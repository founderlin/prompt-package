# Prompt Package frontend

Vue 3 + Vite 前端，通过 REST API 调用 Flask 后端。

## 启动

```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```

默认运行在 `http://127.0.0.1:5173`，会调用 `VITE_API_BASE_URL`（默认 `http://127.0.0.1:5001`）下的后端。

## 目录结构

```
frontend/
├── index.html
├── package.json
├── vite.config.js
├── .env.example
└── src/
    ├── main.js
    ├── App.vue                       # 顶层 router-view
    ├── router/
    │   └── index.js                  # 嵌套布局路由 + auth guard
    ├── api/
    │   ├── client.js                 # axios 实例 + token 注入 + 401 拦截
    │   ├── health.js                 # /api/health
    │   ├── auth.js                   # /api/auth/*
    │   ├── settings.js               # /api/settings/*
    │   ├── projects.js               # /api/projects/*
    │   ├── chat.js                   # /api/conversations + /api/projects/<pid>/conversations + /api/conversations/*（含 summarize）
    │   ├── memories.js               # /api/projects/<pid>/memories + /api/conversations/<cid>/memories + /api/memories/<mid>
    │   ├── search.js                 # /api/search（R10）
    │   └── contextPacks.js           # /api/projects/<pid>/context-packs[/generate] + /api/context-packs/* （R11）
    ├── constants/
    │   └── models.js                 # OpenRouter 精选模型 + DEFAULT_MODEL_ID + modelLabel()
    ├── stores/
    │   └── auth.js                   # 用户状态 + login/register/logout/refresh
    ├── utils/
    │   ├── errors.js                 # API 错误转友好文案
    │   └── highlight.js              # highlightSegments(text, query) → 带 match 标记的片段数组
    ├── layouts/
    │   ├── AppShell.vue              # Sidebar + Header + 主内容区
    │   └── AuthLayout.vue            # 登录/注册页用的 slot 布局
    ├── components/
    │   ├── layout/
    │   │   ├── SidebarNav.vue        # 左侧导航
    │   │   └── AppHeader.vue         # 顶部栏 + 用户菜单
    │   ├── common/
    │   │   ├── PageHeader.vue        # 页面级标题 + 操作槽
    │   │   └── EmptyState.vue        # 空状态卡片
    │   ├── projects/
    │   │   └── ProjectFormDialog.vue # 新建 / 编辑项目对话框
    │   └── chat/
    │       ├── MessageBubble.vue     # 单条消息气泡（user 右 / assistant 左）
    │       ├── MessageList.vue       # 自滚动消息流 + "Model is thinking…"
    │       └── ChatComposer.vue      # 多行输入框 + Enter 发送 / Shift+Enter 换行
    ├── views/
    │   ├── auth/
    │   │   ├── LoginView.vue         # /login
    │   │   └── RegisterView.vue      # /register
    │   ├── DashboardView.vue         # 三张计数卡（projects / conversations / context packs） + Recent conversations + Recent context packs
    │   ├── ProjectsView.vue          # 列表 / 创建 / 编辑 / 删除
    │   ├── ProjectDetailView.vue     # 项目详情 + Conversations + Memories + Context Packs（生成表单 + 列表 + 行内复制）
    │   ├── ProjectChatView.vue       # /projects/:id/chat[/:cid] 聊天页（含 Wrap up + summary 折叠面板 + #msg-<id> 锚点高亮）
    │   ├── ContextPackView.vue       # /projects/:id/context-packs/:packId 单条详情（Markdown 渲染 + 复制 / 重命名 / 编辑 body / 删除）
    │   ├── SearchView.vue            # /search 跨项目搜索（debounce + 分段 tabs + 高亮 + 直达原对话）
    │   ├── ContextPacksView.vue      # /context-packs 跨项目最近 packs 列表
    │   ├── SettingsView.vue          # Account + OpenRouter API key 卡片
    │   ├── PrivacyView.vue
    │   └── NotFoundView.vue
    └── styles/
        └── base.css                  # 全局 token + 通用组件类
```

## 路由

| Path             | 公开/受保护 | 说明 |
| ---------------- | ----------- | ---- |
| `/login`         | 公开        | 登录页（已登录访问会被重定向到 `/dashboard`） |
| `/register`      | 公开        | 注册页（已登录访问会被重定向到 `/dashboard`） |
| `/dashboard`     | 受保护      | 默认首页 |
| `/projects`      | 受保护      | 项目列表 + 新建 / 编辑 / 删除 |
| `/projects/:id`  | 受保护      | 项目详情 + Conversations 列表 + Memories（按 kind 分组）+ Context Packs（生成表单 + 列表 + 复制） |
| `/projects/:id/chat`           | 受保护 | 进入聊天会先自动建一个空对话，并 replace 路由到 `/projects/:id/chat/:cid` |
| `/projects/:id/chat/:cid`      | 受保护 | 指定对话；不存在 / 不属于当前用户 → "Conversation not found" |
| `/projects/:id/context-packs/:packId` | 受保护 | 单个 Context Pack 详情：Markdown 渲染 + 一键复制 + 改 title / 改 body / 删除 |
| `/search`        | 受保护      | 跨项目搜索 messages / memories / conversations，URL 带 `?q=` / `?type=` 可分享刷新 |
| `/context-packs` | 受保护      | 跨项目最近 packs 列表（每行带项目 chip + 240 字预览 + 行内复制） |
| `/settings`      | 受保护      | Account 卡 + OpenRouter API key 卡（保存 / 删除 / 测试连接） |
| `/privacy`       | 公开        | 隐私说明 |
| `*`              | 公开        | 404 |

## 认证

- Token 存在 `localStorage` 的 `promptpackage_token` 键。
- axios 请求拦截器自动把 `Authorization: Bearer <token>` 加到每个请求。
- 收到 401 时自动清掉本地 token，并把 store 里的用户置空。
- `router.beforeEach` 在导航前会调用一次 `/api/auth/me` 复活会话；token 失效会被自动重定向到 `/login?redirect=…`。

## OpenRouter API key（Settings 页）

- 仅在用户点击 **Save key** 或 **Test connection** 时把明文 key 通过 HTTPS 发到后端，由后端再去 OpenRouter `/key` 验证。
- 前端代码不会把 key 写进 `console.*` 或 `localStorage`；axios 默认也不打印请求体。保存成功后会立刻清空输入框并切到 masked 显示。
- 失败时按后端返回的 `error` code（`invalid_api_key`、`openrouter_unreachable`、`openrouter_timeout` 等）转成对应的友好文案。

## 注意

- 前端不要直接调用 OpenRouter，所有 LLM 调用都走后端。
- API base URL 由 `VITE_API_BASE_URL` 控制，方便切换本地 / 远端环境。
