# novel-forge

![Python](https://img.shields.io/badge/python-3.11-blue.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-0.109.0-green.svg)
![React](https://img.shields.io/badge/react-18.3.1-blue.svg)
![License](https://img.shields.io/badge/license-GPL%20v3-blue.svg)

基于 AI 的智能小说创作助手。

## ✨ 特性

- 🤖 **多 AI 模型** - 支持 OpenAI、Gemini、Claude 等主流模型
- 📝 **智能向导** - AI 自动生成大纲、角色和世界观
- 👥 **角色管理** - 人物关系、组织架构可视化
- 📖 **章节编辑** - 创建、编辑、重新生成和润色
- 🌐 **世界观设定** - 构建完整的故事背景
- 🔐 **多种登录** - OAuth 或本地账户
- 💾 **PostgreSQL** - 生产级数据库，多用户数据隔离
- 🐳 **Docker 部署** - 一键启动，开箱即用

## 🚀 快速开始

### 前置要求

- Docker 和 Docker Compose
- 至少一个 AI 服务的 API Key（OpenAI / Gemini / Claude）

### Docker Compose 部署

```bash
# 1. 配置环境变量
cp backend/.env.example .env
# 编辑 .env 文件，填入必要配置

# 2. 启动服务
docker-compose up -d

# 3. 访问应用
# http://localhost:8000
```

### 本地开发

#### 后端

```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# 编辑 .env

python -m uvicorn app.main:app --host localhost --port 8000 --reload
```

#### 前端

```bash
cd frontend
npm install
npm run dev      # 开发模式
npm run build    # 生产构建
```

## ⚙️ 配置说明

最小可用配置（`.env`）：

```bash
# 数据库
DATABASE_URL=postgresql+asyncpg://novelforge:your_password@postgres:5432/novel_forge
POSTGRES_PASSWORD=your_secure_password

# AI 服务
OPENAI_API_KEY=your_openai_key
OPENAI_BASE_URL=https://api.openai.com/v1
DEFAULT_AI_PROVIDER=openai
DEFAULT_MODEL=gpt-4o-mini

# 本地账户登录
LOCAL_AUTH_ENABLED=true
LOCAL_AUTH_USERNAME=admin
LOCAL_AUTH_PASSWORD=your_password
```

支持任何 OpenAI 兼容格式的中转 API，修改 `OPENAI_BASE_URL` 即可。

## 📁 项目结构

```
novel-forge/
├── backend/                 # 后端服务 (FastAPI)
│   ├── app/
│   │   ├── api/             # API 路由
│   │   ├── models/          # 数据模型
│   │   ├── services/        # 业务逻辑
│   │   ├── middleware/      # 中间件
│   │   └── main.py          # 应用入口
│   ├── alembic/             # 数据库迁移
│   ├── scripts/             # 工具脚本
│   └── requirements.txt
├── frontend/                # 前端应用 (React + Vite)
│   └── src/
│       ├── pages/
│       ├── components/
│       ├── services/
│       └── store/
├── docker-compose.yml
├── Dockerfile
└── README.md
```

## 🛠️ 技术栈

- **后端**：FastAPI · PostgreSQL · SQLAlchemy · OpenAI / Claude / Gemini SDK
- **前端**：React 18 · TypeScript · Ant Design · Zustand · Vite

## 📖 API 文档

启动后可访问：

- Swagger UI：`http://localhost:8000/docs`
- ReDoc：`http://localhost:8000/redoc`

## 📝 许可证

本项目采用 [GNU General Public License v3.0](LICENSE)。
