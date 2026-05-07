# Prompt Package

<img width="748" height="221" alt="Prompt Package Logo" src="https://github.com/user-attachments/assets/764edff7-1d60-4da2-b6e2-4c04c400ba0f" />

> **[English](#english) | [简体中文](#简体中文) | [Deutsch](#deutsch)**

---

<a name="english"></a>
## English

### Overview
**Prompt Package** is an AI project memory tool designed for individual users of OpenRouter, DeepSeek, and OpenAI. It turns transient AI conversations into a reusable knowledge base. By summarizing chats, creating hand-written notes, and generating "Context Packs," it ensures your next AI session starts exactly where the last one left off.

### Deployment & Availability
- **Live Demo**: Currently deployed on Alibaba Cloud at [http://139.196.44.96](http://139.196.44.96/). 
- **Note on Models**: Models from OpenAI, Google, and Anthropic are not available on the cloud instance. To use these models, you must deploy the project locally and access them through a local VPN.

### What's New
- **Wrap Up**: Summarize individual chats or entire projects into a single Context Pack.
- **Context Zoo**: A central hub to browse, search, and manage all your context assets in a responsive grid.
- **Bla Notes**: Project-scoped lightweight Markdown notes for manual knowledge entry.
- **Chat Context Picker**: Attach project notes directly to your chat messages as background context for the LLM.
- **Enhanced Data Model**: Context Packs now support versioning, structured content, visibility controls, and usage tracking.

### Tech Stack
- **Frontend**: Vue 3 (Composition API), Vite, Vue Router, Axios.
- **Backend**: Flask, Flask-SQLAlchemy (ORM), PyJWT, Fernet (Encrypted keys).
- **Database**: SQLite (MVP/Dev) / PostgreSQL (Prod).
- **Styling**: Custom Material-inspired system with responsive CSS Grid layouts.

### Quick Start
1. **Backend**: `cd backend && python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt && python app.py`
2. **Frontend**: `cd frontend && npm install && npm run dev`
3. **Setup**: Add your API keys in the Settings page.

---

<a name="简体中文"></a>
## 简体中文

### 概览
**Prompt Package** 是一款面向 OpenRouter、DeepSeek 和 OpenAI 个人用户的 AI 项目记忆工具。它将零散的 AI 对话转化为可复用的项目知识库。通过自动摘要、手动记录（Bla Note）以及生成“Context Pack”，它能确保您的下一次 AI 会话能够无缝承接上一次的进度。

### 最新功能
- **Wrap Up（整理）**: 将单个对话或整个项目整理成一个 Context Pack。
- **Context Zoo（上下文仓库）**: 用于浏览、搜索和管理所有 Context Pack 的中心，支持响应式网格布局。
- **Bla Notes（项目笔记）**: 项目级的轻量 Markdown 笔记，用于记录手动输入的知识点。
- **对话引用**: 在聊天框通过“+ Context”选择器直接引用项目笔记作为 LLM 的背景上下文。
- **核心模型升级**: Context Pack 现在支持版本管理、结构化内容、可见性控制和使用频率追踪。

### 技术栈
- **前端**: Vue 3 (Composition API), Vite, Vue Router, Axios。
- **后端**: Flask, Flask-SQLAlchemy (ORM), PyJWT, Fernet (API 密钥加密存储)。
- **数据库**: SQLite (开发/MVP) / PostgreSQL (生产)。
- **样式**: 自研类 Material 风格系统，采用响应式 CSS Grid 布局。

### 快速开始
1. **后端**: `cd backend && python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt && python app.py`
2. **前端**: `cd frontend && npm install && npm run dev`
3. **配置**: 在 Settings 页面添加您的 provider API key。

---

<a name="deutsch"></a>
## Deutsch

### Überblick
**Prompt Package** ist ein KI-Projekt-Gedächtnistool für Einzelnutzer von OpenRouter, DeepSeek und OpenAI. Es verwandelt flüchtige KI-Gespräche in eine wiederverwendbare Wissensdatenbank. Durch Zusammenfassungen, manuelle Notizen (Bla Note) und die Erstellung von „Context Packs“ stellt es sicher, dass Ihre nächste KI-Sitzung genau dort fortgesetzt wird, wo die letzte aufgehört hat.

### Neue Funktionen
- **Wrap Up (Zusammenfassung)**: Fassen Sie einzelne Chats oder ganze Projekte in einem einzigen Context Pack zusammen.
- **Context Zoo**: Ein zentraler Hub zum Durchsuchen, Filtern und Verwalten all Ihrer Kontext-Assets in einem responsiven Raster.
- **Bla Notes**: Projektbezogene, leichtgewichtige Markdown-Notizen für die manuelle Wissenseingabe.
- **Chat Context Picker**: Fügen Sie Projektnotizen direkt an Ihre Chat-Nachrichten als Hintergrundkontext für das LLM an.
- **Erweitertes Datenmodell**: Context Packs unterstützen jetzt Versionierung, strukturierten Inhalt, Sichtbarkeitskontrollen und Nutzungsstatistiken.

### Technologie-Stack
- **Frontend**: Vue 3 (Composition API), Vite, Vue Router, Axios.
- **Backend**: Flask, Flask-SQLAlchemy (ORM), PyJWT, Fernet (verschlüsselte API-Keys).
- **Datenbank**: SQLite (Entwicklung) / PostgreSQL (Produktion).
- **Styling**: Eigenes Material-inspiriertes System mit responsivem CSS-Grid-Layout.

### Schnellstart
1. **Backend**: `cd backend && python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt && python app.py`
2. **Frontend**: `cd frontend && npm install && npm run dev`
3. **Einrichtung**: Fügen Sie Ihre API-Keys auf der Einstellungsseite (Settings) hinzu.
