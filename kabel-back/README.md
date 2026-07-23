# Kabel 后端

Kabel 后端基于 FastAPI、SQLAlchemy 和 Alembic，提供用户认证、任务与样本管理、附件、数据源、预标注、自动标注、导出及 WebSocket 协作接口。

## 启动

```bash
cp .env.example .env
uv sync
uv run kabel --host 0.0.0.0 --port 8002 --media-host http://localhost:8002
```

默认数据库连接为：

```dotenv
DATABASE_URL=mysql+pymysql://root:root@localhost:3306/kabel
```

MySQL 中需预先创建 `kabel` 数据库；数据表和迁移会在服务启动时自动处理。

接口文档：<http://localhost:8002/docs>

更多完整说明请查看项目根目录的 `README.md`。
