from __future__ import annotations

import sys
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi_app import create_app


class FastAPIAppTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(create_app())

    def test_sample_endpoint_matches_existing_shape(self) -> None:
        response = self.client.get("/api/sample")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("jobDescription", payload)
        self.assertIn("resumePaths", payload)
        self.assertEqual(payload["timezone"], "Asia/Shanghai")

    def test_workbench_endpoint_wraps_data(self) -> None:
        response = self.client.get("/api/workbench")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertIn("data", payload)
        self.assertIn("jobs", payload["data"])
        self.assertIn("resumes", payload["data"])

    def test_run_endpoint_keeps_error_payload_shape(self) -> None:
        response = self.client.post("/api/run", json={})

        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertFalse(payload["ok"])
        self.assertIn("岗位描述", payload["error"])


if __name__ == "__main__":
    unittest.main()
