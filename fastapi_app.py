from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
STATIC = ROOT / "static"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from web_app import (  # noqa: E402
    fetch_email_resumes,
    list_interview_confirmations,
    list_jobs,
    list_outbox_items,
    list_resume_library,
    load_email_config,
    load_sample_payload,
    load_workbench_data,
    parse_uploaded_resume,
    run_recruitment,
    safe_upload_name,
    save_interview_confirmation,
    save_job,
    unique_path,
)


def create_app() -> FastAPI:
    app = FastAPI(title="ZhipinAgent API", version="0.3.0")
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    @app.get("/api/sample")
    def api_sample() -> dict[str, Any]:
        return load_sample_payload()

    @app.get("/api/workbench")
    def api_workbench() -> Any:
        return handle_action(lambda: {"ok": True, "data": load_workbench_data()})

    @app.get("/api/jobs")
    def api_jobs() -> Any:
        return handle_action(lambda: {"ok": True, "jobs": list_jobs()})

    @app.get("/api/resumes")
    def api_resumes() -> Any:
        return handle_action(lambda: {"ok": True, "resumes": list_resume_library()})

    @app.get("/api/outbox")
    def api_outbox() -> Any:
        return handle_action(lambda: {"ok": True, "items": list_outbox_items()})

    @app.get("/api/interviews")
    def api_interviews() -> Any:
        return handle_action(lambda: {"ok": True, "interviews": list_interview_confirmations()})

    @app.get("/api/email/config")
    def api_email_config() -> Any:
        return handle_action(lambda: {"ok": True, "config": load_email_config()})

    @app.post("/api/upload")
    async def api_upload(files: list[UploadFile] = File(...)) -> Any:
        return handle_action(lambda: {"ok": True, "files": save_uploaded_files(files)})

    @app.post("/api/jobs/save")
    def api_jobs_save(payload: dict[str, Any]) -> Any:
        return handle_action(lambda: {"ok": True, "job": save_job(payload)})

    @app.post("/api/interviews/confirm")
    def api_interviews_confirm(payload: dict[str, Any]) -> Any:
        return handle_action(lambda: {"ok": True, "confirmation": save_interview_confirmation(payload)})

    @app.post("/api/email/fetch")
    def api_email_fetch(payload: dict[str, Any]) -> Any:
        return handle_action(lambda: fetch_email_resumes(payload))

    @app.post("/api/run")
    def api_run(payload: dict[str, Any]) -> Any:
        return handle_action(lambda: {"ok": True, "result": run_recruitment(payload)})

    return app


def handle_action(action) -> Any:
    try:
        return action()
    except Exception as exc:
        status = 400 if isinstance(exc, ValueError) else 500
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=status)


def save_uploaded_files(files: list[UploadFile]) -> list[dict[str, Any]]:
    upload_dir = ROOT / "data" / "web_uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    saved: list[dict[str, Any]] = []

    for upload in files:
        if not upload.filename:
            continue
        target = unique_path(upload_dir / safe_upload_name(upload.filename))
        with target.open("wb") as handle:
            shutil.copyfileobj(upload.file, handle)
        file_info: dict[str, Any] = {
            "name": upload.filename,
            "path": str(target),
            "size": target.stat().st_size,
            "updatedAt": datetime.fromtimestamp(target.stat().st_mtime).isoformat(),
            "source": "web_uploads",
        }
        file_info.update(parse_uploaded_resume(target))
        saved.append(file_info)

    if not saved:
        raise ValueError("No files were uploaded.")
    return saved


app = create_app()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the ZhipinAgent FastAPI console.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    return parser.parse_args()


def main() -> None:
    import uvicorn

    args = parse_args()
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
