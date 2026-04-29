from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator
from pathlib import Path

import httpx
from fastapi import Cookie, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.db import engine
from app.dependencies import serializer, MAX_SESSION_AGE
from app.routes import auth, webhook, dashboard, payment, admin


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    app.state.http_client = httpx.AsyncClient()
    yield
    await app.state.http_client.aclose()
    await engine.dispose()


app = FastAPI(title="RunRename", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))

app.include_router(auth.router)
app.include_router(webhook.router)
app.include_router(dashboard.router)
app.include_router(payment.router)
app.include_router(admin.router)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.get("/", response_class=HTMLResponse)
async def landing(request: Request, session: str | None = Cookie(default=None)):
    if session:
        try:
            serializer.loads(session, max_age=MAX_SESSION_AGE)
            return RedirectResponse(url="/dashboard", status_code=302)
        except Exception:
            pass
    return templates.TemplateResponse(request, "landing.html", context={"user": None})


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
