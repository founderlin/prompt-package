# imrockey backend

Flask 后端，REST API 入口为 `/api/*`。

## R15 — Google Sign-In（GIS id_token）

让用户用 Google 账号一键登录，跟现有「邮箱 + 密码」流程并存：

- 数据模型：`users` 表新增 `google_sub`（UNIQUE）/ `google_email` / `auth_provider` 三列。`google_sub` 是 Google 给的 stable account id；老用户的密码完全保留。Google-only 用户的 `password_hash` 写入哨兵值 `!google-oauth-only!`，`check_password` 永远返回 False。
- 依赖：`google-auth==2.35.0`，只用 `id_token.verify_oauth2_token` 在服务端校验 JWT 签名 + `aud` + `iss` + `exp`。
- 配置：`GOOGLE_CLIENT_ID` 取自 [Google Cloud Console](https://console.cloud.google.com/apis/credentials) Web 应用 OAuth Client，前后端用同一个；未配置时整个特性自动 disable（`/api/auth/google` → 503，前端按钮不渲染）。
- 路由：
  - `POST /api/auth/google` 接 `{id_token}` 或 `{credential}` 别名（GIS 默认字段名）；按 `sub` → 已验证 email → 创建新用户 三级回退落用户，发 imrockey 自己的 JWT。
  - `GET /api/auth/google/config` 让前端拿 `enabled` flag。
- 安全：`email_verified=False` 时永远不会自动把这个 Google 账号 link 进老的 password 账户，避免别人借未验证邮箱劫持。
- 复登幂等：第二次同 `sub` 命中只刷 `google_email`，不 dup user。

烟雾测试：

```bash
.venv/bin/python scripts/smoke_google_login.py
```

8 条断言覆盖：未配 client id 时 503 / 无效 id_token 401 / 缺 id_token 400 / 首登创建 passwordless 用户 / 同 sub 复登幂等 / verified-email 安全 link 不丢密码 / unverified-email 不 auto-link / `/google/config` 状态。

## R14 — Multi-provider 支持（OpenRouter / DeepSeek / OpenAI）

每个用户可以同时挂多家 provider key，聊天 / 摘要 / Context Pack 都按 provider 路由到对应 endpoint：

- 数据模型：新表 `provider_credentials(user_id, provider, encrypted_api_key, label, last_verified_at, …)`，`(user_id, provider)` 唯一；`conversations.provider` / `messages.provider` 记录每条 assistant turn 实际走的 gateway。
- 配置：`app/providers.py` 静态登记三家 provider（base URL / verify endpoint / 推荐 summary 模型 / extra headers / docs URL），env 可覆盖 `OPENROUTER_BASE_URL` / `DEEPSEEK_BASE_URL` / `OPENAI_BASE_URL` / `LLM_VERIFY_TIMEOUT_SECONDS`。
- 通用 LLM 客户端：`app/services/llm_service.py` 暴露 `verify_api_key(api_key, provider=)` / `chat_completion(api_key, messages, *, provider=, model=, …)`，把 OpenRouter `/key` 与 DeepSeek/OpenAI `/models` 探活统一封装。
- 凭据服务：`app/services/credentials_service.py` 接管多 provider key 的 save / delete / test / status / `first_configured_provider`；老 `openrouter_service.py` / `settings_service.py` 都降级为薄 shim，老 `/api/settings/openrouter-key` 路由仍可用。
- chat / memory / context_pack 三条业务链都接收 / 透传 `provider`，并把它写回数据库；老对话 NULL 视为 `openrouter`。
- 自动迁移：启动时 `_apply_lightweight_migrations` 自动建表 + 加列 + 把老的 `users.openrouter_api_key_encrypted` 复制进 `provider_credentials`，无需手工脚本。

烟雾测试：

```bash
.venv/bin/python scripts/smoke_multi_provider.py
```

7 条断言覆盖：多家 key 独立保存 / 老 OpenRouter shim 兼容 / `User.to_dict().providers` 状态正确 / `send_user_message` 按 provider 命中对应 client / 不支持的 provider 立即 422 / 删某家 key 不影响其他家 / `first_configured_provider` 选优先级。

## R13 — Context Pack as Prompt Plus

每个 conversation 现在可以挂一个 Context Pack 作为「软 system prompt」：

- 数据模型：`conversations.context_pack_id`（INTEGER NULL，逻辑 FK 到 `context_packs.id`）。
- 服务：`chat_service.set_context_pack(user, conversation_id, pack_id | None)`。
- 路由：
  - `POST /api/projects/<pid>/conversations` 接受 `{model, context_pack_id}`。
  - `PATCH /api/conversations/<cid>` 接受 `{context_pack_id: <id|null>}` 用于挂载 / 切换 / 卸下。
- 调 OpenRouter 时，`_build_message_payload` 在 history 前面插一条 `role=system` 消息，
  内容 = `CONTEXT_PACK_PREAMBLE`（定位语）+ pack body。**不**写入 `messages` 表，
  所以切换 / 删除 pack 不会篡改历史。

烟雾测试：

```bash
python scripts/smoke_prompt_plus.py
```

8 条断言覆盖：创建即挂载、跨用户拒绝（404）、跨项目挂载、卸下、替换、系统消息注入、卸下后无注入、被删 pack 不破坏对话。

## 启动

### 开发

```bash
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
python app.py
```

默认监听 `http://127.0.0.1:5001`。

### 生产（gunicorn）

```bash
pip install gunicorn==23.0.0      # 见 requirements.txt 末尾的可选段

# 三把密钥必须是真实强随机值（任意一项是 dev 默认会 RuntimeError 拒绝起服）
export FLASK_ENV=production
export SECRET_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(48))")
export JWT_SECRET_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(48))")
export ENCRYPTION_KEY=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
export CORS_ORIGINS="https://your-frontend.example.com"

gunicorn -w 4 -b 0.0.0.0:5001 'app:app'
```

`app.py` 模块顶端已经把 `app = create_app()` 暴露成 WSGI callable，任何 WSGI server（gunicorn / uwsgi / waitress）都可以直接 `app:app` 接入。

## 接口（当前轮）

| Method | Path                                  | 鉴权   | 说明 |
| ------ | ------------------------------------- | ------ | ---- |
| GET    | `/api/health`                         | -      | 健康检查 |
| POST   | `/api/auth/register`                  | -      | 注册，body `{email, password}`，返回 `{token, user}` |
| POST   | `/api/auth/login`                     | -      | 登录，body `{email, password}`，返回 `{token, user}` |
| POST   | `/api/auth/google`                    | -      | （R15）body `{id_token}` 或 `{credential}`；后端验证 GIS id_token，按 sub / verified-email 找/建用户，返 `{token, user}` |
| GET    | `/api/auth/google/config`             | -      | （R15）告诉前端 `GOOGLE_CLIENT_ID` 是否已配置 |
| POST   | `/api/auth/logout`                    | Bearer | 服务端无状态，仅作为「显式退出」语义 |
| GET    | `/api/auth/me`                        | Bearer | 返回当前登录用户 |
| GET    | `/api/settings/providers`             | Bearer | 列出三家 provider 状态（含 `configured` / `masked` / docs URL / 最近 verify 元数据）（R14） |
| GET    | `/api/settings/providers/<provider>/key` | Bearer | 单家 provider 当前 key 状态（R14） |
| PUT    | `/api/settings/providers/<provider>/key` | Bearer | body `{api_key, skip_verify?}`，默认会先打对应 provider 验证再加密保存（R14） |
| DELETE | `/api/settings/providers/<provider>/key` | Bearer | 清除某家 provider 的 key（R14） |
| POST   | `/api/settings/providers/<provider>/test` | Bearer | body `{api_key?}`；返回该 provider 的探活元数据（R14） |
| GET    | `/api/settings/openrouter-key`        | Bearer | （兼容 alias）当前 OpenRouter key 状态 |
| PUT    | `/api/settings/openrouter-key`        | Bearer | （兼容 alias）保存 OpenRouter key |
| DELETE | `/api/settings/openrouter-key`        | Bearer | （兼容 alias）清除 OpenRouter key |
| POST   | `/api/settings/openrouter-key/test`   | Bearer | （兼容 alias）OpenRouter key 探活 |
| GET    | `/api/projects`                       | Bearer | 列出当前用户的项目，按 `updated_at` 倒序，含 `total` |
| POST   | `/api/projects`                       | Bearer | body `{name, description?}` 创建项目 |
| GET    | `/api/projects/<id>`                  | Bearer | 项目详情；不属于当前用户 → 404 |
| PATCH  | `/api/projects/<id>`                  | Bearer | 部分更新（只更新出现在 body 中的字段） |
| DELETE | `/api/projects/<id>`                  | Bearer | 删除项目 |
| GET    | `/api/projects/<pid>/conversations`   | Bearer | 列出当前用户在该项目下的对话，按最近活动倒序，每条带 `message_count` |
| POST   | `/api/projects/<pid>/conversations`   | Bearer | body `{model?, provider?, context_pack_id?}` 创建一个空对话；不传 `provider` 默认 `openrouter`（R13/R14） |
| GET    | `/api/conversations`                  | Bearer | **跨项目**列出当前用户的对话，`?limit=N`（默认 20，上限 100），每条带 `message_count` 与 `project: {id, name}`，附带 `total` 用于 Dashboard 计数 |
| GET    | `/api/conversations/<cid>`            | Bearer | 拿对话 + 全量 messages；不属于当前用户 → 404 |
| DELETE | `/api/conversations/<cid>`            | Bearer | 删除对话（消息级联清理） |
| GET    | `/api/conversations/<cid>/messages`   | Bearer | 拿这个对话的全部消息 |
| POST   | `/api/conversations/<cid>/messages`   | Bearer | body `{content, model?, provider?}`；按 provider 拿对应 key + endpoint，持久化 user / assistant 消息（含 provider 列），返回三元组（R14） |
| PATCH  | `/api/conversations/<cid>`            | Bearer | body 可含 `context_pack_id: <id|null>`，挂载 / 切换 / 卸下 Prompt+ pack（R13） |
| POST   | `/api/conversations/<cid>/summarize`  | Bearer | body `{model?}`；用整段 transcript 让模型产出 JSON `{summary, memories[]}`，落库覆盖该对话已有的 memories；返回更新后的 `{conversation, memories[]}`（R9） |
| GET    | `/api/conversations/<cid>/memories`   | Bearer | 列出当前对话提取出的 memories（R9） |
| GET    | `/api/projects/<pid>/memories`        | Bearer | 列出项目内全部 memories（R9），每条带 `conversation: {id, title}` |
| DELETE | `/api/memories/<mid>`                 | Bearer | 删除单条 memory（R9） |
| GET    | `/api/search`                         | Bearer | 跨项目搜索；`?q=<term>&type=messages|memories|conversations|all（可重复）&limit=<1..50>`；返回三个并行的结果桶，每条带 `snippet` + `match_field`，全部按 user 隔离（R10） |
| GET    | `/api/projects/<pid>/context-packs`   | Bearer | 列出项目内 Context Packs（不含 body，附 240 字 `body_preview`）（R11） |
| POST   | `/api/projects/<pid>/context-packs/generate` | Bearer | body `{title?, instructions?, memory_ids?[], model?}`；按项目 memories 调 OpenRouter 产 Markdown，落库新 pack；零 memory → `no_memories`（R11） |
| GET    | `/api/context-packs?limit=N`          | Bearer | **跨项目**最近 packs，默认 20 / 上限 100；返回 `total` 用于 Dashboard（R11） |
| GET    | `/api/context-packs/<id>`             | Bearer | 单个 pack 完整 body + 元信息 + `project: {id, name}` |
| PATCH  | `/api/context-packs/<id>`             | Bearer | body 可含 `title?` / `body?`；空 title → 422 |
| DELETE | `/api/context-packs/<id>`             | Bearer | 删除单个 pack |

鉴权方式：把登录返回的 token 作为 `Authorization: Bearer <token>` 头带到所有受保护接口。

## 安全：Provider API key 存储（R14）

- 三家 provider（OpenRouter / DeepSeek / OpenAI）共用同一套加密策略：入库前 Fernet 对称加密（`cryptography` 库），密钥从 `ENCRYPTION_KEY` 读取，未配置时从 `SECRET_KEY` 派生（仅 dev 便利，prod 必须显式配置）。
- 每条记录落在 `provider_credentials` 表，`(user_id, provider)` 唯一；老 `users.openrouter_api_key_encrypted` 数据会在启动时被自动迁移到新表，老路径 `/api/settings/openrouter-key/*` 仍可用。
- 接口任何返回都只回传 masked 字符串（如 `sk-or-v1••••••7890`），明文 key 永远不离开服务端。
- 保存路径默认会先调对应 provider 探活（OpenRouter `/key`、DeepSeek/OpenAI `/models`），无效会立刻 401，不会落库。

## 目录结构

```
backend/
├── app.py                      # 启动入口
├── config.py                   # 配置加载（读取 .env）
├── requirements.txt
├── .env.example
├── instance/
│   └── imrockey.sqlite3        # SQLite 数据库（gitignored）
└── app/
    ├── __init__.py             # create_app() + db.create_all()
    ├── extensions.py           # SQLAlchemy 实例
    ├── models/
    │   ├── __init__.py
    │   ├── user.py                  # User 模型（含 to_dict().providers 状态映射）
    │   ├── project.py               # Project 模型
    │   ├── conversation.py          # Conversation（含 summary / context_pack_id / provider）+ Message（含 provider）
    │   ├── memory.py                # Memory 模型 + KINDS 枚举（R9）
    │   ├── context_pack.py          # ContextPack 模型 + source_memory_ids JSON 序列化（R11）
    │   └── provider_credential.py   # 多 provider 加密 key 存储（R14）
    ├── providers.py                  # R14：三家 provider 静态配置 + env 覆盖
    ├── services/
    │   ├── auth_service.py          # 注册 / 登录业务逻辑
    │   ├── llm_service.py            # R14 通用 LLM 客户端：verify_api_key / chat_completion (provider= ...)
    │   ├── openrouter_service.py    # 兼容 shim → 转给 llm_service(provider='openrouter')
    │   ├── credentials_service.py    # R14 多 provider key 管理：save / delete / test / status
    │   ├── settings_service.py      # 兼容 shim → 转给 credentials_service(provider='openrouter')
    │   ├── project_service.py       # Project CRUD + 用户隔离
    │   ├── chat_service.py          # 对话 + 消息：按 provider 路由 endpoint，写回 conversation/message.provider
    │   ├── memory_service.py        # R9 wrap-up：按对话 provider / first_configured_provider 选 key + summary 模型
    │   ├── search_service.py        # R10 跨项目搜索：三类 LIKE 查询 + 转义 + snippet
    │   └── context_pack_service.py  # R11 Context Pack：分组 prompt + Markdown 输出 + CRUD（R14 多 provider）
    ├── utils/
    │   ├── auth.py                  # JWT 编解码 + login_required 装饰器
    │   └── crypto.py                # Fernet 加解密包装
    ├── scripts/
    │   ├── smoke_context_packs.py   # R11 烟雾测试：mock OpenRouter，覆盖 generate / 隔离 / 校验
    │   ├── smoke_prompt_plus.py     # R13 烟雾测试：Context Pack 作为 Prompt+
    │   ├── smoke_multi_provider.py  # R14 烟雾测试：多 provider 路径 + 老 key 兼容
    │   └── smoke_google_login.py    # R15 烟雾测试：Google 一键登录全分支
    └── routes/
        ├── __init__.py              # 蓝图注册
        ├── health.py                # /api/health
        ├── auth.py                  # /api/auth/*
        ├── settings.py              # /api/settings/*
        ├── projects.py              # /api/projects/* (含 conversations / memories / context-packs 子路由)
        ├── conversations.py         # /api/conversations/*（含 summarize + memories）
        ├── memories.py              # /api/memories/*（单条 memory 操作）
        ├── search.py                # /api/search（R10）
        └── context_packs.py         # /api/context-packs/*（R11 跨项目 list + 单条 CRUD）
```

## 数据库

- MVP 使用 SQLite，文件位于 `backend/instance/imrockey.sqlite3`，被 `.gitignore` 忽略。
- 启动时调用 `db.create_all()` 自动建表，`_apply_lightweight_migrations()` 会按需给已有表追加列（SQLite 友好）；老 DB 文件无需手动迁移。R9 给 `conversations` 加 `summary` / `summarized_at`；R13 加 `context_pack_id`；R14 加 `conversations.provider` / `messages.provider`，并把老 `users.openrouter_api_key_encrypted` 数据复制进新表 `provider_credentials`。
- 当前表：
  - `users`（id / email / password_hash / openrouter_api_key_encrypted（legacy，仍可读）/ **google_sub?** / **google_email?** / **auth_provider?** / created_at / updated_at；R15）
  - `provider_credentials`（id / user_id → users.id / provider ∈ {openrouter, deepseek, openai} / encrypted_api_key / label? / 计费元数据 / last_verified_at / created_at / updated_at；`(user_id, provider)` 唯一；删除用户级联清理）
  - `projects`（id / user_id → users.id / name / description / created_at / updated_at；删除用户级联清理）
  - `conversations`（id / user_id / project_id → projects.id / title / model / **provider** / **context_pack_id?** / last_message_at / **summary / summarized_at** / created_at / updated_at；删除项目级联清理）
  - `messages`（id / conversation_id → conversations.id / role / content / model / **provider** / prompt_tokens / completion_tokens / total_tokens / created_at；删除对话级联清理）
  - `memories`（id / user_id / project_id / conversation_id?（可空） / kind ∈ {fact, decision, todo, question} / content / source_excerpt? / created_at / updated_at；随用户 / 项目 / 对话级联清理）
  - `context_packs`（id / user_id / project_id / title / body / model? / instructions? / source_memory_ids（JSON 字符串） / memory_count / prompt/completion/total_tokens / created_at / updated_at；随用户 / 项目级联清理）
- 后续轮加表时只需把 model 文件放进 `app/models/`，并在 `app/models/__init__.py` 导出即可被 `create_all()` 拾取。给已有表加列时，把 ALTER 语句加进 `_apply_lightweight_migrations()`。

## 烟雾测试

R9 起的纯逻辑烟雾脚本放在 `scripts/`，使用 in-memory SQLite + `unittest.mock` 屏蔽 OpenRouter / DeepSeek / OpenAI HTTP 调用，可在 venv 内独立运行：

```bash
.venv/bin/python scripts/smoke_context_packs.py    # R11
.venv/bin/python scripts/smoke_prompt_plus.py      # R13
.venv/bin/python scripts/smoke_multi_provider.py   # R14
.venv/bin/python scripts/smoke_google_login.py     # R15
```

每个脚本都会以 `... smoke tests passed.` 结尾。
