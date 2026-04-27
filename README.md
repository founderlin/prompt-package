# imrockey

> 面向 OpenRouter / DeepSeek / OpenAI 个人用户的 AI 项目记忆工具。
>
> 在项目内挂上你想用的 provider key，选模型聊天 → 自动保存对话 → 摘要 → 搜索 → 生成 Context Pack，把过去的 AI 对话变成可复用的项目记忆，并能作为 Prompt+ 注入下一次新对话。

---

## 项目结构

```
imrocky/
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

---

## Roadmap（按轮次推进）

- [x] **R1** 项目基础架构（健康检查打通）
- [x] **R2** 基础 UI Shell（Sidebar + Header + Dashboard + 空状态体系 + 路由）
- [x] **R3** 用户注册 / 登录 / 退出 + JWT 鉴权 + 路由护卫
- [x] **R4** OpenRouter API Key 设置页（保存 / 删除 / 测试连接 + 加密存储）
- [x] **R5** Project 项目管理（创建 / 列表 / 编辑 / 删除 / 用户隔离）
- [x] **R6** Project Detail 项目详情页（元数据 + 编辑 / 删除 + Conversations / Memories / Context Packs 占位）
- [x] **R7** 项目内 Chat 页面（创建对话 / 选模型 / 调 OpenRouter / 自动保存 user+assistant 消息 / 历史回灌）
- [x] **R8** Conversation 对话列表与详情（跨项目 + 项目内列表带 message_count；Dashboard Recent 接真实数据；聊天页左侧对话侧栏支持切换 / New / Delete）
- [x] **R9** Conversation 摘要与记忆提取（聊天页 Wrap up → JSON summary + 结构化 memories；按 kind 分组展示在聊天页 + 项目详情页；可单条删除；二次 wrap 会覆盖旧记忆）
- [x] **R10** Search 跨项目搜索（messages / memories / conversations 三类，user 隔离 + LIKE 转义；前端 debounce 输入框 + 分段 tabs + 命中关键词高亮，消息结果支持 `#msg-<id>` 锚点直达原对话）
- [x] **R11** Context Pack Generator（项目内把 memories 喂给模型 → 生成可粘贴的 Markdown Context Pack；落库 + 复制 + 列表 + 单条详情/编辑/删除 + 跨项目最近列表）
- [x] **R12** 打磨与发布前检查（共享时间工具 / Dashboard 现状指引 / document.title 同步 / 首屏 spinner / 后端生产 guard + 统一 JSON 错误 + gunicorn 备选 / OpenRouter UA 统一 / 部署文档）
- [x] **R13** Context Pack 作为 Prompt Plus（聊天页 Prompt+ pill；新对话/对话过程中可挂载/切换/移除任意 pack 含跨项目；后端在每次 OpenRouter 调用前注入 pack body 为 system 消息，但不污染 messages 历史）
- [x] **R14** 多 Provider 支持（OpenRouter / DeepSeek / OpenAI 同库共存；每个用户每家一把 key 加密存储；聊天页模型下拉按 provider 分组 + 未配 key 即时提醒；老 OpenRouter key 自动迁移进新表）
- [x] **R15** Google 一键登录（GIS id_token 流程：前端 Google 官方按钮 → 后端验证 id_token → 按 `sub` / 已验证 email 找/建用户；与现有密码登录共存；`GOOGLE_CLIENT_ID` 未配置时整个特性自动隐藏）

### R15 速览（Google 一键登录）

- **数据模型**
  - `users` 表新增三列：`google_sub`（VARCHAR(64)，UNIQUE INDEX）/ `google_email` / `auth_provider`（`'password'` 或 `'google'`）；启动时通过 `_apply_lightweight_migrations` 自动 ALTER + 建唯一索引，老用户行原状不动。
  - `User.password_hash` 仍是 NOT NULL，但 Google-only 用户写入哨兵值 `!google-oauth-only!`，`check_password` 永远返回 False，配合新 `has_password` 属性 / `mark_passwordless()` 方法。
  - `User.to_dict()` 多返 `auth_provider` / `has_password` / `google_linked` 三个字段，前端可据此判断「Google 链接但还没设密码」「密码已设 + 已链 Google」等状态。
- **后端**
  - 新依赖：`google-auth==2.35.0`，仅用 `verify_oauth2_token` 校验 id_token 签名 + `aud`（== `GOOGLE_CLIENT_ID`）+ `iss`（accounts.google.com）+ `exp` 未过期。
  - `auth_service.login_with_google_id_token(id_token)`：
    1. 先按 `sub` 命中 → 直接返用户 + 顺带刷 `google_email`；
    2. 否则若 `email_verified=True` 且能按 email 找到老用户 → 把 `google_sub` 链上去，**保留原密码**；
    3. 否则创建新 user：`auth_provider='google'`、写入 `google_sub` / `google_email`、`mark_passwordless()`；
    4. `email_verified=False` 永远不 auto-link 进老账号，避免别人借未验证邮箱劫持你的 imrockey 账户。
  - 路由：`POST /api/auth/google`（body `{ id_token }` 或 `{ credential }` 别名）→ 返 `{ token, user }`；`GET /api/auth/google/config` 给前端探活，未配 `GOOGLE_CLIENT_ID` 返 `enabled: false`，`/google` 直接 503。
- **前端**
  - 新组件 `components/auth/GoogleSignInButton.vue`：动态 inject `https://accounts.google.com/gsi/client`，调 `google.accounts.id.initialize` + `renderButton`，把 `response.credential` 通过 `@credential` emit 出去；`VITE_GOOGLE_CLIENT_ID` 未配置时整个组件隐身。
  - `api/auth.js` 加 `google({ idToken })` / `googleConfig()`；`stores/auth.js` 加 `loginWithGoogle(idToken)`。
  - Login / Register 两页都加 SSO 区：Google 按钮 + 「or sign in / up with email」分割线，错误以独立 banner 展示，跟密码表单分离；登录成功后 router 走 `redirect` query 跳回原页面。
- **使用回路**
  1. 在 [Google Cloud Console](https://console.cloud.google.com/apis/credentials) 建一个 Web 应用 OAuth Client，把 `http://127.0.0.1:5173` 加到 Authorized JS origins；
  2. 把同一个 client id 写到 `backend/.env` 的 `GOOGLE_CLIENT_ID` 与 `frontend/.env` 的 `VITE_GOOGLE_CLIENT_ID`；
  3. 重启前后端 → Login / Register 页顶部就会出现官方 Google 按钮，点一下即登录。
- **验证**：`scripts/smoke_google_login.py` 8 条断言（无 client id 时 503 / 无效 id_token 401 / 缺 id_token 400 / 首次登录创建 passwordless 用户 / 同 sub 复登幂等 / verified-email 自动 link 不丢密码 / unverified-email 不 auto-link / `/google/config` 报告状态）全部通过；R14 / R13 / R11 老 smoke 同时回归通过。

### R14 速览（Multi-provider: OpenRouter / DeepSeek / OpenAI）

- **数据模型**
  - 新表 `provider_credentials`（user_id × provider 唯一）：每条存某用户某家 provider 的加密 key + label / 最近验证时间 + 计费元数据；同一用户同一家只保留 1 条，重存覆盖。
  - `conversations.provider` / `messages.provider`（VARCHAR(40) NULL，索引）：记录该对话 / 这条 assistant 消息走的是哪个 API gateway；老行 NULL 视为 `openrouter` 兼容。
  - SQLite 启动时通过 `_apply_lightweight_migrations` 自动建表 + 加列 + 把 `users.openrouter_api_key_encrypted` 老 key 复制进 `provider_credentials`，**老用户零操作即可平迁**。
- **后端**
  - 新模块：`app/providers.py` 三家 provider 静态配置（base_url / verify endpoint / 推荐 summary 模型 / extra headers / docs 链接）+ env 变量覆盖。
  - 新服务：`app/services/llm_service.py` 通用 LLM 客户端（`verify_api_key(api_key, provider=)` / `chat_completion(api_key, messages, provider=, ...)`）；OpenRouter `/key`、DeepSeek/OpenAI `/models` 都被它统一封装；老 `openrouter_service.py` 退化为兼容 shim。
  - 新服务：`app/services/credentials_service.py` 多 provider 凭据 CRUD（`save_key` / `delete_key` / `test_key` / `status_for` / `list_status` / `first_configured_provider`）；老 `settings_service.py` 退化为兼容 shim，老 `/api/settings/openrouter-key/*` 路由保留为 alias。
  - `chat_service.create_conversation` / `send_user_message` 多吃一个 `provider` 参数，按 provider 取对应 key、调对应 endpoint，并把 provider 写入 conversations / messages 表。
  - `memory_service.summarize_conversation` 和 `context_pack_service.generate` 优先沿用对话所属 provider，否则走 `first_configured_provider` 兜底，并使用该 provider 的 `summary_model`，与你最新挂的 key 自动对齐。
  - 新路由组 `/api/settings/providers/*`：
    - `GET /api/settings/providers` 列三家状态（label / configured / masked / 文档 URL / 最近 verify）；
    - `GET / PUT / DELETE /api/settings/providers/<provider>/key` 单家 key 管理；
    - `POST /api/settings/providers/<provider>/test` 主动验活。
- **前端**
  - 新文件 `src/api/providers.js` 包了上面整套接口；老 `openrouter-key` 接口仍可用。
  - Settings 页改成「provider 卡片列表」：每家一张 `ProviderKeyCard`，显示 docs 链接 / 当前 masked / 输入框（show/hide 切换）/ Test / Save / Remove，状态独立持久。
  - `src/constants/models.js` 给每个 model 加 `provider` + `vendor` + `hint`；新增 `groupedModelOptions()`，聊天页下拉按 provider 分组渲染（OpenRouter / DeepSeek / OpenAI 三个 `<optgroup>`）。
  - 聊天页选某个未配 key 的 provider → 顶部 banner + `composer` 自动 disable，引导去 Settings 配 key；自定义模型模式还可单独选 provider。
  - 创建对话 / 发送消息时，把 `provider` 一并提交，后端自动选 key + endpoint。
  - Dashboard 「Get started」第一步从 “Add OpenRouter key” 改成 “Add an LLM provider key”，已配的 provider 用 chip 列出。
- **环境变量**
  - 新增可选：`DEEPSEEK_BASE_URL` / `OPENAI_BASE_URL` / `LLM_VERIFY_TIMEOUT_SECONDS`（统一三家探活超时，老名字 `OPENROUTER_TIMEOUT_SECONDS` 仍兼容）。
  - 安全规约不变：`ENCRYPTION_KEY` 静态加密所有 provider key；明文 key 永不离开服务端；prod 仍由 `assert_safe_for_production` 兜底。
- **验证**：`scripts/smoke_multi_provider.py` 7 条断言（多家 key 独立保存 / 老 OpenRouter shim 仍生效 / `User.to_dict().providers` 反映真实状态 / `send_user_message` 按 provider 路由到对应 endpoint / 不支持的 provider 立即 422 / 删某家 key 不影响其他家 / `first_configured_provider` 优先级）全部通过；R13 / R11 老 smoke 同时回归通过。

### R13 速览（Context Pack as Prompt Plus）

- **数据模型**
  - `conversations.context_pack_id`（INTEGER NULL，逻辑外键到 `context_packs.id`）；
  - SQLite 启动时通过轻量迁移自动 `ALTER TABLE` 加列，老对话原状不动；
  - `Conversation.to_dict()` 多返 `context_pack: { id, title, project_id }` 便于前端无需二次请求。
- **后端**
  - `chat_service.create_conversation(..., context_pack_id=)` 创建时即可挂 pack；
  - 新增 `chat_service.set_context_pack(user, conv_id, pack_id|None)`：挂载 / 替换 / 卸下，所有路径 user 隔离硬走 404；
  - `_build_message_payload` 把 pack body 包在固定 preamble 里，作为 leading `system` 消息注入每次发给 OpenRouter 的 messages 数组；**绝不**写进 `messages` 表，所以替换 / 删除 pack 不会改写历史；
  - pack 被删后 SQLAlchemy joined-load 会返回 `None`，`send_user_message` 自动 fallback 到 "无 pack" 模式，已被 smoke 覆盖；
  - 路由：`POST /api/projects/<pid>/conversations` 接 `context_pack_id`；新增 `PATCH /api/conversations/<cid>` body 形如 `{"context_pack_id": <id|null>}`。
- **前端**
  - 聊天页 header 加 **Prompt+** pill：未挂载显示 `Add Context Pack`，挂载后显示 pack 标题 + 「×」一键移除；
  - 点击触发 pack 选择器模态框：双 tab（**This project** / **All your packs**）+ 客户端搜索（按标题或正文预览），跨项目 pack 会带项目 chip 标签；选完直接 PATCH 绑定，下条消息开始生效；
  - `ProjectChatView` 的 `chatApi.updateConversation` 复用之前的 `apiClient`，不引入新依赖。
- **使用回路**
  1. 先在某个项目走完 Wrap up + Generate Context Pack；
  2. 进任意项目的聊天页（同项目或别的项目都行），点 Prompt+ → 选刚生成的 pack；
  3. 之后每条 user 消息都带这份 pack 作为系统级背景，模型回答会自动以这份背景为前提；
  4. 切到别的 pack 或点 × 移除 → 立即生效，且不污染历史。
- **验证**：`scripts/smoke_prompt_plus.py` 8 条断言全部通过（创建即挂载 / 跨用户拒绝 / 跨项目挂载 / 卸下 / 替换 / 系统消息注入 / 卸下后无注入 / 删除 pack 不破坏对话）。

### R12 速览（打磨与发布前检查）

- **前端**
  - 共享时间工具：新建 `frontend/src/utils/time.js`（`relativeTime` / `formatDateTime`），5 个 view 里 5 份重复的 relative-time 实现全部砍掉，从此 `5h ago` 在所有页面口径完全一致。
  - `document.title` 自动同步：`router.afterEach` 把 `route.meta.title` 拼成 `<Page> · imrockey`，刷新 / 切 tab / 分享标签都对得上；登录 / 注册 / 404 也走同一管线。
  - Dashboard 「Get started」改写：去掉历史里 R3 / R4 的「Coming in」话术，改成基于真实账户状态的 4 步引导（API key 已配？项目 > 0？对话 > 0？packs > 0？），每步动态变绿色完成态并附深链。
  - 首屏 boot spinner：`index.html` 加 `#app:empty::before` 内联 CSS spinner + meta description / theme-color，避免 router 还没 ready 时整页空白。
  - 体感：`npm run build` 生成 dist 同时减少了重复代码体积。
- **后端**
  - **生产配置 guard**：`ProductionConfig.assert_safe_for_production()` 启动时检查 `SECRET_KEY` / `JWT_SECRET_KEY` / `ENCRYPTION_KEY`，任何一个还是 dev 默认或未设置就 `RuntimeError` 拒绝起服，杜绝裸默认 secrets 上线。
  - **统一 JSON 错误**：所有 400 / 401 / 403 / 404 / 405 / 422 + 通用 `HTTPException` + 兜底 `Exception` 全部 JSON `{error, message}` 输出；500 走 `app.logger.exception(...)` 留 stacktrace 在服务端，**永不**把 traceback 漏给客户端。
  - **OpenRouter UA 统一**：`_user_agent()` 从 `APP_VERSION` 取，`/key` 探活和 `/chat/completions` 共用 `imrockey/<version>`，方便 OpenRouter 端归因 + grep 日志。
  - **部署就绪**：`app.py` 头注释加生产指引（`gunicorn -w 4 -b 0.0.0.0:5001 'app:app'`）；`requirements.txt` 末尾给出可选 `gunicorn==23.0.0`（注释形式，dev 不强依赖）；日志器在 `_configure_logging()` 里被显式装好（INFO in prod / DEBUG in dev）。
  - 验证：`scripts/smoke_context_packs.py` 全 11 条断言仍通过；`FLASK_ENV=production` 启动会按预期 `RuntimeError`。

### R11 速览

- **后端**
  - 新表 `context_packs`：`title / body / model / instructions / source_memory_ids (JSON) / memory_count / 三种 token 计数 + 时间戳`，user/project 双 FK，`db.create_all()` 启动时自动建表。
  - `context_pack_service.generate(user, project_id, *, title?, instructions?, memory_ids?, model?)` 拉项目 memories（默认全部，可指定子集），按 `decisions / todos / facts / questions` 分组喂进 system prompt，要求模型输出**纯 Markdown**（含 H1 标题 + 一段总结 + 5 个 H2 区块 + 给下次会话的 orientation），自动 strip 代码围栏后落库；零 memory 时抛 `no_memories`。
  - 路由：`GET /api/projects/<pid>/context-packs`、`POST /api/projects/<pid>/context-packs/generate`、`GET /api/context-packs?limit=N`（跨项目 recent，默认 20、上限 100）、`GET/PATCH/DELETE /api/context-packs/<id>`，所有路由 user 隔离硬走 404。
  - 烟雾测试 `backend/scripts/smoke_context_packs.py` 用 in-memory SQLite + monkeypatch OpenRouter 覆盖 generate/选定子集/no_memories/跨用户 404/list/count/update/校验/`source_memory_ids` 反射等 11 条断言。
- **前端**
  - 项目详情页 Context Packs 区接通真实数据：顶部 `Generate Context Pack` 按钮展开内联表单（可选 title + instructions），调用接口后新 pack 进入列表顶并直接跳到详情页；列表项展示标题 + 240 字预览 + 模型 + memory 数 + 相对时间 + 行内 `Copy` 一键复制 body。
  - 新页 `/projects/:id/context-packs/:packId`：完整 Markdown 等宽渲染 + 元信息（项目 / 模型 / memory 数 / token / 时间 / 自定义 instructions）+ 顶部 `Copy pack` 一键复制全文 / `Edit` 内联改 body / `Rename` 改标题 / `Delete` 删除（带二次确认）。
  - 顶级 `/context-packs` 页改造为跨项目最近 packs 列表，每行点项目 chip 进 packs 详情；Dashboard 第三张计数卡显示 Context Packs 总数，同时在 Recent conversations 之后增加 Recent Context Packs 区，与最近对话保持同款卡片样式。

### R10 速览

- **后端**：`GET /api/search?q=<term>&type=...&limit=...`，三类 SQLite LIKE 查询统一加 `func.lower(...)` 实现大小写不敏感，并对 `%` `_` `\` 做了转义，避免用户输入变成通配符。每条命中带 `snippet`（首次命中位置前后 80 字、过长时加 `…`） + `match_field`，user 隔离硬编码在所有 SELECT 上。
- **前端**：`/search` 页接通真实数据 — 输入框带 300ms debounce，URL 带 `?q=` / `?type=`（刷新可保持）；4 个圆角 tab（All / Messages / Memories / Conversations）带各自命中数；命中关键词在 snippet 与标题里用 `<mark>` 黄色高亮；消息结果点击直达 `/projects/<pid>/chat/<cid>#msg-<id>`，聊天页会自动 scrollIntoView 并对该气泡 flash 高亮 1.6s。

### R9 速览

- **后端**
  - 新增 `Memory` 表（kind / content / source_excerpt + user/project/conversation 三层 FK）。
  - `Conversation` 增加 `summary` + `summarized_at`（启动时通过轻量 migration 自动给老库追列）。
  - `memory_service.summarize_conversation` 把整段对话喂给 OpenRouter，要求只输出 JSON；解析容忍 markdown 围栏 / 前后多余文本。
  - 路由：`POST /api/conversations/<cid>/summarize`、`GET /api/conversations/<cid>/memories`、`GET /api/projects/<pid>/memories`、`DELETE /api/memories/<mid>`，全部走 user 隔离。
- **前端**
  - 聊天页头部加「Wrap up」按钮：≥2 条 user/assistant 消息后可点；运行中显示 spinner，完成后摘要 + memories 折叠面板出现在 MessageList 上方；二次点击文案变「Re-wrap up」。
  - 聊天侧栏的对话条目和项目详情页的 Conversations 列表，会显示 `Summarized` 徽章。
  - 项目详情页 Memories 区按 `Decisions / Todos / Facts / Open questions` 分组展示，每条可链接回原对话并支持单条删除。
