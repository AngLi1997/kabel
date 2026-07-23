from fastapi import FastAPI

from kabel.internal.common.config import settings
from kabel.internal.adapter.routers import user
from kabel.internal.adapter.routers import task
from kabel.internal.adapter.routers import sample
from kabel.internal.adapter.routers import attachment
from kabel.internal.adapter.routers import pre_annotation
from kabel.internal.adapter.routers import datasource


def add_router(app: FastAPI):
    app.include_router(user.router, prefix=settings.API_V1_STR)
    app.include_router(task.router, prefix=settings.API_V1_STR)
    app.include_router(attachment.router, prefix=settings.API_V1_STR)
    app.include_router(sample.router, prefix=settings.API_V1_STR)
    app.include_router(pre_annotation.router, prefix=settings.API_V1_STR)
    app.include_router(datasource.router, prefix=settings.API_V1_STR)
