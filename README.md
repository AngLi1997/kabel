# Kabel

Kabel 是一个面向图片、音频和视频的多模态数据标注平台，提供任务管理、数据导入、在线标注、协作、预标注和结果导出能力。

项目采用前后端分离结构：

```text
kabel/
├── kabel-back/    # FastAPI + SQLAlchemy 后端
└── kabel-front/   # React + TypeScript 前端及标注组件
```

## 功能

- 图片、音频和视频标注
- 矩形、点、线、多边形、立体框等图片标注工具
- 标注任务、样本、附件和协作者管理
- 本地文件与 S3 兼容对象存储
- 预标注、自动标注和多种结果导出格式
- WebSocket 实时协作

## 技术栈

- 后端：Python 3.11+、FastAPI、SQLAlchemy、Alembic
- 前端：React 18、TypeScript、Vite、pnpm workspace
- 默认数据库：MySQL 5.7+/8.0+

## 本地开发

### 1. 准备 MySQL

默认开发配置：

```text
地址：localhost:3306
用户：root
密码：root
数据库：kabel
```

创建数据库：

```sql
CREATE DATABASE IF NOT EXISTS kabel
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;
```

后端连接配置位于 `kabel-back/.env`：

```dotenv
DATABASE_URL=mysql+pymysql://root:root@localhost:3306/kabel
MEDIA_HOST=http://localhost:8002
PASSWORD_SECRET_KEY=dev-secret-key-change-in-production
```

生产环境必须替换 `PASSWORD_SECRET_KEY` 和数据库凭据。

### 2. 启动后端

```bash
cd kabel-back
uv sync
uv run kabel --host 0.0.0.0 --port 8002 --media-host http://localhost:8002
```

首次启动会自动创建数据表并执行 Alembic 迁移。

- API：<http://localhost:8002/api/v1>
- OpenAPI：<http://localhost:8002/docs>

### 3. 启动前端

```bash
cd kabel-front
pnpm install
pnpm dev
```

访问 <http://localhost:3004>。开发服务器会把 `/api` 和 `/ws` 请求代理到 `http://127.0.0.1:8002`。

## 常用命令

后端：

```bash
cd kabel-back
uv sync --group test
uv run pytest kabel/tests -v
uv run alembic -c kabel/alembic_kabel/alembic.ini upgrade head
uv run black kabel
uv run flake8 kabel
```

前端：

```bash
cd kabel-front
pnpm build
pnpm build:frontend
```

## 可选配置

后端通过环境变量配置。常用配置可参考 `kabel-back/.env.example`，包括：

- `DATABASE_URL`：MySQL 或 SQLite 连接串
- `MEDIA_HOST`：后端媒体文件访问地址
- `STORAGE_BACKEND`：`local` 或 `s3`
- `S3_*`：S3 兼容对象存储配置
- `AI_AUTO_LABEL_ENABLED` 与 `AI_*`：自动标注服务配置

虽然默认使用 MySQL，仍可按需切换 SQLite：

```dotenv
DATABASE_URL=sqlite:///data/kabel.sqlite
```

## 许可证

Apache License 2.0。
