import asyncio
import json
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
    _load_config,
    _settings_from_config,
    _setup_logging,
    create_runtime,
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


class WebRuntime:
    def __init__(self, settings: Settings, config_path: Path) -> None:
        self._lock = threading.Lock()
        self.config_path = config_path
        self.settings = settings
        self.state, self.controller, self.runner = create_runtime(settings)
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        self._start_thread(self.runner, self.settings)

    def _start_thread(self, runner: Any, settings: Settings) -> None:
        def _target() -> None:
            logging.info("START")
            time.sleep(settings.startup_delay_seconds)
            runner.run_forever()

        thread = threading.Thread(target=_target, daemon=True)
        thread.start()
        self.thread = thread

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return self.state.snapshot()

    def get_controller(self) -> SyncController:
        with self._lock:
            return self.controller

    def get_settings(self) -> Settings:
        with self._lock:
            return self.settings

    def restart(self, new_settings: Settings) -> None:
        with self._lock:
            prev_controller = self.controller
            prev_runner = self.runner
            prev_thread = self.thread
            paused = prev_controller.is_paused()
            dry_run = prev_controller.get_dry_run()
            prev_runner.stop()

        if prev_thread:
            prev_thread.join(timeout=5)

        with self._lock:
            _setup_logging(new_settings.log_path)
            self.settings = new_settings
            self.state, self.controller, self.runner = create_runtime(new_settings)
            if paused:
                self.controller.pause()
            self.controller.set_dry_run(dry_run)
            self._start_thread(self.runner, self.settings)


def create_app(runtime: WebRuntime) -> FastAPI:
    app = FastAPI()
    static_dir = Path(__file__).parent / "web" / "static"
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        html = (static_dir / "index.html").read_text(encoding="utf-8")
        return HTMLResponse(html)

    @app.get("/api/status")
    def status() -> JSONResponse:
        snapshot = runtime.snapshot()
        controller = runtime.get_controller()
        payload = {
            "paused": controller.is_paused(),
            "dry_run": controller.get_dry_run(),
            "config_path": str(runtime.config_path),
            "servers": snapshot["servers"],
        }
        return JSONResponse(payload)

    @app.get("/api/history")
    def history() -> JSONResponse:
        snapshot = runtime.snapshot()
        return JSONResponse({"items": snapshot["history"]})

    @app.get("/api/config")
    def config() -> JSONResponse:
        cfg = _load_config(runtime.config_path)
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
                os.startfile(str(runtime.config_path))  # type: ignore[attr-defined]
                return JSONResponse({"ok": True})
            except Exception as exc:
                return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)
        return JSONResponse({"ok": False, "error": "unsupported OS"}, status_code=400)

    @app.post("/api/pause")
    def pause() -> JSONResponse:
        runtime.get_controller().pause()
        return JSONResponse({"ok": True})

    @app.post("/api/resume")
    def resume() -> JSONResponse:
        runtime.get_controller().resume()
        return JSONResponse({"ok": True})

    @app.post("/api/run-once")
    def run_once() -> JSONResponse:
        runtime.get_controller().request_run_once()
        return JSONResponse({"ok": True})

    @app.post("/api/dry-run")
    async def dry_run(request: Request) -> JSONResponse:
        body = await request.json()
        enabled = bool(body.get("enabled", False))
        runtime.get_controller().set_dry_run(enabled)
        return JSONResponse({"ok": True, "dry_run": enabled})

    @app.get("/api/logs/stream")
    async def logs_stream(
        level: str | None = None, server: str | None = None, tail: int = 200
    ) -> StreamingResponse:
        async def event_stream() -> AsyncIterator[str]:
            log_path = runtime.get_settings().log_path
            for line in _tail_lines(log_path, tail):
                if _match_log_line(line, level, server):
                    yield f"data: {line}\n\n"

            try:
                log_path = runtime.get_settings().log_path
                with log_path.open("r", encoding="utf-8", errors="replace") as f:
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

    @app.post("/api/config/save")
    async def save_config(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except Exception as exc:
            return JSONResponse({"ok": False, "errors": [str(exc)]}, status_code=400)

        errors = validate_config_dict(body)
        if errors:
            return JSONResponse({"ok": False, "errors": errors}, status_code=400)

        runtime.config_path.parent.mkdir(parents=True, exist_ok=True)
        runtime.config_path.write_text(
            json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        new_settings = _settings_from_config(body)
        runtime.restart(new_settings)
        return JSONResponse({"ok": True})

    return app


def run_web(runtime: WebRuntime, host: str, port: int) -> None:
    import uvicorn

    app = create_app(runtime)
    uvicorn.run(app, host=host, port=port, log_level="info")
