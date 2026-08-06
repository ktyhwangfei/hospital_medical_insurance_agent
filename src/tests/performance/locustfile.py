"""
Locust entry point for the hospital medical insurance AI agent performance tests.

Imports all scenario HttpUser classes so Locust discovers them automatically.
Provides event hooks for test lifecycle logging.
"""

from locust import events

from scenarios.business_api import BusinessAPIUser
from scenarios.knowledge_api import KnowledgeAPIUser
from scenarios.mcp_api import McpAPIUser
from scenarios.model_api import ModelAPIUser
from scenarios.policy_qa_api import PolicyQAAPIUser
from scenarios.skill_api import SkillAPIUser

__all__ = [
    "BusinessAPIUser",
    "KnowledgeAPIUser",
    "McpAPIUser",
    "ModelAPIUser",
    "PolicyQAAPIUser",
    "SkillAPIUser",
]


@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    """Log that the performance test is starting."""
    print(f"\n{'=' * 60}")
    print(f"Performance test starting...")
    print(f"Target host: {environment.host}")
    print(f"User classes: {len(environment.runner.user_classes) if environment.runner else 'N/A'}")
    print(f"{'=' * 60}\n")


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    """Print summary statistics when the performance test finishes."""
    print(f"\n{'=' * 60}")
    print(f"Performance test completed.")
    if environment.stats:
        print(f"Total requests: {environment.stats.total.num_requests}")
        print(f"Total failures: {environment.stats.total.num_failures}")
        print(f"Average response time: {environment.stats.total.avg_response_time:.2f} ms")
        if environment.stats.total.num_requests > 0:
            error_rate = (environment.stats.total.num_failures / environment.stats.total.num_requests) * 100
            print(f"Error rate: {error_rate:.2f}%")
    print(f"{'=' * 60}\n")
