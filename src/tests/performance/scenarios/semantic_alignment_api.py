"""Semantic proposal review-list performance scenario."""

import base64
import hashlib
import hmac
import json
import os
import time

from locust import HttpUser, between, tag, task

from src.tests.performance.config import API_PREFIX


def _review_token() -> str:
    secret = os.environ["AUTH_JWT_SECRET"]

    def encode(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode()

    header = encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = encode(json.dumps({
        "sub": "semantic-perf-reviewer",
        "permissions": ["semantic:review"],
        "roles": [],
        "exp": time.time() + 3600,
    }).encode())
    signature = encode(hmac.new(
        secret.encode(), f"{header}.{payload}".encode(), hashlib.sha256
    ).digest())
    return f"{header}.{payload}.{signature}"


class SemanticAlignmentAPIUser(HttpUser):
    """Exercises the indexed proposal list query used by the review page."""

    wait_time = between(0.1, 0.3)

    def on_start(self) -> None:
        self.headers = {"Authorization": f"Bearer {_review_token()}"}

    @task
    @tag("semantic_alignment", "readonly")
    def list_proposals(self) -> None:
        self.client.get(
            f"{API_PREFIX}/semantic/alignment/proposals?proposal_type=metric",
            headers=self.headers,
            name="/semantic/alignment/proposals [GET list]",
        )
