from __future__ import annotations

import email
import imaplib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from email.header import decode_header
from email.message import Message
from pathlib import Path
from typing import Any


RESUME_SUFFIXES = {".pdf", ".doc", ".docx", ".txt", ".md", ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff"}

IMAP_PRESETS = {
    "outlook": {"host": "imap-mail.outlook.com", "port": 993, "ssl": True},
    "qq": {"host": "imap.qq.com", "port": 993, "ssl": True},
    "163": {"host": "imap.163.com", "port": 993, "ssl": True},
    "gmail": {"host": "imap.gmail.com", "port": 993, "ssl": True},
}


@dataclass
class InboxConfig:
    host: str
    username: str
    password: str
    port: int = 993
    folder: str = "INBOX"
    use_ssl: bool = True
    search: str = "UNSEEN"
    max_messages: int = 20
    mark_seen: bool = False


class InboxResumeFetcher:
    def __init__(self, storage_dir: Path, state_file: Path | None = None) -> None:
        self.storage_dir = storage_dir
        self.state_file = state_file or storage_dir / "_seen_messages.json"

    def fetch(self, config: InboxConfig) -> dict[str, Any]:
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        seen = self._load_seen()
        imported: list[dict[str, Any]] = []
        skipped: list[dict[str, str]] = []

        mailbox = self._connect(config)
        try:
            mailbox.select(config.folder)
            status, data = mailbox.search(None, config.search)
            if status != "OK":
                raise RuntimeError(f"IMAP search failed: {status}")

            message_ids = data[0].split()[-config.max_messages :]
            for message_id in message_ids:
                status, payload = mailbox.fetch(message_id, "(RFC822)")
                if status != "OK" or not payload or not isinstance(payload[0], tuple):
                    skipped.append({"messageId": message_id.decode("utf-8", errors="ignore"), "reason": "fetch failed"})
                    continue

                message = email.message_from_bytes(payload[0][1])
                fingerprint = self._fingerprint(message, message_id)
                if fingerprint in seen:
                    skipped.append({"messageId": fingerprint, "reason": "already imported"})
                    continue

                files = self._extract_message_files(message, fingerprint)
                if not files:
                    body_file = self._save_body_as_resume(message, fingerprint)
                    if body_file:
                        files.append(body_file)

                if files:
                    seen.add(fingerprint)
                    imported.append(
                        {
                            "messageId": fingerprint,
                            "from": decode_mime_text(message.get("From", "")),
                            "subject": decode_mime_text(message.get("Subject", "")),
                            "date": message.get("Date", ""),
                            "files": files,
                        }
                    )
                    if config.mark_seen:
                        mailbox.store(message_id, "+FLAGS", "\\Seen")
                else:
                    skipped.append({"messageId": fingerprint, "reason": "no resume attachment or resume-like body"})
        finally:
            try:
                mailbox.logout()
            except Exception:
                pass

        self._save_seen(seen)
        return {
            "imported": imported,
            "skipped": skipped,
            "storageDir": str(self.storage_dir),
        }

    def _connect(self, config: InboxConfig):
        if config.use_ssl:
            mailbox = imaplib.IMAP4_SSL(config.host, config.port)
        else:
            mailbox = imaplib.IMAP4(config.host, config.port)
        mailbox.login(config.username, config.password)
        return mailbox

    def _extract_message_files(self, message: Message, fingerprint: str) -> list[dict[str, Any]]:
        files = []
        for part in message.walk():
            if part.get_content_maintype() == "multipart":
                continue
            filename = part.get_filename()
            if not filename:
                continue
            filename = decode_mime_text(filename)
            suffix = Path(filename).suffix.lower()
            if suffix not in RESUME_SUFFIXES:
                continue
            payload = part.get_payload(decode=True)
            if not payload:
                continue
            target = unique_path(self.storage_dir / safe_file_name(f"{fingerprint}_{filename}"))
            target.write_bytes(payload)
            files.append(file_payload(target, source="email_attachment"))
        return files

    def _save_body_as_resume(self, message: Message, fingerprint: str) -> dict[str, Any] | None:
        body = extract_text_body(message).strip()
        if not looks_like_resume(body):
            return None
        target = unique_path(self.storage_dir / safe_file_name(f"{fingerprint}_email_body.txt"))
        target.write_text(body, encoding="utf-8")
        return file_payload(target, source="email_body")

    def _fingerprint(self, message: Message, message_id: bytes) -> str:
        raw = message.get("Message-ID") or message.get("Message-Id")
        if raw:
            return safe_token(raw)
        return safe_token(message_id.decode("utf-8", errors="ignore"))

    def _load_seen(self) -> set[str]:
        if not self.state_file.exists():
            return set()
        try:
            return set(json.loads(self.state_file.read_text(encoding="utf-8")))
        except Exception:
            return set()

    def _save_seen(self, seen: set[str]) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(sorted(seen), ensure_ascii=False, indent=2), encoding="utf-8")


def config_from_payload(payload: dict[str, Any]) -> InboxConfig:
    provider = str(payload.get("provider") or os.getenv("IMAP_PROVIDER", "")).lower()
    preset = IMAP_PRESETS.get(provider, {})
    host = str(payload.get("host") or os.getenv("IMAP_HOST") or preset.get("host") or "").strip()
    username = str(payload.get("username") or os.getenv("IMAP_USERNAME") or "").strip()
    password = str(payload.get("password") or os.getenv("IMAP_PASSWORD") or "").strip()
    if not host:
        raise ValueError("请配置 IMAP_HOST，或选择 outlook / qq / 163 / gmail 预设。")
    if not username:
        raise ValueError("请配置 IMAP_USERNAME。")
    if not password:
        raise ValueError("请配置 IMAP_PASSWORD。邮箱通常需要填写授权码，不是登录密码。")
    return InboxConfig(
        host=host,
        username=username,
        password=password,
        port=int(payload.get("port") or os.getenv("IMAP_PORT") or preset.get("port") or 993),
        folder=str(payload.get("folder") or os.getenv("IMAP_FOLDER") or "INBOX"),
        use_ssl=parse_bool(payload.get("useSsl", os.getenv("IMAP_SSL", preset.get("ssl", True)))),
        search=str(payload.get("search") or os.getenv("IMAP_SEARCH") or "UNSEEN"),
        max_messages=int(payload.get("maxMessages") or os.getenv("IMAP_MAX_MESSAGES") or 20),
        mark_seen=parse_bool(payload.get("markSeen", os.getenv("IMAP_MARK_SEEN", "false"))),
    )


def decode_mime_text(value: str) -> str:
    pieces = []
    for content, charset in decode_header(value):
        if isinstance(content, bytes):
            pieces.append(content.decode(charset or "utf-8", errors="ignore"))
        else:
            pieces.append(content)
    return "".join(pieces).strip()


def extract_text_body(message: Message) -> str:
    parts = []
    for part in message.walk():
        if part.get_content_maintype() == "multipart":
            continue
        if part.get_content_disposition() == "attachment":
            continue
        content_type = part.get_content_type()
        if content_type not in {"text/plain", "text/html"}:
            continue
        payload = part.get_payload(decode=True)
        if not payload:
            continue
        charset = part.get_content_charset() or "utf-8"
        text = payload.decode(charset, errors="ignore")
        if content_type == "text/html":
            text = re.sub(r"<[^>]+>", " ", text)
        parts.append(text)
    return "\n".join(parts)


def looks_like_resume(text: str) -> bool:
    if len(text) < 80:
        return False
    lowered = text.lower()
    signals = ["简历", "求职", "应聘", "工作经验", "项目经验", "教育经历", "resume", "experience", "education"]
    return sum(1 for signal in signals if signal in lowered) >= 2


def parse_bool(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def safe_token(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() else "_" for ch in value)
    cleaned = cleaned.strip("_")
    return cleaned[:72] or f"message_{int(datetime.now().timestamp())}"


def safe_file_name(value: str) -> str:
    name = Path(value).name
    stem = Path(name).stem
    suffix = Path(name).suffix.lower()
    safe_stem = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in stem)[:96] or "resume"
    safe_suffix = suffix if suffix in RESUME_SUFFIXES else ".txt"
    return f"{safe_stem}{safe_suffix}"


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    for index in range(1, 1000):
        candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError("Too many duplicate email resume files.")


def file_payload(path: Path, source: str) -> dict[str, Any]:
    return {
        "name": path.name,
        "path": str(path),
        "size": path.stat().st_size,
        "updatedAt": datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
        "source": source,
    }
