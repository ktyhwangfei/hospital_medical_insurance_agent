"""
Pytest conftest for settlement_explain_skill tests.

Forces MODEL_BASE_URL to "dummy" so the ModelGateway returns
pre-defined dummy output instead of making real API calls.
"""

import os

# Must be set before any module imports ModelServiceConfig
os.environ["MODEL_BASE_URL"] = "dummy"
