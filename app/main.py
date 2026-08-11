import base64
import os
import secrets
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware

from . import db
from .api import router as api_router

db.init_db()

app = FastAPI(title="Season Tracker")

# Gate the whole app behind a single shared username/password when deployed
# --  APP_USERNAME / APP_PASSWORD are read from the environment (set them in
# Render's dashboard, never in code -- this repo is public on GitHub) so
# colleagues get one login prompt and no one else can reach the site or its
# Import tab. Locally, neither var is set, so this is a total no-op: no
# prompt, no change in behaviour.
APP_USERNAME = os.environ.get("APP_USERNAME")
APP_PASSWORD = os.environ.get("APP_PASSWORD")


class BasicAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if not APP_USERNAME or not APP_PASSWORD:
            return await call_next(request)

        auth_header = request.headers.get("authorization", "")
        if auth_header.lower().startswith("basic "):
            try:
                decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
                username, _, password = decoded.partition(":")
            except Exception:
                username, password = "", ""
            # compare_digest -- timing-safe, so response time can't leak how
            # many characters matched.
            if secrets.compare_digest(username, APP_USERNAME) and secrets.compare_digest(password, APP_PASSWORD):
                return await call_next(request)

        return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="Season Tracker"'})


app.add_middleware(BasicAuthMiddleware)
app.include_router(api_router)

STATIC_DIR = Path(__file__).resolve().parent / "static"


class NoCacheStaticFiles(StaticFiles):
    """This is a local, actively-edited dev tool -- a browser holding onto a
    stale cached index.html/app.js/style.css after an update is a real,
    recurring annoyance, not just a testing quirk. `no-store` forces a full
    fetch every load, so a hard refresh is never required to see the
    latest."""
    def file_response(self, *args, **kwargs):
        resp = super().file_response(*args, **kwargs)
        resp.headers["Cache-Control"] = "no-store"
        return resp


app.mount("/static", NoCacheStaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-store"})
