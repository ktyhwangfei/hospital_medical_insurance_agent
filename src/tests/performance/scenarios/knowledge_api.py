"""
Knowledge API performance scenario.

Exercises CRUD operations across all knowledge domains:
error codes, rules, assets, appeal templates, and prompt templates.
"""

from uuid import uuid4

from locust import HttpUser, between, tag, task

from src.tests.performance.config import API_PREFIX


class KnowledgeAPIUser(HttpUser):
    """Simulates knowledge management CRUD traffic."""

    wait_time = between(0.5, 1.5)

    @task(4)
    @tag("knowledge", "crud")
    def error_codes_crud(self):
        suffix = uuid4().hex[:8]
        err_code = f"PERF-ERR-{suffix}"

        self.client.post(
            f"{API_PREFIX}/knowledge/error-codes",
            json={
                "error_code": err_code,
                "description": "性能测试错误码",
                "exception_type": "test",
                "responsible_role": "billing_staff",
                "recommendation": "联系管理员",
            },
            name="/knowledge/error-codes [POST]",
        )

        self.client.get(
            f"{API_PREFIX}/knowledge/error-codes",
            name="/knowledge/error-codes [GET list]",
        )

        self.client.get(
            f"{API_PREFIX}/knowledge/error-codes/{err_code}",
            name="/knowledge/error-codes [GET single]",
        )

        self.client.delete(
            f"{API_PREFIX}/knowledge/error-codes/{err_code}",
            name="/knowledge/error-codes [DELETE]",
        )

    @task(3)
    @tag("knowledge", "crud")
    def rules_crud(self):
        suffix = uuid4().hex[:8]
        rule_id = f"RULE-PERF-{suffix}"

        self.client.post(
            f"{API_PREFIX}/knowledge/rules",
            json={
                "rule_id": rule_id,
                "rule_name": "性能测试规则",
                "category": "test",
                "scenario": "test",
                "rule_content": "测试内容",
                "explanation": "测试说明",
            },
            name="/knowledge/rules [POST]",
        )

        self.client.get(
            f"{API_PREFIX}/knowledge/rules",
            name="/knowledge/rules [GET list]",
        )

        self.client.get(
            f"{API_PREFIX}/knowledge/rules/{rule_id}",
            name="/knowledge/rules [GET single]",
        )

        self.client.delete(
            f"{API_PREFIX}/knowledge/rules/{rule_id}",
            name="/knowledge/rules [DELETE]",
        )

    @task(2)
    @tag("knowledge", "crud")
    def assets_crud(self):
        suffix = uuid4().hex[:8]
        asset_id = f"ASSET-PERF-{suffix}"

        self.client.post(
            f"{API_PREFIX}/knowledge/assets",
            json={
                "asset_id": asset_id,
                "title": "性能测试资产",
                "source": "test",
                "asset_type": "document",
                "status": "active",
            },
            name="/knowledge/assets [POST]",
        )

        self.client.get(
            f"{API_PREFIX}/knowledge/assets",
            name="/knowledge/assets [GET list]",
        )

        self.client.delete(
            f"{API_PREFIX}/knowledge/assets/{asset_id}",
            name="/knowledge/assets [DELETE]",
        )

    @task(2)
    @tag("knowledge", "crud")
    def appeal_templates_crud(self):
        suffix = uuid4().hex[:8]
        template_id = f"TPL-PERF-{suffix}"

        self.client.post(
            f"{API_PREFIX}/knowledge/appeal-templates",
            json={
                "template_id": template_id,
                "template_name": "性能测试模板",
                "content": "提交申诉：{{reason}}",
            },
            name="/knowledge/appeal-templates [POST]",
        )

        self.client.get(
            f"{API_PREFIX}/knowledge/appeal-templates",
            name="/knowledge/appeal-templates [GET list]",
        )

        self.client.delete(
            f"{API_PREFIX}/knowledge/appeal-templates/{template_id}",
            name="/knowledge/appeal-templates [DELETE]",
        )

    @task(2)
    @tag("knowledge", "crud")
    def prompt_templates_crud(self):
        suffix = uuid4().hex[:8]
        template_id = f"PRMT-PERF-{suffix}"

        self.client.post(
            f"{API_PREFIX}/knowledge/prompt-templates",
            json={
                "template_id": template_id,
                "template_name": "性能Prompt",
                "template_type": "system",
                "content": "You are: {{role}}",
            },
            name="/knowledge/prompt-templates [POST]",
        )

        self.client.get(
            f"{API_PREFIX}/knowledge/prompt-templates",
            name="/knowledge/prompt-templates [GET list]",
        )

        self.client.delete(
            f"{API_PREFIX}/knowledge/prompt-templates/{template_id}",
            name="/knowledge/prompt-templates [DELETE]",
        )
