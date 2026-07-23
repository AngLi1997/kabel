# Kabel

## Project Overview

Kabel is a multimodal data annotation platform (image/video/audio) built with FastAPI + SQLAlchemy. It provides task management, file attachment handling, sample annotation, and real-time collaboration via WebSocket.

## Architecture

Layered architecture following Domain-Driven Design principles:

- **Domain Layer**: `kabel/internal/domain/models/` - SQLAlchemy ORM models (User, Task, TaskSample, TaskAttachment, TaskPreAnnotation, TaskCollaborator, TaskSampleUpdater)
- **Application Layer**: `kabel/internal/application/` - Business logic split into:
  - `command/` - Request/input Pydantic models
  - `response/` - Response Pydantic models
  - `service/` - Business logic orchestration (uses `db.begin()` for transactions)
- **Adapter Layer**: `kabel/internal/adapter/` - External interfaces:
  - `routers/` - FastAPI HTTP route handlers
  - `persistence/` - CRUD database operations
  - `ws/` - WebSocket handlers
- **Common**: `kabel/internal/common/` - Shared utilities:
  - `config.py` - Pydantic BaseSettings configuration
  - `db.py` - SQLAlchemy engine, session, Base
  - `security.py` - JWT token creation, password hashing
  - `error_code.py` - Error codes enum + exception handlers
  - `converter.py`, `xml_converter.py`, `tf_record_converter.py` - Export format converters
  - `websocket.py` - WebSocket connection manager
- **Dependencies**: `kabel/internal/dependencies/user.py` - FastAPI dependency injection (auth)
- **Middleware**: `kabel/internal/middleware/` - Content-type and tracing middleware

## Development Commands

- **Run server**: `kabel` or `python -m kabel.main`
- **Run server with options**: `kabel --host 0.0.0.0 --port 8000 --media-host http://localhost:8000`
- **Run tests**: `python -m pytest kabel/tests/ -v`
- **Run single test**: `python -m pytest kabel/tests/path/test_file.py::test_name -v`
- **Format code**: `black kabel/`
- **Lint**: `flake8 kabel/`
- **DB migration**: `alembic -c kabel/alembic_kabel/alembic.ini upgrade head`
- **Install**: `poetry install`

## Key Files

- Entry point: `kabel/main.py`
- Config: `kabel/internal/common/config.py`
- Database: `kabel/internal/common/db.py`
- Auth: `kabel/internal/common/security.py` + `kabel/internal/dependencies/user.py`
- Error handling: `kabel/internal/common/error_code.py`
- Alembic migrations: `kabel/alembic_kabel/versions/`
- Tests: `kabel/tests/`
- Version: `kabel/version.py`

## Environment Variables

- `PASSWORD_SECRET_KEY`: JWT signing key (required in production)
- `DATABASE_URL`: DB connection string (default: `sqlite:///<data_dir>/kabel.sqlite`)
- `MEDIA_HOST`: Media file serving host URL (default: `http://localhost:8000`)

Data directory is determined by `appdirs.user_data_dir("kabel")`.

## Tech Stack

- Python 3.11, FastAPI ^0.90, SQLAlchemy ^1.4 (1.x style), Pydantic v1
- Auth: python-jose (JWT), passlib + bcrypt
- DB: SQLite (default) or MySQL (optional)
- Migrations: Alembic
- Package manager: Poetry
- WebSocket: websockets ^10

## Testing

- Tests in `kabel/tests/` using pytest
- Test DB: SQLite file `./test.db` (not in-memory)
- Test fixtures in `kabel/tests/conftest.py`
- Test user: `test@example.com` / `test@123`
- Tables (except `user`) are cleaned between tests via `autouse` fixture
- `scope="module"` for `client` and `testuser_token_headers` fixtures

## Conventions

- Routers delegate to services; services use CRUD persistence layer
- All responses wrapped in `OkResp[T]` or `OkRespWithMeta[T]` (GenericModel-based)
- Custom exceptions: `KabelException` with `ErrorCode` enum
- Soft delete pattern: `deleted_at` timestamp on models
- Transaction management: `with db.begin():` blocks in service layer
- Session uses `autocommit=True` mode (legacy SQLAlchemy pattern)
