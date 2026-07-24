# AGENTS.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Kabel 是多模态（图片/音频/视频）数据标注平台，前后端分离的双 workspace 单仓库。后端 `kabel-back/`（FastAPI + SQLAlchemy），前端 `kabel-front/`（pnpm workspace，React 18 + TS + Vite）。两个 workspace 相互独立，改动应限制在相关 workspace 内，不要让可复用 package 耦合到具体 app。

> `kabel-back/CLAUDE.md` 与 `AGENTS.md` 是后端专用补充说明（编码风格、提交规范等），本文件覆盖全仓库大局架构。

## 常用命令

后端（在 `kabel-back/` 下执行）：

```bash
uv sync --group test                                   # 安装依赖（含测试）
uv run kabel --host 0.0.0.0 --port 8002 --media-host http://localhost:8002  # 启动服务
uv run pytest kabel/tests -v                           # 全部测试
uv run pytest kabel/tests/internal/application/test_xxx.py::test_name -v    # 单个测试
uv run pytest --cov=kabel kabel/tests                  # 覆盖率
uv run black kabel && uv run flake8 kabel              # 格式化 + 检查（4 空格缩进，snake_case）
uv run alembic -c kabel/alembic_kabel/alembic.ini upgrade head   # 手动执行迁移
```

前端（在 `kabel-front/` 下执行）：

```bash
pnpm install
pnpm build            # 按依赖顺序构建全部可复用 packages（改了 packages/ 后需要）
pnpm dev              # 启动主应用于 3004 端口（= pnpm --filter @kabel/frontend start）
pnpm build:frontend   # 打包生产版主应用
pnpm lint:frontend    # lint + fix apps/frontend
pnpm lint:packages    # lint + fix packages
pnpm --filter @kabel/formatter test   # 运行某个 package 的 Jest 测试（仅部分 package 有测试）
```

开发前先 `cp kabel-back/.env.example kabel-back/.env`。提交遵循 Conventional Commits（`feat:`/`fix:`/`chore:`）。

## 后端架构（六边形/整洁架构）

代码在 `kabel-back/kabel/internal/`，严格分层，请求流向为 **router → service → crud → domain model**：

- `domain/models/` — SQLAlchemy ORM 实体，也是唯一的表结构真相：`task`、`sample`、`user`、`attachment`、`data_source`、`pre_annotation`、`export_job`、`auto_label_job`、`task_collaborator`。
- `application/` — 业务逻辑层，三个子目录配套：`command/`（入参 DTO）、`service/`（业务逻辑，事务边界在此）、`response/`（出参 DTO）。
- `adapter/` — 外部接口：`routers/`（FastAPI HTTP 端点，**保持 thin，只做参数解析与调用 service**）、`persistence/`（`crud_*.py`，所有 DB 访问集中于此）、`ws/`（WebSocket）。
- `common/` — 基础设施：`config.py`、`db.py`、`storage.py`（local / S3 抽象）、`crypto.py`/`security.py`、`converter.py`/`xml_converter.py`/`tf_record_converter.py`（导出格式）、`websocket.py`、`error_code.py`（`KabelException` + `ErrorCode`）。
- `dependencies/`（FastAPI DI，含鉴权）、`clients/`、`middleware/`（tracing、content_type）。

新增业务实体时通常需要在这五处同步：`domain/models/`、`application/command|service|response/`、`adapter/routers|persistence/`，并在 `adapter/routers/__init__.py` 的 `add_router()` 注册路由。

**入口与启动**：`kabel.main:cli`（Typer/click）。`main.py` 在导入时即完成装配：`init_tables()` 建表 → `run_db_migrations()` **自动执行 Alembic 迁移** → 注册 router/ws/middleware → 把前端构建产物 `kabel.internal.statics` 挂载为 SPA（HTML 禁缓存）。因此首次启动会自动建表并迁移，无需手动操作。

**配置**：`common/config.py` 的 pydantic-settings `Settings`，从 `.env` 读取。关键约束——**必须单 worker 运行**：WebSocket 协作者在线状态是进程内内存态，多 worker 会各自持有不完整视图（除非迁到 Redis 等共享后端）。生产环境务必设置 `PASSWORD_SECRET_KEY`（JWT 密钥）与数据库凭据。

**存储与鉴权**：`STORAGE_BACKEND` 切换 `local`/`s3`；JWT 采用滑动刷新——剩余寿命低于阈值时通过响应头 `X-New-Token` 下发新 token，活跃用户不会掉线。

**数据库**：默认 `mysql+pymysql://...`（MySQL 5.7+/8.0+），也支持 `sqlite:///...`。若 `DATABASE_URL` 指向 MySQL 但本地存在 sqlite 文件，启动时会自动触发 `migrate_to_mysql`。

## 前端架构（pnpm workspace monorepo）

- `apps/frontend`（`@kabel/frontend`）— 主应用，实际交付的 UI（Vite + React 18 + antd）。
- `apps/website` — 组件展示站。
- `packages/` — 可复用标注库，存在**拓扑依赖顺序**（`pnpm build` 即按此顺序）：
  `interface`（TS 类型）→ `i18n` → `formatter` → `image`（框架无关的图片标注内核）→ `components-react`（基础组件）→ `image-annotator-react` → `audio-react` → `video-react` → `audio-annotator-react` → `video-annotator-react`。
  标注器（`*-annotator-react`）组合底层内核（`image`/`audio-react`/`video-react`）与 `components-react`/`interface`/`i18n`。

**关键机制 —— 开发态源码直连 vs 生产态构建产物**：`vite.config.ts` 在非生产环境启用 `tsMonoAlias`，把 `@kabel/*` 直接指向各 package 的**源码**，因此改动 `packages/` 源码在 `pnpm dev` 下即时生效、无需重新构建；但生产 `build:frontend` 消费的是各 package 的 `dist`，所以**改了 packages 后要先 `pnpm build` 再 `build:frontend`**。

## 全栈集成

- **开发**：前端 3004，vite 把 `/api` → `http://127.0.0.1:8002`、`/ws` → `ws://127.0.0.1:8002`（后端）。API 前缀 `/api/v1`，OpenAPI 文档 `/docs`。
- **生产**：前端 `dist` 由 `kabel-back/scripts/resolve_frontend.sh` 移入 `kabel/internal/statics`，后端以 SPA 形式提供，前后端同源部署（见 `Dockerfile`）。

## AI 自动标注

`kabel-back/model_server/` 提供三套参考模型服务（**Florence-2**、**GroundingDINO+SAM**、**SAM3**），实现统一 HTTP 协议。后端 `application/service/auto_label.py` 通过 `AI_MODEL_ENDPOINT` 调用，受 `AI_AUTO_LABEL_ENABLED` 开关控制，支持的标注工具：`rectTool`、`polygonTool`、`pointTool`、`lineTool`。选型见 `model_server/README.md`。
