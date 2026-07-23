from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from kabel.version import version as kabel_version

class ContentTypeMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        
        # add Kabel-Version header
        response.headers["Kabel-Version"] = kabel_version
        
        # set content-type for javascript files
        if request.url.path.endswith(".js"):
            response.headers["content-type"] = "application/javascript"
            
        return response