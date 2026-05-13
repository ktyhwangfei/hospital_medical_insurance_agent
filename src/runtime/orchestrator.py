"""
RuntimeOrchestrator — Central orchestration abstraction for request processing.

Responsibility boundary:
  Owns the execution lifecycle: context assembly -> security checks -> intent resolution
  -> executor delegation -> response assembly. Contains NO business logic; all domain
  logic is delegated to injected components.

This is the single entry point that replaces the procedural process_chat_request()
in routes.py. The orchestrator's job is flow control, not implementation.

Lifecycle:
  1. _check_security(request)   — Detect and block high-risk actions before any processing
  2. _build_context(request)    — Parse intent, assemble RuntimeContext
  3. _resolve_scenario(context) — Extract the resolved scenario identifier
  4. _authorize(role, scenario) — Verify role-based access (if checker configured)
  5. _delegate(scenario, context) — Route to the appropriate executor
  6. Return AgentResponse

Architecture notes:
  - ScenarioExecutor: handles known business scenarios (settlement exception, pre-discharge QC)
  - SkillExecutor: handles skill-based execution (composable tool workflows from skill registry)
  - Both follow the Strategy pattern — the orchestrator selects the right strategy at runtime
"""

from collections.abc import Callable
from typing import Protocol

from src.domain.skill.models import Skill
from src.runtime.api.schemas import AgentResponse, ChatRequest
from src.runtime.context.models import RuntimeContext
from src.runtime.context.service import build_runtime_context
from src.runtime.intent.models import IntentResult
from src.security.risk_control.service import build_human_confirmation_response


class ScenarioExecutor(Protocol):
    """Protocol for scenario-based business logic executors.

    Implementations handle a specific business scenario (e.g., settlement exception
    guidance, pre-discharge quality control) by executing the appropriate adapter
    calls, knowledge retrieval, and response assembly.

    Each executor declares which scenarios it can handle via ``can_handle()``,
    so the orchestrator can dispatch without instanceof checks.
    """

    def execute(self, context: RuntimeContext) -> AgentResponse:
        """Execute the scenario logic for the given runtime context.

        Args:
            context: Fully assembled runtime context (includes intent, patient info).

        Returns:
            Structured AgentResponse with results, citations, and audit trail.
        """
        ...

    def can_handle(self, scenario: str) -> bool:
        """Return True if this executor is capable of handling *scenario*.

        Args:
            scenario: The resolved scenario identifier (e.g. ``'settlement_exception_guidance'``).

        Returns:
            True if the executor can process the scenario.
        """
        ...


class SkillExecutor(Protocol):
    """Protocol for skill-based execution engines.

    Implementations execute skills — composable workflows of tool invocations
    defined by the skill registry system. Each skill step maps to a tool
    (adapter call, knowledge retrieval, MCP tool call, etc.).
    """

    def execute_skill(
        self,
        skill: Skill,
        context: RuntimeContext,
    ) -> AgentResponse:
        """Execute a skill within the given runtime context.

        Args:
            skill: The skill definition (steps, allowed tools, owner).
            context: Runtime context with patient, encounter, and user info.

        Returns:
            Structured AgentResponse with step results and audit trail.
        """
        ...


class RuntimeOrchestrator:
    """Central orchestrator that manages the end-to-end request lifecycle.

    The orchestrator assembles a pipeline of injectable services and routes
    the request to the correct executor based on the resolved scenario.
    Every non-trivial concern is externalized:

    +------------------+--------------------------------------------------+
    | Component        | Responsibility                                    |
    +------------------+--------------------------------------------------+
    | intent_parser    | ``Callable[[str], IntentResult]``                 |
    | security_checker | ``Callable[[str], list[str]]`` — blocked actions  |
    | scenario_executor| ``ScenarioExecutor`` — business scenarios          |
    | skill_executor   | ``SkillExecutor`` — skill workflows                |
    +------------------+--------------------------------------------------+

    Usage::

        orchestrator = RuntimeOrchestrator(
            intent_parser=parse_intent,
            security_checker=detect_blocked_actions,
            scenario_executor=my_scenario_executor,
            skill_executor=my_skill_executor,
            authorization_checker=is_allowed,
        )
        response = orchestrator.execute_request(chat_request)
    """

    def __init__(
        self,
        intent_parser: Callable[[str], IntentResult],
        security_checker: Callable[[str], list[str]],
        scenario_executor: ScenarioExecutor,
        skill_executor: SkillExecutor,
        authorization_checker: Callable[[str, str], bool] | None = None,
    ) -> None:
        self._intent_parser = intent_parser
        self._security_checker = security_checker
        self._scenario_executor = scenario_executor
        self._skill_executor = skill_executor
        self._authorization_checker = authorization_checker

    def execute_request(self, request: ChatRequest) -> AgentResponse:
        """Execute a chat request through the full orchestration lifecycle.

        Lifecycle:
          1. Security screening — reject high-risk actions before any processing
          2. Context assembly   — parse intent, build RuntimeContext
          3. Scenario resolution — extract scenario from parsed context
          4. Authorization      — verify role has permission (if checker configured)
          5. Executor delegation — route to the correct handler
          6. Response return    — return the final AgentResponse

        Args:
            request: Incoming chat request with user message and context.

        Returns:
            Structured AgentResponse with results, citations, and audit trail.
        """
        # 1. Security — fast-path rejection of high-risk actions
        blocked_response = self._check_security(request)
        if blocked_response is not None:
            return blocked_response

        # 2. Context assembly — parse intent, build runtime context
        context = self._build_context(request)

        # 3. Scenario resolution — extract the resolved scenario
        scenario = self._resolve_scenario(context)

        # 4. Authorization — role-based access control
        if self._authorization_checker is not None:
            if not self._authorization_checker(request.role, scenario):
                return AgentResponse(
                    scenario=scenario,
                    status="permission_denied",
                    result={"message": f"角色 {request.role} 无权访问该场景"},
                    uncertainties=[f"角色 {request.role} 无权访问场景: {scenario}"],
                )

        # 5. Delegate to executor
        return self._delegate(scenario, context)

    def _check_security(self, request: ChatRequest) -> AgentResponse | None:
        """Screen the request for high-risk actions.

        Delegates to the injected ``security_checker``. If blocked actions are
        detected, returns a ``waiting_human_confirmation`` response immediately.

        Args:
            request: The incoming chat request.

        Returns:
            An AgentResponse if high-risk actions were detected, None otherwise.
        """
        blocked = self._security_checker(request.message)
        if blocked:
            return build_human_confirmation_response(blocked)
        return None

    def _build_context(self, request: ChatRequest) -> RuntimeContext:
        """Assemble the runtime context for this request.

        Parses intent via the injected parser, then constructs the full
        RuntimeContext with workflow IDs, user metadata, and intent data.

        Args:
            request: The incoming chat request.

        Returns:
            Fully populated RuntimeContext.
        """
        intent_result = self._intent_parser(request.message)
        return build_runtime_context(request, intent_result)

    @staticmethod
    def _resolve_scenario(context: RuntimeContext) -> str:
        """Extract the scenario identifier from the runtime context.

        By default returns ``context.intent``. Subclasses or callers may
        override this to apply re-resolution or fallback logic.

        Args:
            context: The assembled runtime context.

        Returns:
            The resolved scenario string.
        """
        return context.intent

    def _delegate(self, scenario: str, context: RuntimeContext) -> AgentResponse:
        """Route the request to the appropriate executor based on *scenario*.

        Resolution order:
          1. Scenario executor — checks ``can_handle(scenario)``
          2. Not implemented   — returns a fallback response

        Args:
            scenario: The resolved scenario identifier.
            context: The assembled runtime context.

        Returns:
            The AgentResponse from the matched executor, or a not-implemented
            fallback if no executor can handle the scenario.
        """
        if self._scenario_executor.can_handle(scenario):
            return self._scenario_executor.execute(context)

        return AgentResponse(
            status="not_implemented",
            uncertainties=[f"未识别的场景: {scenario}"],
        )
