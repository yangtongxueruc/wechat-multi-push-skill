#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 wechat-clawbot-push 的 server.py 从「单用户版」升级为「多 bot 版」。

背景: iLink 生态中每个微信对应一个独立 bot。原版 server.py 只支持一个 bot
（缓存里单个 user_id/context_token），无法给多个微信推送。本脚本用精确文本
替换方式把关键函数升级为多 bot 实现（缓存结构为 bots map，群发=遍历所有 bot）。

用法: python patch_multi_bot.py <server.py 路径> [--check]
  --check  只检测是否已多 bot，不做修改
替换前自动备份为 <路径>.bak-multibot
"""
import sys
import os
import shutil

# ---------- 替换清单：old -> new ----------
# 1) load_cache: 无迁移 -> 兼容旧格式并迁移到 bots map
OLD_LOAD_CACHE = '''def load_cache():
    if os.path.exists(CACHE_PATH):
        try:
            with open(CACHE_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}'''

NEW_LOAD_CACHE = '''def load_cache():
    if os.path.exists(CACHE_PATH):
        try:
            with open(CACHE_PATH, encoding="utf-8") as f:
                d = json.load(f)
        except Exception:
            return {}
        # 旧格式（单 bot 平级字段）-> 新格式 bots map 自动迁移
        if "bots" not in d and (d.get("user_id") and d.get("context_token")):
            bt = ""
            try:
                s = json.load(open(SETTINGS_PATH, encoding="utf-8"))
                for u in s.get("claw", {}).get("users", {}).values():
                    ch = u.get("channels", {}).get("weixinClawBot", {})
                    if ch.get("botToken") and ":" in ch.get("botToken", ""):
                        bt = ch["botToken"]
                        break
            except Exception:
                pass
            bot_id = (bt.split(":")[0]) if bt else "unknown@im.bot"
            d["bots"] = {
                bot_id: {
                    "bot_token": bt,
                    "user_id": d["user_id"],
                    "context_token": d["context_token"],
                    "get_updates_buf": d.get("get_updates_buf", ""),
                }
            }
        return d
    return {}'''

# 2) resolve_token: 支持按 bot 取 token
OLD_RESOLVE = '''def resolve_token(config):
    raw = (config.get("bot_token") or "AUTO").strip()
    if not raw or raw.upper() == "AUTO":
        return get_full_token_from_settings()
    return raw'''

NEW_RESOLVE = '''def resolve_token(config, bot=None):
    """bot 自带 token 优先，否则 config / settings.json 兜底。"""
    if bot and bot.get("bot_token"):
        return bot["bot_token"]
    raw = (config.get("bot_token") or "AUTO").strip()
    if not raw or raw.upper() == "AUTO":
        return get_full_token_from_settings()
    return raw'''

# 3) acquire_token_once: 遍历所有 bot
OLD_ACQUIRE = '''def acquire_token_once(config, wait_seconds=35):
    """长轮询一次获取 context_token + user_id。返回 (ok, detail)。"""
    bearer = resolve_token(config)
    cache = load_cache()
    cursor = cache.get("get_updates_buf", "")
    status, resp = ilink_post(
        "/ilink/bot/getupdates",
        {"get_updates_buf": cursor, "base_info": {"channel_version": CHANNEL_VERSION}},
        bearer,
    )
    if "errcode" in resp:
        return False, "getupdates 失败: errcode %s %s" % (resp.get("errcode"), resp.get("errmsg", ""))
    if resp.get("get_updates_buf"):
        cache["get_updates_buf"] = resp["get_updates_buf"]
    msgs = resp.get("msgs") or []
    if not msgs:
        return False, "本轮无新消息（%d 秒内手机未给 bot 发消息）。token 未变化。" % wait_seconds
    m0 = msgs[0]
    cache["user_id"] = m0.get("from_user_id")
    cache["context_token"] = m0.get("context_token")
    save_cache(cache)
    return True, "已获取并缓存 context_token / user_id: %s" % cache.get("user_id")'''

NEW_ACQUIRE = '''def acquire_token_once(config, wait_seconds=35, bot_id=None):
    """长轮询获取 context_token + user_id（多 bot 版）。
    bot_id 为空时遍历所有已配置 bot。返回 (ok, detail)。"""
    cache = load_cache()
    bots = cache.setdefault("bots", {})
    if not bots:
        try:
            bt = get_full_token_from_settings()
            bid = bt.split(":")[0]
            bots[bid] = {"bot_token": bt, "user_id": "", "context_token": "", "get_updates_buf": ""}
        except Exception as e:
            return False, "无已配置 bot，且 settings.json 读取失败: %s" % e
    if bot_id:
        if bot_id not in bots:
            return False, "未找到 bot: %s。已配置: %s" % (bot_id, list(bots.keys()))
        targets = {bot_id: bots[bot_id]}
    else:
        targets = dict(bots)
    results = []
    any_new = False
    for bid, bot in targets.items():
        bearer = resolve_token(config, bot)
        cursor = bot.get("get_updates_buf", "")
        status, resp = ilink_post(
            "/ilink/bot/getupdates",
            {"get_updates_buf": cursor, "base_info": {"channel_version": CHANNEL_VERSION}},
            bearer,
        )
        if "errcode" in resp:
            results.append("%s: getupdates errcode %s %s" % (bid, resp.get("errcode"), resp.get("errmsg", "")))
            continue
        if resp.get("get_updates_buf"):
            bot["get_updates_buf"] = resp["get_updates_buf"]
        msgs = resp.get("msgs") or []
        if msgs:
            m0 = msgs[0]
            bot["user_id"] = m0.get("from_user_id")
            bot["context_token"] = m0.get("context_token")
            results.append("%s: 已绑定用户 %s" % (bid, bot["user_id"]))
            any_new = True
        else:
            results.append("%s: 本轮无新消息（%d 秒内）" % (bid, wait_seconds))
    save_cache(cache)
    if any_new:
        return True, " | ".join(results)
    return False, " | ".join(results)'''

# 4) _send_one + do_send: 按 bot 发送 / 群发
OLD_SEND = '''def _send_one(text, user_id, ctx, bearer):
    msg = {
        "from_user_id": "",
        "to_user_id": user_id,
        "client_id": "push-" + os.urandom(8).hex(),
        "message_type": 2,
        "message_state": 2,
        "context_token": ctx,
        "item_list": [{"type": 1, "text_item": {"text": text}}],
    }
    body = {"msg": msg, "base_info": {"channel_version": CHANNEL_VERSION}}
    status, resp = ilink_post("/ilink/bot/sendmessage", body, bearer)
    if "errcode" in resp or resp.get("ret") == -2:
        err = resp.get("errcode")
        if err == -14:
            return False, "TOKEN_EXPIRED", "token 已失效(errcode -14)：请重新调用 acquire_token 获取。"
        return False, "SEND_FAIL", "HTTP %s | errcode %s | %s | ret %s" % (status, err, resp.get("errmsg", ""), resp.get("ret"))
    return True, "OK", "HTTP %s | 发送成功" % status


def do_send(text, to_user_id=None):
    """用缓存的 context_token 主动发一条文本到用户微信。返回 (ok, code, detail)。"""
    config = load_config()
    bearer = resolve_token(config)
    cache = load_cache()
    user_id = config.get("user_id") or cache.get("user_id")
    ctx = cache.get("context_token")
    if not user_id or not ctx:
        return False, "NO_TOKEN", "尚未获取 token：请先调用 acquire_token 工具，并在手机给 bot 发一条消息完成绑定，再执行推送。"
    msg = {
        "from_user_id": "",
        "to_user_id": user_id,
        "client_id": "push-" + os.urandom(8).hex(),
        "message_type": 2,
        "message_state": 2,
        "context_token": ctx,
        "item_list": [{"type": 1, "text_item": {"text": text}}],
    }
    body = {"msg": msg, "base_info": {"channel_version": CHANNEL_VERSION}}
    status, resp = ilink_post("/ilink/bot/sendmessage", body, bearer)
    if "errcode" in resp or resp.get("ret") == -2:
        err = resp.get("errcode")
        if err == -14:
            return False, "TOKEN_EXPIRED", "token 已失效(errcode -14)：请重新调用 acquire_token 获取。"
        return False, "SEND_FAIL", "HTTP %s | errcode %s | %s | ret %s" % (status, err, resp.get("errmsg", ""), resp.get("ret"))
    return True, "OK", "HTTP %s | 发送成功" % status'''

NEW_SEND = '''def _send_one(text, bot):
    """用单个 bot 的凭据给其绑定的微信发一条文本。返回 (ok, code, detail)。"""
    bearer = bot.get("bot_token")
    user_id = bot.get("user_id")
    ctx = bot.get("context_token")
    if not bearer or not user_id or not ctx:
        return False, "NO_TOKEN", "该 bot 未完成绑定（缺 bot_token/user_id/context_token），请先扫码并 acquire_token。"
    msg = {
        "from_user_id": "",
        "to_user_id": user_id,
        "client_id": "push-" + os.urandom(8).hex(),
        "message_type": 2,
        "message_state": 2,
        "context_token": ctx,
        "item_list": [{"type": 1, "text_item": {"text": text}}],
    }
    body = {"msg": msg, "base_info": {"channel_version": CHANNEL_VERSION}}
    status, resp = ilink_post("/ilink/bot/sendmessage", body, bearer)
    if "errcode" in resp or resp.get("ret") == -2:
        err = resp.get("errcode")
        if err == -14:
            return False, "TOKEN_EXPIRED", "token 已失效(errcode -14)：请重新调用 acquire_token 获取。"
        return False, "SEND_FAIL", "HTTP %s | errcode %s | %s | ret %s" % (status, err, resp.get("errmsg", ""), resp.get("ret"))
    return True, "OK", "HTTP %s | 发送成功" % status


def do_send(text, to_user_id=None):
    """推送到一个或多个已绑定微信（多 bot 版）。
    to_user_id 为空时群发所有已绑定微信；指定时只推该微信。
    返回 (ok, code, detail)。全部成功 ok=True；部分失败返回 PARTIAL 并列出明细。"""
    config = load_config()
    cache = load_cache()
    bots = cache.get("bots") or {}
    if not bots:
        return False, "NO_TOKEN", "尚未绑定任何微信：请先扫码并调用 acquire_token 完成绑定，再执行推送。"
    if to_user_id:
        matched = {bid: b for bid, b in bots.items() if b.get("user_id") == to_user_id}
        if not matched:
            return False, "NO_USER", "未找到绑定用户: %s。已绑定: %s" % (
                to_user_id, [b.get("user_id") for b in bots.values()])
        targets = matched
    else:
        targets = dict(bots)
    results = []
    all_ok = True
    for bid, bot in targets.items():
        ok, code, detail = _send_one(text, bot)
        results.append("%s(%s…): %s" % (bid, (bot.get("user_id") or "?")[:16], detail))
        if not ok:
            all_ok = False
    if all_ok:
        return True, "OK", "发送成功（%d 个微信）| %s" % (len(targets), " | ".join(results))
    return False, "PARTIAL", "部分失败（目标 %d 个）| %s" % (len(targets), " | ".join(results))'''

# 5) tools/call 里的 push 分支 + bridge_status（MCP 处理逻辑）
OLD_PUSH_BRANCH = '''                cache = load_cache()
                users = cache.get("users") or {}
                if not users or (to_user_id and not users.get(to_user_id)):
                    if auto_acquire:
                        ok, detail = acquire_token_once(config)
                        if not ok:
                            send({"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": "token 缺失且自动获取失败：" + detail + "。请改显式调用 acquire_token 并在手机给 bot 发消息。"}], "isError": True}})
                            continue
                        log("auto_acquire 成功，继续推送。")
                    else:
                        send({"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": "尚未绑定任何用户：请先调用 acquire_token 工具，并在手机给 bot 发一条消息完成绑定，再执行推送。"}], "isError": True}})
                        continue
                ok, code, detail = do_send(text, to_user_id)
                if not ok and code == "TOKEN_EXPIRED":
                    send({"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": detail + " 请调用 acquire_token 重新获取后再推送。"}], "isError": True}})
                    continue
                send({"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": detail}], "isError": not ok}})
            elif name == "acquire_token":
                ok, detail = acquire_token_once(config)
                send({"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": detail}], "isError": not ok}})
            elif name == "bridge_status":
                cache = load_cache()
                users = cache.get("users") or {}
                safe = {}
                for uid, info in users.items():
                    ctx = (info or {}).get("context_token") or ""
                    safe[uid] = {"context_token": (ctx[:12] + "…") if len(ctx) > 12 else (ctx or "(空)")}
                send({"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": json.dumps({
                    "has_context_token": bool(users),
                    "user_count": len(users),
                    "users": safe,
                    "user_ids": list(users.keys()),
                    "cache_path": CACHE_PATH,
                }, ensure_ascii=False)}], "isError": False}})'''

NEW_PUSH_BRANCH = '''                cache = load_cache()
                bots = cache.get("bots") or {}
                ready = any(b.get("user_id") and b.get("context_token") for b in bots.values())
                if not ready or (to_user_id and not any(b.get("user_id") == to_user_id for b in bots.values())):
                    if auto_acquire:
                        ok, detail = acquire_token_once(config)
                        if not ok:
                            send({"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": "token 缺失且自动获取失败：" + detail + "。请改显式调用 acquire_token 并在手机给 bot 发消息。"}], "isError": True}})
                            continue
                        log("auto_acquire 成功，继续推送。")
                    else:
                        send({"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": "尚未绑定任何微信：请先调用 acquire_token 工具，并在手机给 bot 发一条消息完成绑定，再执行推送。"}], "isError": True}})
                        continue
                ok, code, detail = do_send(text, to_user_id)
                if not ok and code == "TOKEN_EXPIRED":
                    send({"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": detail + " 请调用 acquire_token 重新获取后再推送。"}], "isError": True}})
                    continue
                send({"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": detail}], "isError": not ok}})
            elif name == "acquire_token":
                ok, detail = acquire_token_once(config)
                send({"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": detail}], "isError": not ok}})
            elif name == "bridge_status":
                cache = load_cache()
                bots = cache.get("bots") or {}
                safe = {}
                for bid, b in bots.items():
                    ctx = b.get("context_token") or ""
                    safe[bid] = {
                        "user_id": b.get("user_id"),
                        "context_token": (ctx[:12] + "…") if len(ctx) > 12 else (ctx or "(空)"),
                        "ready": bool(b.get("user_id") and ctx),
                    }
                send({"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": json.dumps({
                    "bot_count": len(bots),
                    "bots": safe,
                    "user_ids": [b.get("user_id") for b in bots.values() if b.get("user_id")],
                    "cache_path": CACHE_PATH,
                }, ensure_ascii=False)}], "isError": False}})'''

REPLACEMENTS = [
    (OLD_LOAD_CACHE, NEW_LOAD_CACHE),
    (OLD_RESOLVE, NEW_RESOLVE),
    (OLD_ACQUIRE, NEW_ACQUIRE),
    (OLD_SEND, NEW_SEND),
    (OLD_PUSH_BRANCH, NEW_PUSH_BRANCH),
]


def is_already_multi_bot(src):
    return '"bots" not in d' in src or 'cache.get("bots")' in src


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('-')]
    check_only = '--check' in sys.argv
    if not args:
        print('用法: python patch_multi_bot.py <server.py 路径> [--check]')
        sys.exit(1)
    path = args[0]
    if not os.path.exists(path):
        print('ERROR: 文件不存在:', path)
        sys.exit(1)
    with open(path, encoding='utf-8') as f:
        src = f.read()

    if is_already_multi_bot(src):
        print('已检测到多 bot 版（含 bots map 逻辑），无需升级。')
        return 0
    if check_only:
        print('当前为单用户版，需要升级。')
        return 1

    missing = []
    applied = 0
    for i, (old, new) in enumerate(REPLACEMENTS, 1):
        if old in src:
            src = src.replace(old, new)
            applied += 1
        else:
            missing.append(i)
    if missing:
        print('升级失败：以下替换项未匹配到（server.py 版本可能与预期不同）:')
        for i in missing:
            names = {1: 'load_cache', 2: 'resolve_token', 3: 'acquire_token_once',
                     4: '_send_one/do_send', 5: 'push/bridge_status 分支'}
            print('  -', names.get(i, i))
        print('未做任何修改。请人工对照 SKILL.md 的说明升级。')
        return 1

    bak = path + '.bak-multibot'
    shutil.copy2(path, bak)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(src)
    print('升级完成 ✅ 已替换 %d 处，原文件备份为:' % applied)
    print('  ', bak)
    print('下一步: 1) 同步到其它副本  2) python -m py_compile 校验  3) 重启 WorkBuddy')
    return 0


if __name__ == '__main__':
    sys.exit(main())
