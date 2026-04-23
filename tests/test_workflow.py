from __future__ import annotations

from pathlib import Path
import os
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from recruitment_agents.workflow import build_workflow
from recruitment_agents.agents import approval_decision_from_resume, checkpointed_approval_agent
from recruitment_agents.models import ApprovalDecision, EmailNotification
from recruitment_agents.tools.email import parse_channels, parse_feishu_error
from recruitment_agents.tools.email import NotificationCenter


class WorkflowTest(unittest.TestCase):
    def test_recruitment_workflow_runs(self) -> None:
        workflow = build_workflow()
        result = workflow.invoke(
            {
                "job_description": (ROOT / "data" / "sample_job.txt").read_text(encoding="utf-8"),
                "resume_paths": [str(ROOT / "data" / "resumes")],
                "threshold": 70,
                "timezone": "Asia/Shanghai",
                "outbox_dir": str(ROOT / "data" / "outbox"),
            }
        )

        self.assertTrue(result["candidate_matches"])
        self.assertEqual(result["candidate_matches"][0].candidate.name, "陈 Alice")
        self.assertTrue(result["schedule_recommendations"])
        self.assertTrue(result["technical_evaluations"])
        self.assertTrue(result["notifications"])
        self.assertEqual(result["approval_decision"].status, "pending")
        self.assertTrue(result["delivery_results"])
        self.assertEqual(result["delivery_results"][0].channel, "json")
        self.assertTrue(result["events"])

    def test_notification_helpers(self) -> None:
        self.assertEqual(parse_channels("json,sendgrid,unknown"), {"json", "sendgrid"})
        self.assertIsNone(parse_feishu_error('{"StatusCode":0,"StatusMessage":"success"}'))
        self.assertIn("19024", parse_feishu_error('{"code":19024,"msg":"Key Words Not Found"}') or "")
        decision = approval_decision_from_resume({"status": "approved", "approved_by": "HR"})
        self.assertEqual(decision.status, "approved")
        self.assertEqual(decision.approved_by, "HR")

    def test_candidate_notifications_wait_for_approval_on_real_channels(self) -> None:
        previous = os.environ.get("NOTIFICATION_CHANNELS")
        os.environ["NOTIFICATION_CHANNELS"] = "smtp"
        try:
            center = NotificationCenter()
            notifications = [
                EmailNotification(
                    category="interview_invite",
                    recipient="candidate@example.com",
                    subject="Interview",
                    body="Please choose a time.",
                ),
                EmailNotification(
                    category="hr_digest",
                    recipient="hr@example.com",
                    subject="Digest",
                    body="Summary",
                ),
            ]
            results = center.deliver_notifications(
                notifications=notifications,
                outbox_dir=None,
                approval_decision=ApprovalDecision(status="pending"),
            )
        finally:
            if previous is None:
                os.environ.pop("NOTIFICATION_CHANNELS", None)
            else:
                os.environ["NOTIFICATION_CHANNELS"] = previous

        self.assertEqual(results[0].status, "skipped")
        self.assertIn("HR approval", results[0].detail)
        self.assertEqual(results[1].status, "skipped")
        self.assertIn("SMTP_HOST", results[1].detail)

    def test_candidate_notifications_send_after_approval(self) -> None:
        class DummyTransport:
            channel = "smtp"

            def send(self, notification: EmailNotification):
                from recruitment_agents.models import DeliveryResult

                return DeliveryResult(
                    channel="smtp",
                    recipient=notification.recipient,
                    category=notification.category,
                    status="sent",
                    detail="dummy send",
                )

        center = NotificationCenter()
        center._build_transports = lambda outbox_dir: [DummyTransport()]  # type: ignore[method-assign]
        notification = EmailNotification(
            category="interview_invite",
            recipient="candidate@example.com",
            subject="Interview",
            body="Please choose a time.",
        )

        pending = center.deliver_notifications([notification], None, ApprovalDecision(status="pending"))
        approved = center.deliver_notifications([notification], None, ApprovalDecision(status="approved"))

        self.assertEqual(pending[0].status, "skipped")
        self.assertEqual(approved[0].status, "sent")

    def test_checkpointed_approval_agent_accepts_resume_payload(self) -> None:
        previous_langgraph = sys.modules.get("langgraph")
        previous_types = sys.modules.get("langgraph.types")
        fake_langgraph = types.ModuleType("langgraph")
        fake_types = types.ModuleType("langgraph.types")
        fake_types.interrupt = lambda payload: {"status": "approved", "approved_by": "HR"}
        sys.modules["langgraph"] = fake_langgraph
        sys.modules["langgraph.types"] = fake_types
        try:
            update = checkpointed_approval_agent({"candidate_matches": []})
        finally:
            if previous_langgraph is None:
                sys.modules.pop("langgraph", None)
            else:
                sys.modules["langgraph"] = previous_langgraph
            if previous_types is None:
                sys.modules.pop("langgraph.types", None)
            else:
                sys.modules["langgraph.types"] = previous_types

        self.assertEqual(update["approval_decision"].status, "approved")
        self.assertEqual(update["approval_decision"].approved_by, "HR")


if __name__ == "__main__":
    unittest.main()
