---
name: wechat-multi-push
description: 基于 wechat-clawbot-push MCP（微信 ClawBot / iLink 协议）绑定多个微信并群发推送。当用户要求"把推送同时发到多个微信"、"给另一个微信也推送"、"绑定新微信接收推送"、"多个微信收晨报/故事"、"ClawBot 推送给多个账号"、生成 ClawBot 绑定二维码、排查微信推送失败或 token 获取失败时使用。涵盖 server.py 多 bot 改造、二维码生成、扫码绑定、context_token 获取、群发/指定推送与常见排障。
agent_created: true
---

# 多微信 ClawBot 绑定与群发推送

## 用途
让 WorkBuddy 自动化（或手动）通过微信 ClawBot（iLink 协议）把一条消息同时推送到**多个微信**。核心机制：每个微信对应一个独立 bot 实例，推送 = 对每个 bot 调用 sendmessage。

## 前置条件
- 已安装并启用 wechat-clawbot-push MCP（stdio，注册于 `~/.workbuddy/mcp.json`，command 为 `python -m wechat_clawbot_push --mcp`）
- 至少一个微信已完成绑定（`~/.workbuddy/wechat-clawbot-push/push_cache.json` 有 token）
- Python 3.9+；如需生成二维码图片：`pip install qrcode pillow`

## 核心架构（务必先理解）
1. **每个微信 = 一个独立 bot**：`GET https://ilinkai.weixin.qq.com/ilink/bot/get_bot_qrcode?bot_type=3` 每次返回的二维码对应一个**新 bot 实例**（bot_id 形如 `<16位hex>@im.bot`）。微信扫码后，扫码者成为该 bot 的绑定用户。扫码打开的页面是微信小程序引导页（liteapp.weixin.qq.com），需在小程序内完成确认。
2. **每个 bot 三件套凭据**：
   - `bot_token`：形如 `<bot_id>:<secret>`（所有请求的 Bearer 鉴权）
   - `user_id`：绑定微信 id，形如 `<xxx>@im.wechat`（来自入站消息 from_user_id）
   - `context_token`：随**入站消息**返回（发送消息给该用户必须携带）
3. **推送**：`POST /ilink/bot/sendmessage`，带 bot_token 鉴权 + to_user_id + context_token。
4. **收消息**：`POST /ilink/bot/getupdates`（长轮询），游标 `get_updates_buf` 推进。消息被消费后**不会再次返回**（一次性）。
5. **二维码状态**：`GET /ilink/bot/get_qrcode_status?qrcode=<qrcode>`（带 bot_token 鉴权）返回该二维码对应新 bot 的 `bot_token` / `ilink_bot_id` / `ilink_user_id`，用于获取新 bot 的凭据。

## 文件位置
- MCP 源码（可能多副本，改动需全部同步）：`~/.workbuddy/binaries/python/versions/<ver>/Lib/site-packages/wechat_clawbot_push/server.py`、`~/.workbuddy/binaries/python/envs/default/Lib/site-packages/wechat_clawbot_push/server.py`、`~/.workbuddy/binaries/python/pkg_clawbot/wechat_clawbot_push/server.py`
- 运行时缓存（多 bot）：`~/.workbuddy/wechat-clawbot-push/push_cache.json`
- MCP 注册：`~/.workbuddy/mcp.json`

## push_cache.json 多 bot 结构
```json
{
  "bots": {
    "<bot_id_1>@im.bot": {
      "bot_token": "<bot_id_1>@im.bot:<secret>",
      "user_id": "<user_id_1>@im.wechat",
      "context_token": "<ctx_1>",
      "get_updates_buf": "<buf_1>"
    },
    "<bot_id_2>@im.bot": {
      "bot_token": "...",
      "user_id": "...",
      "context_token": "...",
      "get_updates_buf": "..."
    }
  }
}
```

## 工作流 A：把 server.py 升级为多 bot 版
若 MCP 工具 `bridge_status` 返回的字段是 `user_count/users`（旧单用户版），需先升级：
1. 运行 `scripts/patch_multi_bot.py <server.py 路径>`（自动替换关键函数为多 bot 版，替换前自动备份）
2. 校验语法：`python -m py_compile <server.py>` 通过
3. 把同一文件同步到其余副本
4. **重启 WorkBuddy**（MCP 子进程只在应用启动时加载代码，UI 断连重连不重启子进程）
5. 验证：`bridge_status` 应返回 `bot_count` 与 `bots`（含 ready 标志）

## 工作流 B：绑定一个新微信
1. 生成二维码：`python scripts/gen_qr.py --out ~/clawbot_qr.png`（调 get_bot_qrcode，无需鉴权；约 5 分钟有效，过期重新生成）。把 PNG 展示给用户。
2. 请**新微信**扫码，并在小程序引导页内完成确认（确认后 bot 出现在该微信聊天列表）。
3. 让新微信给 bot 发任意一条消息（如「绑定」）。
4. 获取新 bot 凭据：
   - 若已从 `get_qrcode_status` 或其它途径拿到新 bot 的 `bot_token`：直接进入第 5 步。
   - 若不知道新 bot 的 token：用已有任一 bot 的 token 调 `get_qrcode_status?qrcode=<刚才生成的qrcode>` 获取。
5. 运行 `python scripts/bind_new_bot.py --bot-token "<bot_id>:<secret>"`：长轮询 getupdates 40 秒，抓到新微信消息后把 `user_id` + `context_token` + `get_updates_buf` 并入 push_cache.json 的 `bots` map。
6. 验证：`bridge_status` 出现新 bot 且 `ready=true`；发一条测试推送确认新微信收到。
7. 若提示「本轮无新消息」：消息可能已被其他消费者消费（见排障），让新微信**再发一条**并立即重跑。

## 工作流 C：推送
- 群发所有微信：`push_wechat_message(text)`（不传 to_user_id）
- 只推指定微信：`push_wechat_message(text, to_user_id="<user_id>@im.wechat")`（user_id 用 bridge_status 查询）
- 自动化集成：prompt 中要求「推送前先 bridge_status 自检；失败回退 Server酱」；无人值守运行**不要**调用 acquire_token 阻塞等待（需手机配合）。

## 排障
| 现象 | 原因 | 解决 |
|------|------|------|
| acquire_token 总提示「本轮无新消息」 | 消息被 WorkBuddy 内置 WeixinClawBotClient（polling，约 18s 一轮）或其它消费者抢走，共用同一游标 | 临时把 `~/.workbuddy/settings.json` 中 `claw.users.*.channels.weixinClawBot.enabled` 改为 false → **重启 WorkBuddy**（配置仅启动时读取）→ 完成绑定后恢复 true |
| bind 脚本第二次跑拿不到消息 | 消息已被首次 getupdates 消费（游标推进，一次性） | 让新微信再发一条，立即重跑 bind |
| 推送返回 errcode -14 | context_token 失效 | 让该微信再发一条消息，重新执行 bind 刷新 token |
| 推送报「尚未绑定任何微信」 | push_cache.json 为空，或 MCP 进程未加载多 bot 版 | 检查 push_cache.json 的 `bots`；确认 server.py 已升级并重启 WorkBuddy |
| 扫码后 bot 没出现在聊天列表 | 只打开了小程序，未在小程序内确认 | 引导用户扫码后在小程序页面点击确认/添加 |

## 安全
- 所有凭据（bot_token / context_token / user_id）只存本地 push_cache.json，勿写入日志、代码或文档。
- 分享脚本与文档时必须使用占位符（`<bot_id>@im.bot`、`<user_id>@im.wechat`、`<secret>`），不得包含真实 token。
- bot_token 等敏感值切勿提交到 GitHub 或公开仓库。
