# ChatGPT 授权后端接入

本系统的运营页面只保留“一键授权”。真实授权流程由服务端环境变量控制。

## 正式 OAuth 接入

复制配置模板：

```bash
cp 管理系统/.env.example 管理系统/.env
```

然后在 `管理系统/.env` 填入：

```bash
CHATGPT_OAUTH_AUTH_URL="https://你的授权服务/oauth/authorize"
CHATGPT_OAUTH_TOKEN_URL="https://你的授权服务/oauth/token"
CHATGPT_OAUTH_CLIENT_ID="你的 client id"
CHATGPT_OAUTH_CLIENT_SECRET="你的 client secret"
CHATGPT_OAUTH_SCOPE="需要的 scope"
CHATGPT_OAUTH_AUDIENCE="可选 audience"
```

填好后重启管理系统。

回调地址固定为：

```text
http://127.0.0.1:19732/api/chatgpt-auth/callback
```

授权服务回调时可以二选一：

1. 返回 `code`，本系统会用 `CHATGPT_OAUTH_TOKEN_URL` 自动换 `access_token`。
2. 直接返回 `token` 或 `access_token`。

推荐 token 响应包含：

```json
{
  "access_token": "真实访问令牌",
  "refresh_token": "刷新令牌",
  "expires_in": 3600,
  "base_url": "https://api.openai.com",
  "model": "gpt-5.5"
}
```

## 模型调用

系统按 OpenAI-compatible 接口调用：

```text
POST {base_url}/v1/chat/completions
Authorization: Bearer {access_token}
```

`base_url` 可以由授权回调返回，也可以在高级接入配置里临时填写。
