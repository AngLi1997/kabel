from fastapi import FastAPI

from kabel.internal.middleware.content_type import ContentTypeMiddleware
from kabel.internal.middleware.tracing import TracingMiddleWare


def add_middleware(app: FastAPI):
    app.add_middleware(TracingMiddleWare)
    app.add_middleware(ContentTypeMiddleware)
