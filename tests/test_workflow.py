from __future__ import annotations

from pathlib import Path
import os
import sys
import tempfile
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from recruitment_agents.workflow import build_workflow
from recruitment_agents.agents import (
    CommunicationAgent,
    IntentSearchAgent,
    ResumeScreeningAgent,
    SchedulingAgent,
    TechnicalEvaluationAgent,
    approval_agent,
    approval_decision_from_resume,
    checkpointed_approval_agent,
    intent_search_agent,
    resume_screening_agent,
)
from recruitment_agents.llm import MockChatModel
from recruitment_agents.models import ApprovalDecision, EmailNotification
from recruitment_agents.parsers import ResumeParser
from recruitment_agents.tools.calendar import CalendarScheduler
from recruitment_agents.tools.email import parse_channels, parse_feishu_error
from recruitment_agents.tools.email import NotificationCenter


class WorkflowTest(unittest.TestCase):
    def test_recruitment_workflow_runs(self) -> None:
        workflow = build_workflow(interrupt_on_approval=False)
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

    def test_five_agent_classes_run_independently(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            state = {
                "job_description": (ROOT / "data" / "sample_job.txt").read_text(encoding="utf-8"),
                "resume_paths": [str(ROOT / "data" / "resumes")],
                "threshold": 70,
                "timezone": "Asia/Shanghai",
                "outbox_dir": temp,
            }
            agents = [
                IntentSearchAgent(MockChatModel()),
                ResumeScreeningAgent(ResumeParser()),
                SchedulingAgent(CalendarScheduler()),
                TechnicalEvaluationAgent(MockChatModel()),
                CommunicationAgent(NotificationCenter()),
            ]

            for agent in agents:
                self.assertTrue(agent.name)
                self.assertTrue(agent.role)
                self.assertTrue(agent.description)
                update = agent.run(state)
                state.update(update)
                self.assertTrue(update["events"])
                self.assertEqual(update["events"][0].node, agent.name)
                self.assertIn("Reason:", update["events"][0].message)
                self.assertIn("Action:", update["events"][0].message)
                self.assertIn("Tool:", update["events"][0].message)
                self.assertIn("Observation:", update["events"][0].message)

            self.assertEqual(len(agents), 5)
            self.assertTrue(state["intent"].required_skills)
            self.assertTrue(state["candidate_matches"])
            self.assertTrue(state["schedule_recommendations"])
            self.assertTrue(state["technical_evaluations"])
            self.assertTrue(state["notifications"])
            self.assertTrue(state["delivery_results"])

    def test_function_wrappers_match_agent_class_outputs(self) -> None:
        llm = MockChatModel()
        parser = ResumeParser()
        state = {
            "job_description": (ROOT / "data" / "sample_job.txt").read_text(encoding="utf-8"),
            "resume_paths": [str(ROOT / "data" / "resumes")],
            "threshold": 70,
        }

        class_update = IntentSearchAgent(llm).run(state)
        wrapper_update = intent_search_agent(state, llm)
        self.assertEqual(class_update["intent"], wrapper_update["intent"])
        self.assertEqual(class_update["events"][0].node, wrapper_update["events"][0].node)

        screening_state = dict(state, intent=class_update["intent"])
        class_screening = ResumeScreeningAgent(parser).run(screening_state)
        wrapper_screening = resume_screening_agent(screening_state, parser)
        self.assertEqual(
            [item.candidate.name for item in class_screening["candidate_matches"]],
            [item.candidate.name for item in wrapper_screening["candidate_matches"]],
        )
        self.assertEqual(class_screening["events"][0].node, wrapper_screening["events"][0].node)

    def test_hr_approval_gate_stays_outside_five_core_agents(self) -> None:
        update = approval_agent({"approval_status": "approved", "approved_by": "HR"})

        self.assertEqual(update["approval_decision"].status, "approved")
        self.assertEqual(update["events"][0].node, "approval_agent")

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
