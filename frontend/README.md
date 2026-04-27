# imrockey frontend

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

- Token 存在 `localStorage` 的 `imrockey_token` 键。
- axios 请求拦截器自动把 `Authorization: Bearer <token>` 加到每个请求。
- 收到 401 时自动清掉本地 token，并把 store 里的用户置空。
- `router.beforeEach` 在导航前会调用一次 `/api/auth/me` 复活会话；token 失效会被自动重定向到 `/login?redirect=…`。

## 项目内 Chat（R7）

- 入口：项目详情页的 **Start chat** 按钮 / 顶部 Conversations 区的 **New chat**。
- 进入路径不带 `:cid` 时，前端会立即调 `POST /api/projects/:id/conversations` 建一个空对话，再 `replace` 到带 `:cid` 的路径，刷新页面也能稳定回到同一对话。
- 顶部模型选择器：内置 6 个常用 OpenRouter 模型，第 7 项 *Custom…* 允许粘贴任意 `provider/model` slug。每条 user 消息都会把当前选中的模型一起发后端，后端用它实际调用 OpenRouter 并把模型名持久化到 `messages.model` / `conversations.model`。
- 发送流程：前端先 optimistic 把 user 气泡展示出来 → 调 `POST /api/conversations/:cid/messages` → 成功用响应里的 `user_message + assistant_message` 替换；失败时再调 `GET /messages` 把后端真实状态拉回来（user 消息其实已经持久化）。
- 没配 API key 时输入框直接 disable，并显示去 `/settings` 的指引；配好后回到聊天页才可发送。

## 对话列表（R8）

- **Dashboard `Recent conversations`** 调 `GET /api/conversations?limit=5`，跨项目按最近活动倒序展示，每行点击直达 `/projects/<pid>/chat/<cid>`；指标卡 `Conversations` 用同一接口的 `total`。
- **项目详情页 Conversations**：调 `GET /api/projects/<pid>/conversations`，每行显示 `模型 · N msgs · 5h ago`，已 wrap 的对话尾部带 `Summarized` 徽章。
- **聊天页左侧对话侧栏**：列出本项目所有对话，当前对话高亮，点击即切换；顶部 **New** 按钮一键新建并跳转；删除当前对话后会自动跳到剩下最近的一条，没有时回到项目详情。每次成功发完消息会刷新侧栏的 `last_message_at` / `message_count`，已 wrap 的对话也会带徽章。

## 摘要与记忆（R9）

- **聊天页 Wrap up**：当本对话至少有 1 轮 user/assistant 交互后，头部 **Wrap up** 按钮可点。点击会调 `POST /api/conversations/:cid/summarize`，运行中按钮内自带 spinner，期间不能再发消息或删对话。
- 后端拿到响应后，前端会：(1) 在 MessageList 上方插一张 **Summary** 折叠卡，先展示一句话总结 + `Show N memories` 切换；(2) 把 memories 按 `Decisions / Todos / Facts / Open questions` 分组渲染，每条带可选 `source_excerpt` 引用；(3) 给当前对话和侧栏条目打上 `Summarized` 徽章；(4) 按钮文案改为 **Re-wrap up**。再次点击会让后端覆盖式替换该对话已有的 memories。
- **项目详情页 Memories**：进入页面就会调 `GET /api/projects/:id/memories`，按 kind 分组渲染，每条可点 `From: <对话标题>` 跳回原对话，右侧 `×` 调 `DELETE /api/memories/:mid` 单条删除。`Refresh` 按钮可手动重拉。
- 删除项目 / 对话时数据库 `ON DELETE CASCADE` 会顺手清掉 memories；前端只需在 UI 层面同步移除。

## Context Packs（R11）

- **生成入口**：项目详情页 Context Packs 区右上角 `Generate Context Pack` 按钮。点开内联表单可填 title（可选）/ instructions（可选，用来加额外约束，如 "focus on backend decisions"），点 `Generate` 调 `POST /api/projects/<pid>/context-packs/generate`，返回的新 pack 会瞬间出现在列表顶并自动跳转到详情页。零 memories 时按钮 disable，并提示先 wrap 一次对话。
- **列表行**：标题 + 240 字 body 预览（多行省略） + 模型 + memory 数 + 相对时间 + 行内 `Copy` 按钮（直接复制 body 到剪贴板，1.8s 内显示 Copied）。点击其它区域进入详情页。
- **详情页 `/projects/:id/context-packs/:packId`**：
  - 顶部卡：可点 `Rename` 内联改 title；元信息一栏（项目链接 / 模型 / memory 数 / total tokens / 创建时间），如果生成时填了 instructions 也会回显。
  - 顶部按钮：`Copy pack`（带图标 + 复制反馈）/ `Edit`（把 body 装进 textarea，`Save changes` 走 `PATCH /api/context-packs/<id>` 持久化）/ `Delete`（二次确认后 `DELETE /api/context-packs/<id>` 并跳回项目详情）。
  - 主体：Markdown 等宽 `<pre>` 渲染，`max-height: 640px` 内滚动；不引入 markdown 渲染器，所见即可粘。
- **顶级 `/context-packs`**：跨项目最近 30 条 packs，每行带项目 chip + 行内 `Copy`，点击进入对应详情页。
- **Dashboard**：第三张计数卡显示 Context Packs 总数；下方新增 `Recent Context Packs` 区，与 Recent conversations 同款卡片样式，最多 5 条。
- **错误处理**：所有 `Could not …` 文案统一走 `describeApiError`，与其它模块共享同一份错误样式。

## 搜索（R10）

- 入口：左侧导航 **Search**，路由 `/search`。
- 输入框 300ms debounce 自动跑搜索，回车立即跑；URL 同步 `?q=` / `?type=`，刷新或分享链接都能复现同一查询。
- 顶部 4 个分段：**All / Messages / Memories / Conversations**，每个分段后面带本次结果的命中数。**All** 会顺序展示 messages → memories → conversations 三段（每段最多各 50 条），单独的分段只看那一类。
- 每张结果卡：顶部 chip + 项目/对话面包屑，下面是 `snippet`（关键词 `<mark>` 高亮）和 meta（模型 / 时间 / 已 wrap 徽章）。整张卡是一个 RouterLink：
  - **Message** → `/projects/<pid>/chat/<cid>#msg-<id>`（聊天页自动 scrollIntoView 并对气泡 flash 高亮）
  - **Memory** → 有原对话则跳到那条对话，否则回到项目详情
  - **Conversation** → 跳到对话最新视图
- 服务端只返回当前用户自己的数据（其他用户的内容**永远**搜不到）；输入里的 `%` `_` `\` 不会被当作通配符。

## OpenRouter API key（Settings 页）

- 仅在用户点击 **Save key** 或 **Test connection** 时把明文 key 通过 HTTPS 发到后端，由后端再去 OpenRouter `/key` 验证。
- 前端代码不会把 key 写进 `console.*` 或 `localStorage`；axios 默认也不打印请求体。保存成功后会立刻清空输入框并切到 masked 显示。
- 失败时按后端返回的 `error` code（`invalid_api_key`、`openrouter_unreachable`、`openrouter_timeout` 等）转成对应的友好文案。

## 注意

- 前端不要直接调用 OpenRouter，所有 LLM 调用都走后端。
- API base URL 由 `VITE_API_BASE_URL` 控制，方便切换本地 / 远端环境。
