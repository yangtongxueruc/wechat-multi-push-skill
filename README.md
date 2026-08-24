# wechat-multi-push

WorkBuddy Skill：绑定多个微信，并通过 ClawBot（微信 iLink 机器人）把一条消息**同时推送到多个微信**。

Bind multiple WeChat accounts and broadcast one message to all of them via ClawBot (WeChat iLink bot).

## 核心原理

- iLink 生态中**每个微信对应一个独立 bot**：`get_bot_qrcode` 每次生成的二维码对应一个新 bot，微信扫码后扫码者成为该 bot 的绑定用户。
- 推送 = 遍历每个 bot，用各自的 `bot_token` + `user_id` + `context_token` 调用 `sendmessage`。
- 凭据只存本地 `~/.workbuddy/wechat-clawbot-push/push_cache.json`。

## 目录结构

```
wechat-multi-push/
├── SKILL.md                      # Skill 主文档（工作流 + 排障）
├── scripts/
│   ├── gen_qr.py                 # 生成绑定二维码（get_bot_qrcode）
│   ├── bind_new_bot.py           # 绑定新微信（长轮询 getupdates 拿 context_token）
│   └── patch_multi_bot.py        # 把单用户 server.py 升级为多 bot 版
└── references/
    └── ilink-api.md              # iLink API 参考与排障
```

## 快速上手

1. 安装并启用 `wechat-clawbot-push` MCP（`~/.workbuddy/mcp.json`，`python -m wechat_clawbot_push --mcp`）
2. 运行 `scripts/patch_multi_bot.py <server.py 路径>` 升级为多 bot 版 → 同步副本 → 重启 WorkBuddy
3. `python scripts/gen_qr.py` 生成二维码 → 新微信扫码并在小程序内确认 → 给 bot 发一条消息
4. `python scripts/bind_new_bot.py --bot-token "<bot_id>:<secret>"` 完成绑定
5. `push_wechat_message(text)` 群发所有微信；`push_wechat_message(text, to_user_id=...)` 指定推送

## 安全

- 所有凭据（bot_token / context_token / user_id）仅存本地，勿提交到仓库。
- 本仓库所有示例均使用占位符，不含任何真实凭据。
- 详细工作流与排障见 `SKILL.md`。

## License

MIT
