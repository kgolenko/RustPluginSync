import asyncio
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from rust_sync.service import (
    Settings,
    SyncController,
    SyncState,
    _load_config,
    validate_config_dict,
)


def _tail_lines(path: Path, max_lines: int) -> list[str]:
    if max_lines <= 0:
        return []
    try:
        with path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            block = 1024
            data = b""
            while size > 0 and data.count(b"\n") <= max_lines:
                step = min(block, size)
                f.seek(-step, os.SEEK_CUR)
                data = f.read(step) + data
                f.seek(-step, os.SEEK_CUR)
                size -= step
            lines = data.splitlines()[-max_lines:]
            return [line.decode("utf-8", errors="replace") for line in lines]
    except FileNotFoundError:
        return []


def _match_log_line(line: str, level: str | None, server: str | None) -> bool:
    if level and level.upper() not in line:
        return False
    if server and f"[{server}]" not in line:
        return False
    return True


def create_app(
    settings: Settings, state: SyncState, controller: SyncController, config_path: Path
) -> FastAPI:
    app = FastAPI()
    static_dir = Path(__file__).parent / "web" / "static"
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        html = (static_dir / "index.html").read_text(encoding="utf-8")
        return HTMLResponse(html)

    @app.get("/api/status")
    def status() -> JSONResponse:
        snapshot = state.snapshot()
        payload = {
            "paused": controller.is_paused(),
            "dry_run": controller.get_dry_run(),
            "config_path": str(config_path),
            "servers": snapshot["servers"],
        }
        return JSONResponse(payload)

    @app.get("/api/history")
    def history() -> JSONResponse:
        snapshot = state.snapshot()
        return JSONResponse({"items": snapshot["history"]})

    @app.get("/api/config")
    def config() -> JSONResponse:
        cfg = _load_config(config_path)
        return JSONResponse(cfg)

    @app.post("/api/validate")
    async def validate(request: Request) -> JSONResponse:
        try:
            body = await request.json()
            errors = validate_config_dict(body)
            return JSONResponse({"ok": not errors, "errors": errors})
        except Exception as exc:
            return JSONResponse({"ok": False, "errors": [str(exc)]}, status_code=400)

    @app.post("/api/open-config")
    def open_config() -> JSONResponse:
        if os.name == "nt":
            try:
                os.startfile(str(config_path))  # type: ignore[attr-defined]
                return JSONResponse({"ok": True})
            except Exception as exc:
                return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)
        return JSONResponse({"ok": False, "error": "unsupported OS"}, status_code=400)

    @app.post("/api/pause")
    def pause() -> JSONResponse:
        controller.pause()
        return JSONResponse({"ok": True})

    @app.post("/api/resume")
    def resume() -> JSONResponse:
        controller.resume()
        return JSONResponse({"ok": True})

    @app.post("/api/run-once")
    def run_once() -> JSONResponse:
        controller.request_run_once()
        return JSONResponse({"ok": True})

    @app.post("/api/dry-run")
    async def dry_run(request: Request) -> JSONResponse:
        body = await request.json()
        enabled = bool(body.get("enabled", False))
        controller.set_dry_run(enabled)
        return JSONResponse({"ok": True, "dry_run": enabled})

    @app.get("/api/logs/stream")
    async def logs_stream(
        level: str | None = None, server: str | None = None, tail: int = 200
    ) -> StreamingResponse:
        async def event_stream() -> AsyncIterator[str]:
            for line in _tail_lines(settings.log_path, tail):
                if _match_log_line(line, level, server):
                    yield f"data: {line}\n\n"

            try:
                with settings.log_path.open(
                    "r", encoding="utf-8", errors="replace"
                ) as f:
                    f.seek(0, os.SEEK_END)
                    while True:
                        line = f.readline()
                        if line:
                            line = line.rstrip("\n")
                            if _match_log_line(line, level, server):
                                yield f"data: {line}\n\n"
                        else:
                            await asyncio.sleep(0.5)
            except FileNotFoundError:
                return

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    return app


def run_web(
    settings: Settings,
    state: SyncState,
    controller: SyncController,
    config_path: Path,
    host: str,
    port: int,
) -> None:
    import uvicorn

    app = create_app(settings, state, controller, config_path)
    uvicorn.run(app, host=host, port=port, log_level="info")


def start_runner_background(
    runner: Any, startup_delay_seconds: int
) -> threading.Thread:
    def _target() -> None:
        runner.settings.startup_delay_seconds = max(0, startup_delay_seconds)
        logging.info("START")
        time.sleep(runner.settings.startup_delay_seconds)
        runner.run_forever()

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
    return thread
