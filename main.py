"""FastAPI app: REST/WebSocket API + static dashboard, single Railway service."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import db
from app.api import router as api_router
from app.poller import poller

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

FRONTEND_DIR = Path(__file__).parent / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init_pool()
    await poller.start()
    yield
    await poller.stop()
    await db.close_pool()


app = FastAPI(title="Sharp Karaine", lifespan=lifespan)
app.include_router(api_router)
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/healthz")
async def healthz():
    return {"ok": True}


@app.get("/")
async def index():
    return FileResponse(FRONTEND_DIR / "index.html")
