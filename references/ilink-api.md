# iLink ClawBot API 参考

腾讯微信 iLink 机器人协议（`https://ilinkai.weixin.qq.com`）要点，供绑定/推送排障使用。
所有请求 Header：
- `Content-Type: application/json`
- `AuthorizationType: ilink_bot_token`
- `Authorization: Bearer <bot_id>:<secret>`
- `X-WECHAT-UIN: base64(随机uint32)`（防重放，每次请求重新生成）
- `SKRouteTag: 1001`

## 1. 生成绑定二维码（无需鉴权）
```
GET /ilink/bot/get_bot_qrcode?bot_type=3
Header: iLink-App-ClientVersion: 1
```
响应：
```json
{
  "ret": 0,
  "qrcode": "<16位hex>",
  "qrcode_img_content": "https://liteapp.weixin.qq.com/q/<path>?qrcode=<qrcode>&bot_type=3"
}
```
- 每次调用返回一个**新 bot** 的引导二维码；约 5 分钟有效。
- 微信扫码 → 打开微信小程序引导页 → 小程序内确认添加 → bot 出现在该微信聊天列表。
- 扫码者即成为该 bot 的绑定用户。

## 2. 查询二维码状态 / 获取新 bot 凭据（需鉴权）
```
GET /ilink/bot/get_qrcode_status?qrcode=<qrcode>
```
响应（已扫码确认后）：
```json
{
  "baseurl": "https://ilinkai.weixin.qq.com",
  "bot_token": "<bot_id>:<secret>",
  "ilink_bot_id": "<bot_id>@im.bot",
  "ilink_user_id": "<user_id>@im.wechat"
}
```
未确认/过期返回 `{"ret": 0, "status": "wait"|"expired"}`。

## 3. 收消息 / 获取 context_token（需鉴权）
```
POST /ilink/bot/getupdates
Body: {"get_updates_buf": "<游标>", "base_info": {"channel_version": "1.0.3"}}
```
- 长轮询（可挂 30-45 秒）；有消息立即返回。
- 响应含 `msgs`（消息数组）与新的 `get_updates_buf`（游标）。
- 消息字段：`from_user_id`（发消息的微信 id）、`context_token`（回复该用户必须带）、`item_list[].text_item.text`（文本内容）。
- **游标推进后消息不会再次返回**——需要用户消息时，必须在长轮询期间让用户发消息。

## 4. 发送消息（需鉴权）
```
POST /ilink/bot/sendmessage
Body:
{
  "msg": {
    "from_user_id": "",
    "to_user_id": "<user_id>@im.wechat",
    "client_id": "push-<hex>",
    "message_type": 2,
    "message_state": 2,
    "context_token": "<ctx>",
    "item_list": [{"type": 1, "text_item": {"text": "..."}}]
  },
  "base_info": {"channel_version": "1.0.3"}
}
```
- `bot_token` 必须是**该用户绑定的那个 bot**（每个微信一个 bot，凭据不能混用）。
- 错误码：`errcode -14` = context_token 失效，需让该用户重发消息刷新。

## 5. 多 bot 数据模型
每个 bot 一份运行时状态，存于 `~/.workbuddy/wechat-clawbot-push/push_cache.json`：
```json
{
  "bots": {
    "<bot_id>@im.bot": {
      "bot_token": "<bot_id>:<secret>",
      "user_id": "<user_id>@im.wechat",
      "context_token": "<ctx>",
      "get_updates_buf": "<buf>"
    }
  }
}
```
推送群发 = 遍历 `bots`，每个 bot 用自己的 `bot_token` + `user_id` + `context_token` 调 sendmessage。

## 6. 已知竞争问题
WorkBuddy 内置的 WeixinClawBotClient（`claw.users.*.channels.weixinClawBot`，polling 模式约 18 秒一轮）
与自定义 MCP 桥可能共用同一 bot 的 getupdates 游标，会抢消息。
- 症状：`acquire_token` / bind 脚本反复「本轮无新消息」，但用户确认已发消息。
- 解决：临时把 `~/.workbuddy/settings.json` 中 `claw.users.*.channels.weixinClawBot.enabled` 改 `false`，
  **重启 WorkBuddy**（配置仅启动时读取），完成绑定后恢复 `true` 并再次重启。
