from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from . import db
from .api import router as api_router

db.init_db()

app = FastAPI(title="Season Tracker")
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
