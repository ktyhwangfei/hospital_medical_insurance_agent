"""
Model service API performance scenario.

Tests model configuration, routing, provider management, and
both non-streaming and streaming model test endpoints.
"""

from locust import HttpUser, between, tag, task

from src.tests.performance.config import API_PREFIX


class ModelAPIUser(HttpUser):
    """Simulates model service management traffic."""

    wait_time = between(0.5, 1.5)

    @task(3)
    @tag("model", "readonly")
    def get_config(self):
        self.client.get(
            f"{API_PREFIX}/model-config",
            name="/model-config",
        )

    @task(3)
    @tag("model", "readonly")
    def get_routes(self):
        self.client.get(
            f"{API_PREFIX}/model-routes",
            name="/model-routes",
        )

    @task(2)
    @tag("model", "readonly")
    def get_providers(self):
        self.client.get(
            f"{API_PREFIX}/model-providers",
            name="/model-providers",
        )

    @task(2)
    @tag("model", "chat")
    def model_test(self):
        self.client.post(
            f"{API_PREFIX}/model-test",
            json={
                "message": "你好，请简单自我介绍",
                "scene": "default",
            },
            name="/model-test",
        )

    @task(2)
    @tag("model", "stream")
    def model_test_stream(self):
        with self.client.post(
            f"{API_PREFIX}/model-test/stream",
            json={
                "message": "你好",
                "scene": "default",
            },
            catch_response=True,
            stream=True,
            name="/model-test/stream",
        ) as response:
            for _ in response.iter_lines():
                pass
