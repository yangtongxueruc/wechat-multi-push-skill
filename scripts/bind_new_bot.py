#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""绑定一个新微信到指定 bot：长轮询 getupdates 抓取该微信的 user_id + context_token，
并入 ~/.workbuddy/wechat-clawbot-push/push_cache.json 的 bots map。
用法: python bind_new_bot.py --bot-token "<bot_id>:<secret>" [--timeout 40] [--no-save]
"""
import urllib.request
import urllib.error
import json
import os
import base64
import random
import argparse
import sys
import time

BASE = 'https://ilinkai.weixin.qq.com'
CACHE_PATH = os.path.expanduser('~/.workbuddy/wechat-clawbot-push/push_cache.json')


def uin():
    return base64.b64encode(str(random.getrandbits(32)).encode()).decode()


def getupdates(bt, cursor='', timeout=45):
    body = {'get_updates_buf': cursor, 'base_info': {'channel_version': '1.0.3'}}
    req = urllib.request.Request(
        BASE + '/ilink/bot/getupdates',
        data=json.dumps(body).encode('utf-8'),
        method='POST',
    )
    req.add_header('Content-Type', 'application/json')
    req.add_header('AuthorizationType', 'ilink_bot_token')
    req.add_header('Authorization', 'Bearer ' + bt)
    req.add_header('X-WECHAT-UIN', uin())
    req.add_header('SKRouteTag', '1001')
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode('utf-8'))


def load_cache():
    if os.path.exists(CACHE_PATH):
        try:
            with open(CACHE_PATH, encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_cache(cache):
    tmp = CACHE_PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CACHE_PATH)


def main():
    ap = argparse.ArgumentParser(description='绑定新微信到指定 bot')
    ap.add_argument('--bot-token', required=True, help='新 bot 完整 token，形如 <bot_id>:<secret>')
    ap.add_argument('--timeout', type=int, default=40, help='长轮询等待秒数')
    ap.add_argument('--no-save', action='store_true', help='只打印凭据，不写缓存')
    args = ap.parse_args()

    bt = args.bot_token.strip()
    if ':' not in bt:
        print('ERROR: --bot-token 格式应为 <bot_id>:<secret>')
        sys.exit(1)
    bot_id = bt.split(':')[0]

    deadline = time.time() + args.timeout
    cursor = ''
    while time.time() < deadline:
        try:
            data = getupdates(bt, cursor, timeout=min(40, deadline - time.time() + 2))
        except Exception as e:
            print('getupdates exc:', e)
            time.sleep(2)
            continue
        msgs = data.get('msgs') or []
        if msgs:
            m = msgs[0]
            entry = {
                'bot_token': bt,
                'user_id': m.get('from_user_id'),
                'context_token': m.get('context_token'),
                'get_updates_buf': data.get('get_updates_buf', ''),
            }
            if not entry.get('user_id') or not entry.get('context_token'):
                print('ERROR: 消息缺少 user_id/context_token，消息内容:',
                      json.dumps(m, ensure_ascii=False)[:200])
                sys.exit(1)
            if args.no_save:
                print(json.dumps(entry, ensure_ascii=False, indent=2))
                return 0
            cache = load_cache()
            bots = cache.setdefault('bots', {})
            bots[bot_id] = entry
            save_cache(cache)
            print('BOUND | bot:', bot_id)
            print('user_id:', entry['user_id'])
            print('已并入 push_cache.json 的 bots map（现有 bot:', list(bots.keys()), '）')
            return 0
        if data.get('get_updates_buf'):
            cursor = data['get_updates_buf']
        time.sleep(1)

    print(f'TIMEOUT: {args.timeout} 秒内未收到消息。')
    print('可能原因: 新微信还没发消息 / 消息已被其它消费者消费。请让新微信再发一条后立即重跑。')
    return 1


if __name__ == '__main__':
    sys.exit(main())
