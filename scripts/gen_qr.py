#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 ClawBot 绑定二维码（get_bot_qrcode，无需鉴权）。
用法: python gen_qr.py [--out qr.png] [--bot-type 3]
生成的二维码供一个「新微信」扫码绑定：扫码后打开微信小程序引导页，
在小程序内确认添加，然后给 bot 发任意一条消息完成绑定。
"""
import urllib.request
import urllib.error
import json
import sys
import argparse

import qrcode  # pip install qrcode pillow

API_BASE = 'https://ilinkai.weixin.qq.com'


def fetch_qrcode(bot_type='3'):
    url = f'{API_BASE}/ilink/bot/get_bot_qrcode?bot_type={bot_type}'
    req = urllib.request.Request(url, headers={'iLink-App-ClientVersion': '1'})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        print('HTTP ERROR', e.code, e.read().decode('utf-8')[:200])
        sys.exit(1)
    except Exception as e:
        print('ERROR:', e)
        sys.exit(1)
    if data.get('ret') != 0 or not data.get('qrcode_img_content'):
        print('API FAIL:', json.dumps(data, ensure_ascii=False)[:300])
        sys.exit(1)
    return data


def main():
    ap = argparse.ArgumentParser(description='生成 ClawBot 绑定二维码')
    ap.add_argument('--out', default='clawbot_qr.png', help='输出 PNG 路径')
    ap.add_argument('--bot-type', default='3', help='bot 类型（默认 3）')
    args = ap.parse_args()

    data = fetch_qrcode(args.bot_type)
    img = qrcode.make(data['qrcode_img_content'])
    img.save(args.out)
    print('QR SAVED:', args.out)
    print('qrcode:', data.get('qrcode'))
    print('提示: 二维码约 5 分钟有效。请新微信扫码 → 在小程序内确认 → 给 bot 发一条消息（如「绑定」），然后运行 bind_new_bot.py 完成绑定。')


if __name__ == '__main__':
    main()
