"""Policy QA streaming API performance scenario."""

from time import perf_counter

from locust import HttpUser, between, tag, task

from src.tests.performance.config import API_PREFIX


class PolicyQAAPIUser(HttpUser):
    """Exercise the real Policy QA SSE endpoint and consume the full stream."""

    wait_time = between(1, 2)

    @task
    @tag("policy-qa", "stream")
    def policy_qa_stream(self):
        started_at = perf_counter()
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
            saw_done = False
            stream_error: Exception | None = None
            try:
                for line in response.iter_lines():
                    if line.strip() == b"event: done":
                        saw_done = True
            except Exception as exc:  # Locust 必须把断流计入失败率。
                stream_error = exc
            finally:
                response.request_meta["response_time"] = (
                    perf_counter() - started_at
                ) * 1000

            if stream_error is not None:
                response.failure(f"policy qa stream interrupted: {stream_error}")
            elif response.status_code != 200:
                response.failure(
                    f"policy qa stream returned HTTP {response.status_code}"
                )
            elif not saw_done:
                response.failure("policy qa stream did not finish with done")
