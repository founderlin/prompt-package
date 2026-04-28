# Prompt Package

<img width="748" height="221" alt="icon2" src="https://github.com/user-attachments/assets/764edff7-1d60-4da2-b6e2-4c04c400ba0f" />


> 面向 OpenRouter / DeepSeek / OpenAI 个人用户的 AI 项目记忆工具。
>
> 在项目内挂上你想用的 provider key，选模型聊天 → 自动保存 blabla → 摘要 → 搜索 → 生成 Context Pack，把过去的 AI 对话变成可复用的项目记忆，并能作为 Prompt+ 注入下一次新 blabla。

---

- **目前已经部署在阿里云，域名：139.196.44.96 [139.196.44.96](139.196.44.96)，但是没法用OpenAI、Google、Anthropic等公司的模型**
- **如果要用OpenAI、Google、Anthropic等公司的模型，需要本地部署项目，通过本地vpn实现**

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
# {"status":"ok","service":"promptpackage-backend","version":"0.1.0"}
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
export DATABASE_URL="postgresql://user:pass@host/promptpackage"   # 可选；不配则用 SQLite

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
# {"status":"ok","service":"promptpackage-backend","version":"0.1.0","timestamp":"…"}
```

任何上层的 LB / k8s readiness probe 直接打这个端点即可。

### GitHub Actions 自动部署

仓库 `.github/workflows/deploy.yml` 在 `push` 到 `main` 时通过 SSH 触发 ECS 上的 `~/deploy.sh`（服务器端脚本，负责 `git pull` + 后端 `pip install` + 前端 `npm run build` + `systemctl restart`）。

需要在 GitHub repo → Settings → Secrets and variables → Actions 里配置以下 Secrets：

| Secret | 说明 |
| --- | --- |
| `SSH_HOST` | ECS 公网地址 |
| `SSH_USER` | 登录用户。**该用户必须满足**:(a) 对项目目录有写权限,能直接 `git pull`;(b) 能不经 `sudo -i` / `su` 切换账号就跑 `npm run build`(切换账号会导致 `VITE_*` 环境变量丢失)。当前生产使用 `admin`,项目目录 `/home/admin/prompt-package`,`~/deploy.sh` 即 `/home/admin/deploy.sh` |
| `SSH_KEY_B64`（推荐）/ `SSH_KEY` | SSH 私钥，前者为 base64 单行编码。切换 `SSH_USER` 时记得同步更新,并确保新用户已在 `~/.ssh/authorized_keys` 里信任这把公钥 |
| `VITE_API_BASE_URL` | 前端构建时写入 bundle 的后端 API 地址，例如 `https://api.your-domain.example.com` |
| `VITE_GOOGLE_CLIENT_ID` | 前端构建时写入 bundle 的 Google OAuth Web Client ID；**留空则 Login / Register 页不会出现 Google 一键登录按钮** |

> 踩坑记录：`VITE_*` 变量只在 `vite build` 执行那一刻被内联到产物里，服务器重启 Flask 不会重新读取；因此这两个值必须**在 `npm run build` 之前**出现在 shell env 中。workflow 已经用 `appleboy/ssh-action` 的 `envs:` 把它们转发到远端 shell 会话，`deploy.sh` 只要在调用 `npm run build` 之前照常继承环境即可（脚本本身不需要再 `source` 任何 env 文件）。如果 `deploy.sh` 自己用了 `env -i` 或 `sudo` 清洗环境，请务必把这两个名字加入白名单，否则生产 bundle 里会是空串，Google 按钮又会消失。

> 切换 `SSH_USER` 的 checklist（例如从 `deploy` 换成 `admin`）：
> 1. 新用户的 `~/.ssh/authorized_keys` 包含 `SSH_KEY_B64` 对应的公钥；
> 2. 新用户对项目目录（本例 `/home/admin/prompt-package`）有写权限，`git pull` 不报 `Permission denied`；
> 3. `~/deploy.sh` 以新用户身份存在且可执行（`chmod +x`）；
> 4. `npm` / `node` 在新用户的登录 `PATH` 里能被找到——常见坑是 nvm 只在交互式 shell 中注入 PATH，非交互 SSH 登录会拿不到。建议在 `deploy.sh` 头部显式 `export PATH="$HOME/.nvm/versions/node/<ver>/bin:$PATH"` 或 `source ~/.nvm/nvm.sh`；
> 5. 如果后端服务通过 `systemctl` 重启，并且新用户不是 systemd unit 的 owner，需要 `NOPASSWD` sudo 白名单（例：`admin ALL=(root) NOPASSWD: /bin/systemctl restart promptpackage`）。

