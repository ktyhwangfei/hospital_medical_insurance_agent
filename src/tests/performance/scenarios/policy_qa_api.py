"""Policy QA streaming API performance scenario."""

from locust import HttpUser, between, tag, task

from src.tests.performance.config import API_PREFIX


class PolicyQAAPIUser(HttpUser):
    """Exercise the real Policy QA SSE endpoint and consume the full stream."""

    wait_time = between(1, 2)

    @task
    @tag("policy-qa", "stream")
    def policy_qa_stream(self):
        with self.client.post(
            f"{API_PREFIX}/policy-qa/stream",
            json={
                "question": "查询住院费用构成",
                "settlement_id": "1671213",
            },
            catch_response=True,
            stream=True,
            name="/policy-qa/stream",
        ) as response:
            saw_done = any(
                line.startswith(b"event: done") for line in response.iter_lines()
            )
            if response.status_code != 200 or not saw_done:
                response.failure("policy qa stream did not finish with done")
