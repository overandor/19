"""FastAPI backend for the Autonomous Alpha Console."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
import time
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from scripts.harvest_signals import generate_signals, write_signals
from scripts.prompt_combinator import compute_focus

# ---------------------------------------------------------------------------
# Logging — structured JSON in production, plain text in dev
# ---------------------------------------------------------------------------
_log_format = os.getenv("LOG_FORMAT", "text")  # "json" | "text"

if _log_format == "json":
    try:
        from pythonjsonlogger import jsonlogger
        _handler = logging.StreamHandler()
        _handler.setFormatter(
            jsonlogger.JsonFormatter("%(asctime)s %(name)s %(levelname)s %(message)s")
        )
        logging.root.handlers = [_handler]
    except ImportError:
        pass

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("alpha_console")

# ---------------------------------------------------------------------------
# Optional API-key authentication
# ---------------------------------------------------------------------------
_API_KEY: Optional[str] = os.getenv("API_KEY")


def _check_api_key(request: Request) -> None:
    if not _API_KEY:
        return
    key = request.headers.get("X-Api-Key") or request.query_params.get("api_key")
    if key != _API_KEY:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid api key")


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------
limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])

# ---------------------------------------------------------------------------
# Startup / shutdown
# ---------------------------------------------------------------------------
_startup_time = time.time()


@asynccontextmanager
async def _lifespan(application: FastAPI):
    logger.info("alpha_console starting", extra={"pid": os.getpid()})
    yield
    logger.info("alpha_console shutting down gracefully")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Autonomous Alpha Console",
    description="Speculative signal research API — research-only, no live trading.",
    version="1.0.0",
    lifespan=_lifespan,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

_ALLOWED_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Signal handlers for clean Docker/K8s shutdown
# ---------------------------------------------------------------------------


def _install_signal_handlers() -> None:
    def _handle(signum, _frame):
        logger.info("received signal %s, exiting", signum)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)


# ---------------------------------------------------------------------------
# Request/response models
# ---------------------------------------------------------------------------
class ScanRequest(BaseModel):
    persist: bool = Field(False, description="Write signals.json to disk")


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
async def _to_thread(func, *args, **kwargs):
    return await asyncio.to_thread(func, *args, **kwargs)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/health", tags=["ops"])
async def health() -> Dict[str, Any]:
    """Liveness + basic dependency probe."""
    return {
        "status": "ok",
        "uptime_seconds": round(time.time() - _startup_time, 1),
        "pid": os.getpid(),
    }


@app.get("/signals", tags=["signals"], dependencies=[Depends(_check_api_key)])
@limiter.limit("30/minute")
async def signals(request: Request) -> Dict[str, Any]:
    """Synchronous signal harvest — no persistence."""
    payload = await _to_thread(generate_signals)
    return payload


@app.post("/focus", tags=["signals"], dependencies=[Depends(_check_api_key)])
@limiter.limit("10/minute")
async def focus(request: Request) -> Dict[str, Any]:
    """Recompute focus targets and persist cache/focus.json."""
    payload = await _to_thread(compute_focus, True)
    return payload


@app.post("/scan", tags=["signals"], dependencies=[Depends(_check_api_key)])
@limiter.limit("20/minute")
async def scan(request: Request, body: Optional[ScanRequest] = None) -> Dict[str, Any]:
    """Scan signals; optionally persist to signals.json."""
    persist = body.persist if body else False
    payload = await _to_thread(generate_signals)
    if persist:
        await _to_thread(write_signals, payload)
    return payload


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    logger.info("ws connected from %s", websocket.client)
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_text(json.dumps({"type": "error", "error": "invalid_json"}))
                continue

            action = data.get("type") or data.get("action")

            if action == "scan":
                persist = bool(data.get("persist"))
                logger.info("ws scan (persist=%s)", persist)
                payload = await _to_thread(generate_signals)
                if persist:
                    await _to_thread(write_signals, payload)
                await websocket.send_text(json.dumps({"type": "signals", "payload": payload}))

            elif action == "focus":
                persist = bool(data.get("persist", True))
                logger.info("ws focus (persist=%s)", persist)
                payload = await _to_thread(compute_focus, persist)
                await websocket.send_text(json.dumps({"type": "focus", "payload": payload}))

            else:
                logger.warning("ws unknown action: %s", action)
                await websocket.send_text(json.dumps({"type": "error", "error": "unknown_action"}))

    except WebSocketDisconnect:
        logger.info("ws disconnected")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    _install_signal_handlers()
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8765)),
        log_level=os.getenv("LOG_LEVEL", "info").lower(),
    )
