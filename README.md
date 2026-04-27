# Prompt Package

<img width="748" height="221" alt="icon2" src="https://github.com/user-attachments/assets/764edff7-1d60-4da2-b6e2-4c04c400ba0f" />


> 面向 OpenRouter / DeepSeek / OpenAI 个人用户的 AI 项目记忆工具。
>
> 在项目内挂上你想用的 provider key，选模型聊天 → 自动保存 blabla → 摘要 → 搜索 → 生成 Context Pack，把过去的 AI 对话变成可复用的项目记忆，并能作为 Prompt+ 注入下一次新 blabla。

---

## 项目结构

```
prompt-package/
├── backend/        # Flask 后端，提供 REST API
├── frontend/       # Vue.js 前端，调用后端 API
├── README.md       # 你正在看的这份
└── .gitignore
```

前后端完全分离，前端通过 HTTP 访问后端 REST API。

---

## 技术栈

- **前端**：Vue 3 + Vite + Vue Router + Axios
- **后端**：Flask + Flask-CORS（后续轮会接入 SQLAlchemy / JWT / OpenRouter）
- **数据库**：MVP 使用 SQLite（后续轮接入）
- **样式**：自研 Material 风格基础样式（后续轮）

---

## 快速开始

### 1. 启动后端（Flask）

```bash
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # 按需修改
python app.py
```

后端默认运行在 `http://127.0.0.1:5001`。

健康检查：

```bash
curl http://127.0.0.1:5001/api/health
# {"status":"ok","service":"imrockey-backend","version":"0.1.0"}
```

### 2. 启动前端（Vue）

新开一个终端：

```bash
cd frontend
npm install
cp .env.example .env               # 按需修改 VITE_API_BASE_URL
npm run dev
```

前端默认运行在 `http://127.0.0.1:5173`，打开浏览器即可看到首页。
首页会自动调用后端 `/api/health` 并把响应展示出来；如果展示 `ok`，说明前后端联通成功。

---

## 环境变量

### Backend（`backend/.env`）

| 变量 | 说明 | 示例 |
| --- | --- | --- |
| `FLASK_ENV` | 运行环境 | `development` |
| `FLASK_HOST` | 监听地址 | `127.0.0.1` |
| `FLASK_PORT` | 监听端口 | `5001` |
| `SECRET_KEY` | Flask 会话密钥 | 任意随机字符串 |
| `CORS_ORIGINS` | 允许跨域的前端地址，逗号分隔 | `http://127.0.0.1:5173,http://localhost:5173` |

额外可选：`DATABASE_URL`、`JWT_SECRET_KEY`、`JWT_EXPIRES_DAYS`、`ENCRYPTION_KEY`（所有 provider Key 静态加密，未配置时从 `SECRET_KEY` 派生，prod 必须显式配置）、`OPENROUTER_BASE_URL`、`DEEPSEEK_BASE_URL`、`OPENAI_BASE_URL`（私有网关 / 反代覆盖用）、`LLM_VERIFY_TIMEOUT_SECONDS`（兼容老名字 `OPENROUTER_TIMEOUT_SECONDS`）、`GOOGLE_CLIENT_ID`（R15 Google 一键登录的 OAuth Web Client ID；未配置时 `/api/auth/google` 直接 503 拒绝，密码登录正常）。

### Frontend（`frontend/.env`）

| 变量 | 说明 | 示例 |
| --- | --- | --- |
| `VITE_API_BASE_URL` | 后端 API 地址 | `http://127.0.0.1:5001` |
| `VITE_GOOGLE_CLIENT_ID` | （可选，R15）Google OAuth Web Client ID。设置后 Login / Register 页会渲染官方 Google 按钮；留空则按钮不出现，密码登录不变 | `xxx.apps.googleusercontent.com` |

---

## 开发规约

- 前端不直接调用任何 LLM provider，所有 LLM 请求经由后端转发。
- 用户的 provider API Key（OpenRouter / DeepSeek / OpenAI）仅在后端加密存储，绝不出现在前端日志或响应中。
- API 路径统一以 `/api` 为前缀。
- 提交代码前请确认 `.env` 不会被推到远端（`.gitignore` 已处理）。

---

## 部署（Production-ready 指南）

> R12 已加入 production guard，启动时会强制校验三把密钥都不是 dev 默认值，任何一项漏配都会 `RuntimeError` 不起服。

### 后端（Flask + gunicorn）

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install gunicorn==23.0.0          # 见 requirements.txt 末尾的可选段

# 生成三把强密钥（举例）
SECRET_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(48))")
JWT_SECRET_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(48))")
ENCRYPTION_KEY=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")

# 一定要 export 进环境，**不要**写进随包发布的 .env
export FLASK_ENV=production
export SECRET_KEY JWT_SECRET_KEY ENCRYPTION_KEY
export CORS_ORIGINS="https://your-frontend.example.com"
export DATABASE_URL="postgresql://user:pass@host/imrockey"   # 可选；不配则用 SQLite

gunicorn -w 4 -b 0.0.0.0:5001 'app:app'
```

> SQLite 建表 + 轻量迁移会在第一次进程启动时跑完；接 PostgreSQL 时建议改走 Alembic。

### 前端（Vite static build）

```bash
cd frontend
echo "VITE_API_BASE_URL=https://api.your-domain.example.com" > .env.production
npm install
npm run build      # 输出到 frontend/dist/
```

把 `dist/` 直接发到 Nginx / Cloudflare Pages / Vercel / Netlify 任何静态托管即可。注意：

- 因为是 SPA，需要把所有未命中的路径回退到 `index.html`（Nginx `try_files $uri /index.html;`，Vercel `rewrite "/(.*)" "/index.html"`）。
- `VITE_API_BASE_URL` 必须指向后端的公网域名；CORS 的允许域名要在后端 `CORS_ORIGINS` 里同步加上。

### 健康检查

```bash
curl https://api.your-domain.example.com/api/health
# {"status":"ok","service":"imrockey-backend","version":"0.1.0","timestamp":"…"}
```

任何上层的 LB / k8s readiness probe 直接打这个端点即可。
