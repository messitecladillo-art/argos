# Security Policy

本项目当前定位为本地开发与实验工具，仅建议在本机或可信内网环境运行。不要在未加鉴权、访问控制和 HTTPS 保护的情况下直接暴露到公网。

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
