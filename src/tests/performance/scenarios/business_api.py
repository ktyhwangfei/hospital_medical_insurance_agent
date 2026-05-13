"""
Business API performance scenario.

Simulates billing staff and doctor users interacting with the core
business endpoints: chat, chat/stream, patient-context, workflows, and version.
"""

from locust import HttpUser, between, tag, task

from src.tests.performance.config import API_PREFIX


class BusinessAPIUser(HttpUser):
    """Simulates business-facing user traffic patterns."""

    wait_time = between(1, 3)

    @task(5)
    @tag("business", "chat")
    def chat(self):
        self.client.post(
            f"{API_PREFIX}/chat",
            json={
                "user_id": "billing_staff_001",
                "role": "billing_staff",
                "message": "P001 患者结算异常 5月门诊被拒付",
                "patient_id": "P001",
                "encounter_id": "E001",
                "mentioned_skill_ids": [],
            },
            name="/chat",
        )

    @task(3)
    @tag("business", "stream")
    def chat_stream(self):
        with self.client.post(
            f"{API_PREFIX}/chat/stream",
            json={
                "user_id": "doctor_001",
                "role": "doctor",
                "message": "查询质控结果",
                "mentioned_skill_ids": [],
            },
            catch_response=True,
            stream=True,
            name="/chat/stream",
        ) as response:
            for _ in response.iter_lines():
                pass

    @task(2)
    @tag("business", "readonly")
    def get_patient_context(self):
        self.client.get(
            f"{API_PREFIX}/patient-context/P001/E001?user_id=doctor_001&role=doctor",
            name="/patient-context",
        )

    @task(2)
    @tag("business", "readonly")
    def get_workflows(self):
        self.client.get(
            f"{API_PREFIX}/workflows?scenario=settlement_exception",
            name="/workflows",
        )

    @task(1)
    @tag("business", "readonly")
    def get_version(self):
        self.client.get(
            f"{API_PREFIX}/version",
            name="/version",
        )
