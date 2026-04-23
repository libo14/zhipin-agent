from __future__ import annotations

import json
import os
import smtplib
import ssl
import urllib.error
import urllib.request
from email.message import EmailMessage
from pathlib import Path
from typing import Protocol

from recruitment_agents.models import (
    ApprovalDecision,
    CandidateMatch,
    DeliveryResult,
    EmailNotification,
    InterviewRecommendation,
    TechnicalEvaluation,
)


CANDIDATE_NOTIFICATION_CATEGORIES = {
    "resume_received",
    "shortlisted",
    "interview_invite",
    "rejection",
}


class NotificationTransport(Protocol):
    channel: str

    def send(self, notification: EmailNotification) -> DeliveryResult:
        ...


class JsonOutboxTransport:
    channel = "json"

    def __init__(self, outbox_dir: str) -> None:
        self.outbox_dir = Path(outbox_dir)
        self._counter = 0

    def send(self, notification: EmailNotification) -> DeliveryResult:
        self.outbox_dir.mkdir(parents=True, exist_ok=True)
        self._counter += 1
        filename = f"{self._counter:02d}_{notification.category}_{safe_name(notification.recipient)}.json"
        target = self.outbox_dir / filename
        target.write_text(
            json.dumps(notification.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return DeliveryResult(
            channel="json",
            recipient=notification.recipient,
            category=notification.category,
            status="drafted",
            detail=str(target),
        )


class SmtpTransport:
    channel = "smtp"

    def __init__(
        self,
        host: str,
        port: int,
        username: str | None,
        password: str | None,
        from_email: str,
        use_tls: bool = True,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.from_email = from_email
        self.use_tls = use_tls

    def send(self, notification: EmailNotification) -> DeliveryResult:
        if not self.host or not self.from_email:
            return self._skipped(notification, "SMTP_HOST and SMTP_FROM_EMAIL are required.")

        message = EmailMessage()
        message["From"] = self.from_email
        message["To"] = notification.recipient
        message["Subject"] = notification.subject
        message.set_content(notification.body)

        try:
            if self.use_tls:
                context = ssl.create_default_context()
                with smtplib.SMTP(self.host, self.port, timeout=15) as server:
                    server.starttls(context=context)
                    self._login(server)
                    server.send_message(message)
            else:
                with smtplib.SMTP_SSL(self.host, self.port, timeout=15) as server:
                    self._login(server)
                    server.send_message(message)
        except Exception as exc:  # pragma: no cover - depends on external SMTP.
            return self._failed(notification, str(exc))

        return DeliveryResult(
            channel="smtp",
            recipient=notification.recipient,
            category=notification.category,
            status="sent",
            detail=f"Sent via SMTP {self.host}:{self.port}.",
        )

    def _login(self, server: smtplib.SMTP) -> None:
        if self.username and self.password:
            server.login(self.username, self.password)

    def _skipped(self, notification: EmailNotification, detail: str) -> DeliveryResult:
        return DeliveryResult(channel="smtp", recipient=notification.recipient, category=notification.category, status="skipped", detail=detail)

    def _failed(self, notification: EmailNotification, detail: str) -> DeliveryResult:
        return DeliveryResult(channel="smtp", recipient=notification.recipient, category=notification.category, status="failed", detail=detail)


class SendGridTransport:
    channel = "sendgrid"

    def __init__(self, api_key: str | None, from_email: str, base_url: str) -> None:
        self.api_key = api_key
        self.from_email = from_email
        self.base_url = base_url.rstrip("/")

    def send(self, notification: EmailNotification) -> DeliveryResult:
        if not self.api_key or not self.from_email:
            return self._result(notification, "skipped", "SENDGRID_API_KEY and SENDGRID_FROM_EMAIL are required.")

        payload = {
            "personalizations": [{"to": [{"email": notification.recipient}], "subject": notification.subject}],
            "from": {"email": self.from_email},
            "content": [{"type": "text/plain", "value": notification.body}],
        }
        request = urllib.request.Request(
            url=f"{self.base_url}/v3/mail/send",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                status_code = response.getcode()
        except urllib.error.HTTPError as exc:  # pragma: no cover - external API.
            detail = exc.read().decode("utf-8", errors="ignore") or str(exc)
            return self._result(notification, "failed", detail)
        except Exception as exc:  # pragma: no cover - external API.
            return self._result(notification, "failed", str(exc))

        if 200 <= status_code < 300:
            return self._result(notification, "sent", f"SendGrid accepted message with HTTP {status_code}.")
        return self._result(notification, "failed", f"SendGrid returned HTTP {status_code}.")

    def _result(self, notification: EmailNotification, status: str, detail: str) -> DeliveryResult:
        return DeliveryResult(channel="sendgrid", recipient=notification.recipient, category=notification.category, status=status, detail=detail)


class FeishuWebhookTransport:
    channel = "feishu"

    def __init__(self, webhook_url: str | None) -> None:
        self.webhook_url = webhook_url

    def send(self, notification: EmailNotification) -> DeliveryResult:
        if not self.webhook_url:
            return self._result(notification, "skipped", "FEISHU_WEBHOOK_URL is required.")

        text = f"[{notification.category}] {notification.subject}\nRecipient: {notification.recipient}\n\n{notification.body}"
        payload = {"msg_type": "text", "content": {"text": text}}
        request = urllib.request.Request(
            url=self.webhook_url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                status_code = response.getcode()
                response_body = response.read().decode("utf-8", errors="ignore")
        except urllib.error.HTTPError as exc:  # pragma: no cover - external webhook.
            detail = exc.read().decode("utf-8", errors="ignore") or str(exc)
            return self._result(notification, "failed", detail)
        except Exception as exc:  # pragma: no cover - external webhook.
            return self._result(notification, "failed", str(exc))

        if 200 <= status_code < 300:
            api_error = parse_feishu_error(response_body)
            if api_error:
                return self._result(notification, "failed", api_error)
            return self._result(notification, "sent", response_body or f"Feishu HTTP {status_code}.")
        return self._result(notification, "failed", f"Feishu returned HTTP {status_code}: {response_body}")

    def _result(self, notification: EmailNotification, status: str, detail: str) -> DeliveryResult:
        return DeliveryResult(channel="feishu", recipient=notification.recipient, category=notification.category, status=status, detail=detail[:500])


class NotificationCenter:
    def build_notifications(
        self,
        matches: list[CandidateMatch],
        schedules: list[InterviewRecommendation],
        technical_reports: list[TechnicalEvaluation],
    ) -> list[EmailNotification]:
        notifications: list[EmailNotification] = []
        schedule_by_candidate = {item.candidate_name: item for item in schedules}
        tech_by_candidate = {item.candidate_name: item for item in technical_reports}

        for match in matches:
            candidate = match.candidate
            recipient = candidate.email or "candidate@example.com"
            notifications.append(
                EmailNotification(
                    category="resume_received",
                    recipient=recipient,
                    subject=f"已收到你的简历 - {candidate.name}",
                    body=f"{candidate.name} 你好，我们已经收到你的简历，正在进行岗位匹配评估。",
                )
            )

            if match.recommendation == "reject":
                notifications.append(
                    EmailNotification(
                        category="rejection",
                        recipient=recipient,
                        subject="招聘流程更新",
                        body=(
                            f"{candidate.name} 你好，感谢你的投递。经过评估，本次岗位与当前经历匹配度暂未达到面试标准，"
                            "我们会保留你的资料用于后续合适机会。"
                        ),
                    )
                )
                continue

            notifications.append(
                EmailNotification(
                    category="shortlisted",
                    recipient=recipient,
                    subject="你已进入下一轮招聘流程",
                    body=f"{candidate.name} 你好，你的综合匹配得分为 {match.score.weighted_total}，已进入面试排期阶段。",
                )
            )

            schedule = schedule_by_candidate.get(candidate.name)
            if schedule:
                slot_lines = [
                    f"- {slot.starts_at.strftime('%Y-%m-%d %H:%M')} - {slot.ends_at.strftime('%H:%M')} {slot.timezone}"
                    for slot in schedule.slots
                ]
                notifications.append(
                    EmailNotification(
                        category="interview_invite",
                        recipient=recipient,
                        subject="面试时间确认",
                        body=f"{candidate.name} 你好，推荐面试时段如下：\n" + "\n".join(slot_lines),
                    )
                )

            tech = tech_by_candidate.get(candidate.name)
            if tech:
                notifications.append(
                    EmailNotification(
                        category="technical_brief",
                        recipient="interviewer@example.com",
                        subject=f"技术面试 Brief - {candidate.name}",
                        body=tech.interviewer_brief,
                    )
                )

        notifications.append(self._build_hr_digest(matches, schedules))
        return notifications

    def deliver_notifications(
        self,
        notifications: list[EmailNotification],
        outbox_dir: str | None,
        approval_decision: ApprovalDecision | None = None,
    ) -> list[DeliveryResult]:
        transports = self._build_transports(outbox_dir)
        results: list[DeliveryResult] = []
        for transport in transports:
            for notification in notifications:
                if self._should_skip_for_approval(transport, notification, approval_decision):
                    results.append(
                        DeliveryResult(
                            channel=transport.channel,
                            recipient=notification.recipient,
                            category=notification.category,
                            status="skipped",
                            detail="Candidate-facing notification is waiting for HR approval.",
                        )
                    )
                    continue
                results.append(transport.send(notification))
        return results

    def write_outbox(self, notifications: list[EmailNotification], outbox_dir: str) -> None:
        transport = JsonOutboxTransport(outbox_dir)
        for notification in notifications:
            transport.send(notification)

    def _should_skip_for_approval(
        self,
        transport: NotificationTransport,
        notification: EmailNotification,
        approval_decision: ApprovalDecision | None,
    ) -> bool:
        if transport.channel == "json":
            return False
        if notification.category not in CANDIDATE_NOTIFICATION_CATEGORIES:
            return False
        return approval_decision is None or approval_decision.status != "approved"

    def _build_transports(self, outbox_dir: str | None) -> list[NotificationTransport]:
        channel_names = parse_channels(os.getenv("NOTIFICATION_CHANNELS", "json"))
        transports: list[NotificationTransport] = []

        if outbox_dir:
            transports.append(JsonOutboxTransport(outbox_dir))
        if "smtp" in channel_names:
            transports.append(
                SmtpTransport(
                    host=os.getenv("SMTP_HOST", ""),
                    port=int(os.getenv("SMTP_PORT", "587")),
                    username=os.getenv("SMTP_USERNAME"),
                    password=os.getenv("SMTP_PASSWORD"),
                    from_email=os.getenv("SMTP_FROM_EMAIL", ""),
                    use_tls=os.getenv("SMTP_USE_TLS", "true").lower() != "false",
                )
            )
        if "sendgrid" in channel_names:
            transports.append(
                SendGridTransport(
                    api_key=os.getenv("SENDGRID_API_KEY"),
                    from_email=os.getenv("SENDGRID_FROM_EMAIL", ""),
                    base_url=os.getenv("SENDGRID_BASE_URL", "https://api.sendgrid.com"),
                )
            )
        if "feishu" in channel_names:
            transports.append(FeishuWebhookTransport(os.getenv("FEISHU_WEBHOOK_URL")))

        return transports

    def _build_hr_digest(self, matches: list[CandidateMatch], schedules: list[InterviewRecommendation]) -> EmailNotification:
        lines = ["本轮招聘自动化流程已完成："]
        for match in matches:
            lines.append(
                f"- {match.candidate.name}: {match.recommendation}, "
                f"score={match.score.weighted_total}, missing={','.join(match.score.missing_skills) or '无'}"
            )
        lines.append(f"已生成 {len(schedules)} 组面试推荐时段。")
        return EmailNotification(
            category="hr_digest",
            recipient="hr@example.com",
            subject="招聘 Agent 工作流摘要",
            body="\n".join(lines),
        )


def parse_channels(value: str) -> set[str]:
    allowed = {"json", "smtp", "sendgrid", "feishu"}
    channels = {item.strip().lower() for item in value.split(",") if item.strip()}
    return channels & allowed or {"json"}


def parse_feishu_error(response_body: str) -> str | None:
    if not response_body:
        return None
    try:
        payload = json.loads(response_body)
    except json.JSONDecodeError:
        return None

    code = payload.get("code", payload.get("StatusCode", 0))
    if code in (0, "0", None):
        return None
    message = payload.get("msg") or payload.get("StatusMessage") or response_body
    return f"Feishu business error {code}: {message}"


def safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in value)[:48]
