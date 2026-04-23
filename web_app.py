from __future__ import annotations

import argparse
import cgi
import json
import mimetypes
import os
import shutil
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
STATIC = ROOT / "static"

import sys

sys.path.insert(0, str(SRC))

from recruitment_agents.parsers import ResumeParser
from recruitment_agents.tools.inbox import InboxResumeFetcher, config_from_payload
from recruitment_agents.workflow import build_workflow


class RecruitmentWebHandler(SimpleHTTPRequestHandler):
    server_version = "RecruitmentWorkbench/0.2"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.serve_file(STATIC / "index.html")
            return
        if parsed.path == "/api/sample":
            self.send_json(load_sample_payload())
            return
        if parsed.path == "/api/workbench":
            self.send_json({"ok": True, "data": load_workbench_data()})
            return
        if parsed.path == "/api/jobs":
            self.send_json({"ok": True, "jobs": list_jobs()})
            return
        if parsed.path == "/api/resumes":
            self.send_json({"ok": True, "resumes": list_resume_library()})
            return
        if parsed.path == "/api/outbox":
            self.send_json({"ok": True, "items": list_outbox_items()})
            return
        if parsed.path == "/api/email/config":
            self.send_json({"ok": True, "config": load_email_config()})
            return
        if parsed.path.startswith("/static/"):
            self.serve_file(STATIC / parsed.path.removeprefix("/static/"))
            return
        self.send_error(404, "Not found")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/upload":
            self.handle_json_action(lambda: {"ok": True, "files": self.handle_upload()})
            return
        if parsed.path == "/api/jobs/save":
            self.handle_json_action(lambda: {"ok": True, "job": save_job(self.read_json())})
            return
        if parsed.path == "/api/interviews/confirm":
            self.handle_json_action(lambda: {"ok": True, "confirmation": save_interview_confirmation(self.read_json())})
            return
        if parsed.path == "/api/email/fetch":
            self.handle_json_action(lambda: fetch_email_resumes(self.read_json()))
            return
        if parsed.path == "/api/run":
            self.handle_json_action(lambda: {"ok": True, "result": run_recruitment(self.read_json())})
            return
        self.send_error(404, "Not found")

    def handle_json_action(self, action) -> None:
        try:
            payload = action()
        except Exception as exc:
            self.send_json({"ok": False, "error": str(exc)}, status=500)
            return
        self.send_json(payload)

    def handle_upload(self) -> list[dict[str, Any]]:
        content_type = self.headers.get("Content-Type", "")
        if not content_type.lower().startswith("multipart/form-data"):
            raise ValueError("Upload request must use multipart/form-data.")

        form = cgi.FieldStorage(
            fp=self.rfile,
            headers=self.headers,
            environ={
                "REQUEST_METHOD": "POST",
                "CONTENT_TYPE": content_type,
                "CONTENT_LENGTH": self.headers.get("Content-Length", "0"),
            },
        )
        fields = form["files"] if "files" in form else []
        if not isinstance(fields, list):
            fields = [fields]

        upload_dir = ROOT / "data" / "web_uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)
        saved: list[dict[str, Any]] = []
        for field in fields:
            if not getattr(field, "filename", ""):
                continue
            filename = safe_upload_name(field.filename)
            target = unique_path(upload_dir / filename)
            with target.open("wb") as handle:
                shutil.copyfileobj(field.file, handle)
            file_info: dict[str, Any] = {
                "name": field.filename,
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

    def read_json(self) -> dict[str, Any]:
        content_length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(content_length)
        if not body:
            return {}
        return json.loads(body.decode("utf-8"))

    def send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def serve_file(self, path: Path) -> None:
        if not path.exists() or not path.is_file():
            self.send_error(404, "Not found")
            return
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: Any) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[{timestamp}] {self.address_string()} {format % args}")


def load_sample_payload() -> dict[str, Any]:
    job_path = ROOT / "data" / "sample_job.txt"
    resume_dir = ROOT / "data" / "resumes"
    return {
        "jobDescription": job_path.read_text(encoding="utf-8"),
        "resumePaths": [str(resume_dir)],
        "threshold": 70,
        "timezone": "Asia/Shanghai",
        "approvalStatus": "pending",
        "approvedBy": "HR reviewer",
        "approvalNotes": "",
        "notificationChannels": os.getenv("NOTIFICATION_CHANNELS", "json"),
    }


def load_workbench_data() -> dict[str, Any]:
    return {
        "sample": load_sample_payload(),
        "jobs": list_jobs(),
        "resumes": list_resume_library(),
        "outbox": list_outbox_items(),
        "interviews": list_interview_confirmations(),
        "emailConfig": load_email_config(),
    }


def load_email_config() -> dict[str, Any]:
    provider = os.getenv("IMAP_PROVIDER", "")
    return {
        "provider": provider,
        "host": os.getenv("IMAP_HOST", ""),
        "port": int(os.getenv("IMAP_PORT", "993")),
        "username": os.getenv("IMAP_USERNAME", ""),
        "folder": os.getenv("IMAP_FOLDER", "INBOX"),
        "search": os.getenv("IMAP_SEARCH", "UNSEEN"),
        "maxMessages": int(os.getenv("IMAP_MAX_MESSAGES", "20")),
        "useSsl": os.getenv("IMAP_SSL", "true").lower() != "false",
        "markSeen": os.getenv("IMAP_MARK_SEEN", "false").lower() == "true",
        "configured": bool(os.getenv("IMAP_HOST") and os.getenv("IMAP_USERNAME") and os.getenv("IMAP_PASSWORD")) or provider in {"outlook", "qq", "163", "gmail"},
    }


def list_jobs() -> list[dict[str, Any]]:
    sample = load_sample_payload()
    sample_job = {
        "id": "sample-ai-agent-engineer",
        "title": "多智能体招聘系统 AI Engineer",
        "department": "AI Platform",
        "location": "上海 / Remote",
        "status": "open",
        "headcount": 2,
        "createdAt": datetime.fromtimestamp((ROOT / "data" / "sample_job.txt").stat().st_mtime).isoformat(),
        "description": sample["jobDescription"],
    }
    jobs_by_id = {sample_job["id"]: sample_job}
    order = [sample_job["id"]]
    jobs_dir = ROOT / "data" / "jobs"
    if jobs_dir.exists():
        for path in sorted(jobs_dir.glob("*.json")):
            try:
                job = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            job_id = str(job.get("id") or path.stem)
            if job_id not in order:
                order.append(job_id)
            jobs_by_id[job_id] = job
    return [jobs_by_id[job_id] for job_id in order]


def save_job(payload: dict[str, Any]) -> dict[str, Any]:
    title = str(payload.get("title") or "").strip()
    description = str(payload.get("description") or "").strip()
    if not title:
        raise ValueError("职位名称不能为空。")
    if not description:
        raise ValueError("职位 JD 不能为空。")

    jobs_dir = ROOT / "data" / "jobs"
    jobs_dir.mkdir(parents=True, exist_ok=True)
    job_id = str(payload.get("id") or slugify(title) or f"job-{int(datetime.now().timestamp())}")
    job = {
        "id": job_id,
        "title": title,
        "department": str(payload.get("department") or "AI Platform"),
        "location": str(payload.get("location") or "Remote"),
        "status": str(payload.get("status") or "open"),
        "headcount": int(payload.get("headcount") or 1),
        "createdAt": str(payload.get("createdAt") or datetime.now().isoformat()),
        "description": description,
    }
    (jobs_dir / f"{safe_filename(job_id)}.json").write_text(
        json.dumps(job, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return job


def list_resume_library() -> list[dict[str, Any]]:
    resumes: list[dict[str, Any]] = []
    seen: set[str] = set()
    for folder in [ROOT / "data" / "resumes", ROOT / "data" / "web_uploads", ROOT / "data" / "email_resumes"]:
        if not folder.exists():
            continue
        for path in sorted(folder.iterdir()):
            if not path.is_file() or str(path) in seen:
                continue
            seen.add(str(path))
            item: dict[str, Any] = {
                "name": path.name,
                "path": str(path),
                "size": path.stat().st_size,
                "updatedAt": datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
                "source": folder.name,
            }
            item.update(parse_uploaded_resume(path))
            resumes.append(item)
    return resumes


def list_outbox_items() -> list[dict[str, Any]]:
    outbox_dir = ROOT / "data" / "outbox"
    if not outbox_dir.exists():
        return []
    items: list[dict[str, Any]] = []
    for path in sorted(outbox_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            payload = {}
        items.append(
            {
                "name": path.name,
                "path": str(path),
                "category": payload.get("category", "unknown"),
                "recipient": payload.get("recipient", ""),
                "subject": payload.get("subject", ""),
                "updatedAt": datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
            }
        )
    return items


def save_interview_confirmation(payload: dict[str, Any]) -> dict[str, Any]:
    candidate = str(payload.get("candidateName") or "").strip()
    slot = payload.get("slot") or {}
    if not candidate:
        raise ValueError("候选人不能为空。")
    if not slot:
        raise ValueError("请选择面试时间。")
    target_dir = ROOT / "data" / "interviews"
    target_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "id": f"interview-{int(datetime.now().timestamp())}",
        "candidateName": candidate,
        "candidateEmail": payload.get("candidateEmail"),
        "jobTitle": payload.get("jobTitle") or "未指定职位",
        "slot": slot,
        "status": "confirmed",
        "createdAt": datetime.now().isoformat(),
    }
    target = target_dir / f"{safe_filename(record['id'] + '-' + candidate)}.json"
    target.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return record


def list_interview_confirmations() -> list[dict[str, Any]]:
    target_dir = ROOT / "data" / "interviews"
    if not target_dir.exists():
        return []
    records = []
    for path in sorted(target_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            records.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    return records


def fetch_email_resumes(payload: dict[str, Any]) -> dict[str, Any]:
    config = config_from_payload(payload)
    fetcher = InboxResumeFetcher(ROOT / "data" / "email_resumes")
    result = fetcher.fetch(config)

    parsed_files: list[dict[str, Any]] = []
    for message in result["imported"]:
        for file_info in message.get("files", []):
            path = Path(file_info["path"])
            enriched = dict(file_info)
            enriched.update(parse_uploaded_resume(path))
            enriched["message"] = {
                "messageId": message.get("messageId"),
                "from": message.get("from"),
                "subject": message.get("subject"),
                "date": message.get("date"),
            }
            parsed_files.append(enriched)

    return {
        "ok": True,
        "result": {
            "importedMessages": len(result["imported"]),
            "importedFiles": len(parsed_files),
            "skipped": result["skipped"],
            "files": parsed_files,
            "storageDir": result["storageDir"],
        },
    }


def run_recruitment(payload: dict[str, Any]) -> dict[str, Any]:
    job_description = str(payload.get("jobDescription") or "").strip()
    if not job_description:
        raise ValueError("岗位描述不能为空。")

    resume_paths = normalize_resume_paths(payload)
    if not resume_paths:
        raise ValueError("至少需要提供一个简历路径，或粘贴一份简历文本。")

    notification_channels = str(payload.get("notificationChannels") or "json")
    previous_channels = os.environ.get("NOTIFICATION_CHANNELS")
    os.environ["NOTIFICATION_CHANNELS"] = notification_channels

    try:
        workflow = build_workflow(interrupt_on_approval=False)
        result = workflow.invoke(
            {
                "job_description": job_description,
                "resume_paths": resume_paths,
                "threshold": 0 if payload.get("showAllCandidates", True) else float(payload.get("threshold") or 70),
                "timezone": str(payload.get("timezone") or "Asia/Shanghai"),
                "outbox_dir": str(ROOT / "data" / "outbox"),
                "approval_status": str(payload.get("approvalStatus") or "pending"),
                "approved_by": str(payload.get("approvedBy") or "HR reviewer"),
                "approval_notes": str(payload.get("approvalNotes") or ""),
            }
        )
    finally:
        if previous_channels is None:
            os.environ.pop("NOTIFICATION_CHANNELS", None)
        else:
            os.environ["NOTIFICATION_CHANNELS"] = previous_channels

    return compact_result(to_jsonable(result))


def normalize_resume_paths(payload: dict[str, Any]) -> list[str]:
    raw_paths = payload.get("resumePaths") or []
    if isinstance(raw_paths, str):
        paths = [item.strip() for item in raw_paths.splitlines() if item.strip()]
    else:
        paths = [str(item).strip() for item in raw_paths if str(item).strip()]

    pasted_resume = str(payload.get("pastedResume") or "").strip()
    if pasted_resume:
        upload_dir = ROOT / "data" / "web_uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)
        target = unique_path(upload_dir / "pasted_resume.txt")
        target.write_text(pasted_resume, encoding="utf-8")
        paths.append(str(target))

    return paths


def safe_upload_name(filename: str) -> str:
    original = Path(filename).name
    stem = Path(original).stem or "resume"
    suffix = Path(original).suffix.lower()
    safe_stem = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in stem)[:80]
    safe_suffix = suffix if suffix in {".txt", ".md", ".pdf", ".doc", ".docx", ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff"} else ".txt"
    return f"{safe_stem}{safe_suffix}"


def safe_filename(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value)[:96] or "item"


def slugify(value: str) -> str:
    return safe_filename(value.lower().replace(" ", "-")).strip("-_")


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    for index in range(1, 1000):
        candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise ValueError("Too many uploaded files with the same name.")


def parse_uploaded_resume(path: Path) -> dict[str, Any]:
    try:
        profile = ResumeParser().parse(path)
    except Exception as exc:
        return {
            "parseStatus": "failed",
            "parseError": str(exc),
        }

    return {
        "parseStatus": "parsed",
        "profile": {
            "name": profile.name,
            "email": profile.email,
            "phone": profile.phone,
            "skills": profile.skills,
            "yearsExperience": profile.years_experience,
            "education": profile.education,
            "latestCompany": profile.latest_company,
            "sourcePath": profile.source_path,
        },
    }


def compact_result(result: dict[str, Any]) -> dict[str, Any]:
    delivery_results = result.get("delivery_results", [])
    delivery_stats: dict[str, int] = {}
    for item in delivery_results:
        key = f"{item.get('channel')}:{item.get('status')}"
        delivery_stats[key] = delivery_stats.get(key, 0) + 1

    return {
        "intent": result.get("intent"),
        "candidateProfiles": result.get("candidate_profiles", []),
        "candidateMatches": result.get("candidate_matches", []),
        "schedules": result.get("schedule_recommendations", []),
        "technicalEvaluations": result.get("technical_evaluations", []),
        "notifications": result.get("notifications", []),
        "deliveryResults": delivery_results,
        "deliveryStats": delivery_stats,
        "events": result.get("events", []),
        "approvalDecision": result.get("approval_decision"),
        "outboxDir": str(ROOT / "data" / "outbox"),
    }


def to_jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {key: to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(item) for item in value]
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the recruitment web console.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    server = ThreadingHTTPServer((args.host, args.port), RecruitmentWebHandler)
    url = f"http://{args.host}:{args.port}"
    print(f"Recruitment web console is running at {url}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")


if __name__ == "__main__":
    main()
