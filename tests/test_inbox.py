from __future__ import annotations

import tempfile
import sys
import unittest
from email.message import EmailMessage
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from recruitment_agents.tools.inbox import InboxResumeFetcher, looks_like_resume


class InboxResumeFetcherTest(unittest.TestCase):
    def test_extracts_resume_attachment(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            message = EmailMessage()
            message["From"] = "candidate@example.com"
            message["Subject"] = "应聘 AI Engineer - 简历"
            message["Message-ID"] = "<candidate-001@example.com>"
            message.set_content("您好，附件是我的简历。")
            message.add_attachment(
                "姓名：候选人\n邮箱：candidate@example.com\n3 年 Python 项目经验".encode("utf-8"),
                maintype="application",
                subtype="pdf",
                filename="candidate_resume.pdf",
            )

            fetcher = InboxResumeFetcher(Path(temp))
            files = fetcher._extract_message_files(message, "candidate_001")

            self.assertEqual(len(files), 1)
            self.assertTrue(Path(files[0]["path"]).exists())
            self.assertEqual(files[0]["source"], "email_attachment")

    def test_detects_resume_like_body(self) -> None:
        body = (
            "个人简历\n应聘 Python 工程师\n工作经验：3 年，负责 FastAPI 与 LangGraph Agent 项目。"
            "项目经验：参与招聘 Agent、简历解析和邮件触达系统建设。教育经历：本科，计算机科学。"
        )
        self.assertTrue(looks_like_resume(body))


if __name__ == "__main__":
    unittest.main()
