"""
Skill API performance scenario.

Exercises skill CRUD operations and role-based skill queries
with randomized IDs to avoid conflicts across concurrent users.
"""

from uuid import uuid4

from locust import HttpUser, between, tag, task

from src.tests.performance.config import API_PREFIX


class SkillAPIUser(HttpUser):
    """Simulates skill management traffic."""

    wait_time = between(0.5, 1.5)

    @task(3)
    @tag("skill", "crud")
    def skills_crud(self):
        suffix = uuid4().hex[:8]
        skill_id = f"SKILL-PERF-{suffix}"

        self.client.post(
            f"{API_PREFIX}/skills",
            json={
                "skill_id": skill_id,
                "name": "性能测试技能",
                "description": "测试技能",
                "owner": "admin",
                "steps": [],
                "intent_keywords": ["test"],
                "required_roles": [],
                "risk_level": "low",
            },
            name="/skills [POST]",
        )

        self.client.get(
            f"{API_PREFIX}/skills",
            name="/skills [GET list]",
        )

        self.client.get(
            f"{API_PREFIX}/skills/{skill_id}",
            name="/skills [GET single]",
        )

        self.client.delete(
            f"{API_PREFIX}/skills/{skill_id}",
            name="/skills [DELETE]",
        )

    @task(2)
    @tag("skill", "readonly")
    def by_role(self):
        self.client.get(
            f"{API_PREFIX}/skills/by-role/billing_staff",
            name="/skills/by-role",
        )
