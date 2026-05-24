# Security Policy

本项目当前定位为本地开发与实验工具，仅建议在本机或可信内网环境运行。不要在未加鉴权、访问控制和 HTTPS 保护的情况下直接暴露到公网。

## 内置安全机制

- **API 鉴权**：设置 `API_TOKEN` 环境变量后，除 `/`、`/static/*`、`/mcp/*`、`/api/hermes/status` 外所有请求均需携带 `X-API-Key` 或 `Authorization: Bearer` 头
- **WebSocket 鉴权**：终端 WebSocket 连接支持 `X-API-Key` 头、`Authorization: Bearer` 头或 `?token=` 查询参数
- **速率限制**：基于 IP 的滑动窗口限流，默认每 IP 每分钟 100 请求，可通过 `RATE_LIMIT_MAX`/`RATE_LIMIT_WINDOW` 配置
- **CORS 控制**：生产模式下通过 `CORS_ORIGINS` 精确定义允许的跨域来源，未设置则拒绝所有跨域请求
- **API Key 脱敏**：模型配置的 API Key 在 API 响应中自动脱敏（`sk-a...1234`），真实密钥仅在内部使用时解密
- **密钥管理**：支持 `.env` 文件、环境变量和 Docker secrets（`/run/secrets/`）三种方式注入敏感配置
- **请求 ID 追踪**：每个请求注入 `X-Request-ID`，支持客户端传递或自动生成
- **Docker 安全**：容器以非 root 用户 `hermes` 运行，最小化攻击面

## 生产部署 Checklist

- [ ] 设置 `SECRET_KEY`（`python -c "import secrets; print(secrets.token_hex(32))"`）
- [ ] 设置 `API_TOKEN` 启用鉴权
- [ ] 设置 `CORS_ORIGINS` 限制跨域来源
- [ ] 配置 `RATE_LIMIT_MAX` 防止滥用
- [ ] 使用 HTTPS 反向代理（nginx/Caddy）终止 TLS
- [ ] 将 `FLASK_DEBUG` 设为 `0`
- [ ] 启用 `LOG_FORMAT=json` 结构化日志

## 敏感信息

请不要提交或公开以下内容：

- `.env` 或任何包含真实环境变量的配置文件
- `data/` 下的数据库文件，例如 SQLite 运行时数据库
- Hermes profile 配置、记忆、工作区内容或 `config.yaml`
- MCP server 的 URL、headers、env、token、API key、password、secret 等凭据
- 任何真实用户数据、对话记录、日志或终端输出中的敏感片段

## 建议

- 使用 `.env.example` 作为配置模板，不要把真实 `.env` 加入版本控制。
- 发布前检查 `git status` 和 `git diff`，确认没有敏感文件或凭据。
- 如果需要部署到共享环境，请先增加认证、权限控制、CSRF 防护、HTTPS 和 secret 加密存储。
