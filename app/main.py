import asyncio
import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator
from datetime import datetime, timedelta
from pathlib import Path

import httpx
from fastapi import Cookie, FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import update

from itsdangerous import BadSignature, SignatureExpired

from app.db import engine, async_session
from app.dependencies import serializer, MAX_SESSION_AGE
from app.models.activity import Activity
from app.routes import auth, webhook, dashboard, payment, admin

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def _purge_stale_cache() -> None:
    cutoff = datetime.utcnow() - timedelta(days=7)
    async with async_session() as db:
        result = await db.execute(
            update(Activity)
            .where(Activity.created_at < cutoff, Activity.raw_context.isnot(None))
            .values(raw_context=None)
        )
        if result.rowcount:
            await db.commit()
            logger.info("Purged raw_context from %d activities older than 7 days", result.rowcount)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    app.state.http_client = httpx.AsyncClient()
    await _purge_stale_cache()
    yield
    tasks = webhook._background_tasks.copy()
    if tasks:
        logger.info("Waiting for %d background rename(s) to finish...", len(tasks))
        done, pending = await asyncio.wait(tasks, timeout=90)
        for t in pending:
            t.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
    await app.state.http_client.aclose()
    await engine.dispose()


app = FastAPI(title="LogLine", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))
app.mount("/static", StaticFiles(directory=str(Path(__file__).resolve().parent / "static")), name="static")

app.include_router(auth.router)
app.include_router(webhook.router)
app.include_router(dashboard.router)
app.include_router(payment.router)
app.include_router(admin.router)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.get("/", response_class=HTMLResponse)
async def landing(
    request: Request,
    session: str | None = Cookie(default=None),
    error: str | None = Query(default=None),
):
    if session:
        try:
            serializer.loads(session, max_age=MAX_SESSION_AGE)
            return RedirectResponse(url="/dashboard", status_code=302)
        except (BadSignature, SignatureExpired):
            pass
    return templates.TemplateResponse(request, "landing.html", context={"user": None, "error": error})


@app.get("/privacy", response_class=HTMLResponse)
async def privacy(request: Request):
    return templates.TemplateResponse(request, "privacy.html", context={"user": None})


@app.get("/terms", response_class=HTMLResponse)
async def terms(request: Request):
    return templates.TemplateResponse(request, "terms.html", context={"user": None})


@app.get("/refund", response_class=HTMLResponse)
async def refund(request: Request):
    return templates.TemplateResponse(request, "refund.html", context={"user": None})


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
