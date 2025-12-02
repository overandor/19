import asyncio
import json
import logging
from typing import Any, Dict

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from scripts.harvest_signals import generate_signals, write_signals
from scripts.prompt_combinator import compute_focus

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("backend")

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"] ,
    allow_headers=["*"],
)


async def _to_thread(func, *args, **kwargs):
    return await asyncio.to_thread(func, *args, **kwargs)


@app.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/signals")
async def signals() -> Dict[str, Any]:
    payload = await _to_thread(generate_signals)
    return payload


@app.post("/focus")
async def focus() -> Dict[str, Any]:
    payload = await _to_thread(compute_focus, True)
    return payload


@app.post("/scan")
async def scan(body: Dict[str, Any] | None = None) -> Dict[str, Any]:
    persist = bool(body.get("persist")) if isinstance(body, dict) else False
    payload = await _to_thread(generate_signals)
    if persist:
        await _to_thread(write_signals, payload)
    return payload


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        while True:
            message = await websocket.receive_text()
            try:
                data = json.loads(message)
            except json.JSONDecodeError:
                await websocket.send_text(json.dumps({"type": "error", "error": "invalid_json"}))
                continue

            action = data.get("type") or data.get("action")
            if action == "scan":
                persist = bool(data.get("persist"))
                logger.info("scan request (persist=%s)", persist)
                payload = await _to_thread(generate_signals)
                if persist:
                    await _to_thread(write_signals, payload)
                await websocket.send_text(json.dumps({"type": "signals", "payload": payload}))
            elif action == "focus":
                persist = bool(data.get("persist", True))
                logger.info("focus request (persist=%s)", persist)
                payload = await _to_thread(compute_focus, persist)
                await websocket.send_text(json.dumps({"type": "focus", "payload": payload}))
            else:
                logger.warning("unknown action received: %s", action)
                await websocket.send_text(json.dumps({"type": "error", "error": "unknown_action"}))
    except WebSocketDisconnect:
        return


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8765)
