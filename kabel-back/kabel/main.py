from typing import Any
from contextlib import asynccontextmanager

from loguru import logger
import click
import uvicorn
from fastapi import FastAPI, Response
from fastapi.staticfiles import StaticFiles

from kabel.internal.adapter.routers import add_router
from kabel.internal.adapter.ws import add_ws_router
from kabel.internal.middleware import add_middleware
from kabel.internal.common.logger import init_logging
from kabel.internal.common.db import init_tables
from kabel.internal.common.config import ensure_password_secret_key, settings
from kabel.internal.common.error_code import add_exception_handler
from kabel.alembic_kabel.run_migrate import run_db_migrations
from kabel.scripts.migrate_to_mysql import migrate_to_mysql

from .version import version as kabel_version

description = """
Kabel backend.

## Users

You will be able to:

* **Signup**
* **Login**
* **Logout**.

## Tasks

You will be able to:

* **CRUD**

## Task attachment

You will be able to:

* **upload attachment**
* **download attachment**
* **delete attachment**

## Task sample

You will be able to:

* **list sample**
* **create sample**
* **get sample**
* **update sample**
* **export sample**
"""


tags_metadata = [
    {
        "name": "users",
        "description": "Operations with users.",
    },
    {
        "name": "tasks",
        "description": "Task management.",
    },
    {
        "name": "attachments",
        "description": "Task attachment management.",
    },
    {
        "name": "samples",
        "description": "Task sample management.",
    },
]

@asynccontextmanager
async def lifespan(app):
    if settings.need_migration_to_mysql:
        logger.info("Migrating database to MySQL")
        migrate_to_mysql()
    yield


app = FastAPI(
    lifespan=lifespan,
    title="Kabel",
    description=description,
    version=kabel_version,
    terms_of_service="",
    contact={
        "name": "kabel",
        "url": "http://kabel.example.com/contact/",
        "email": "kabel@example.com",
    },
    license_info={
        "name": "Apache 2.0",
        "url": "https://www.apache.org/licenses/LICENSE-2.0.html",
    },
    openapi_tags=tags_metadata,
)

secret_key_source = ensure_password_secret_key()
if secret_key_source == "generated":
    logger.warning(
        "PASSWORD_SECRET_KEY not set; generated a persistent local key. "
        "Set it explicitly in .env for production."
    )
elif secret_key_source == "loaded":
    logger.warning(
        "PASSWORD_SECRET_KEY not set; using the persistent local "
        "fallback key. "
        "Set it explicitly in .env for production."
    )

init_logging()
init_tables()
run_db_migrations()
add_exception_handler(app=app)
add_router(app=app)
add_ws_router(app=app)
add_middleware(app=app)

class NoCacheStaticFiles(StaticFiles):
    def __init__(self, *args: Any, **kwargs: Any):
        self.cachecontrol = "max-age=0, no-cache, no-store, must-revalidate"
        self.pragma = "no-cache"
        self.expires = "0"
        super().__init__(*args, **kwargs)

    def file_response(self, *args: Any, **kwargs: Any) -> Response:
        resp = super().file_response(*args, **kwargs)
        
        # No cache for html files
        if resp.media_type == "text/html":
            resp.headers.setdefault("Cache-Control", self.cachecontrol)
            resp.headers.setdefault("Pragma", self.pragma)
            resp.headers.setdefault("Expires", self.expires)
            
        return resp

app.mount("", NoCacheStaticFiles(packages=["kabel.internal"], html=True))

@click.group(invoke_without_command=True)
@click.option('--host', default='localhost', help='Server host')
@click.option('--port', default=8000, help='Server port')
@click.option('--media-host', default='http://localhost:8000', help='Media Host')
@click.pass_context
def cli(ctx: click.Context, host: str, port: int, media_host: str):
    if ctx.invoked_subcommand is None:
        settings.PORT = port
        settings.HOST = host
        settings.MEDIA_HOST = media_host
        
        uvicorn.run(app=app, host=settings.HOST, port=settings.PORT, ws="websockets")

@cli.command('migrate_to_mysql')
def to_mysql():
    """Migrate database to MySQL"""
    migrate_to_mysql()

if __name__ == "__main__":
    cli()
