"""
LangGraph 流式执行包装器。

提供 StreamingLangGraph 类，包装编译后的 LangGraph 图对象，
使用 graph.stream(stream_mode="updates") 替代 graph.invoke()，
在每个节点执行完成时通过回调函数发出 stream:step 事件。
"""

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)

_NODE_LABELS: dict[str, str] = {
    # 结算异常场景节点
    "validate_claim": "校验结算请求",
    "check_high_risk": "检查高风险动作",
    "query_error_knowledge": "查询错误码知识库",
    "build_recommendation": "生成处理建议",
    # 出院前质控场景节点
    "get_patient_summary": "获取患者概览",
    "run_qc_rules": "执行质控规则",
    "check_qc_issues": "检查质控问题",
    "build_qc_report": "生成质控报告",
    # 共享节点
    "human_confirmation": "等待人工确认",
}


class StreamingLangGraph:
    """
    LangGraph 流式执行包装器。

    包装编译后的 LangGraph 图对象，在图的节点执行过程中通过回调函数
    发出 stream:step 事件，实现逐步流式输出。支持 interrupt() 人工确认中断的检测。

    当 on_event 为 None 时，直接使用 graph.invoke() 以获得零开销，
    避免创建流式迭代器的额外成本。
    """

    def __init__(
        self,
        graph: Any,
        graph_builder_fn: Callable[..., Any],
        scenario: str,
        on_event: Callable[[str, dict], None] | None = None,
    ):
        """
        初始化 StreamingLangGraph。

        Args:
            graph: 编译后的 LangGraph 图对象（CompiledGraph）
            graph_builder_fn: 图构建函数，接受 checkpointer 参数，用于重建图（恢复执行时使用）
            scenario: 业务场景标识（如 "settlement_exception_guidance"）
            on_event: 可选的事件回调函数，在每个节点执行完成时被调用。
                      回调签名: on_event(event_type: str, data: dict)
                      事件类型: stream:step（节点执行完成）、stream:error（执行出错）
        """
        self._graph = graph
        self._graph_builder_fn = graph_builder_fn
        self._scenario = scenario
        self._on_event = on_event

    @property
    def graph(self) -> Any:
        """获取底层编译后的 LangGraph 图对象。"""
        return self._graph

    @property
    def graph_builder_fn(self) -> Callable[..., Any]:
        """获取图构建函数。"""
        return self._graph_builder_fn

    @property
    def scenario(self) -> str:
        """获取业务场景标识。"""
        return self._scenario

    def invoke(self, input_data: dict, config: dict) -> dict:
        """
        执行图并发出流式步骤事件。

        当 on_event 为 None 时，直接调用 graph.invoke() 以获得零开销。
        否则，使用 graph.stream(stream_mode="updates") 逐节点执行，
        在每一步完成后发出 stream:step 事件。
        流完成后检查是否有人工确认中断，若有则发出 blocked 状态事件。

        Args:
            input_data: 图的初始状态字典
            config: LangGraph 配置字典，需包含 thread_id 等可配置参数
                    如 {"configurable": {"thread_id": "xxx"}}

        Returns:
            dict: 与 graph.invoke() 相同形状的最终状态字典

        Raises:
            透传 graph.stream() 或 graph.invoke() 中的异常
        """
        # 无回调时直接调用 invoke，零开销
        if self._on_event is None:
            return self._graph.invoke(input_data, config)

        # 使用 graph.stream() 逐节点流式执行
        updates: list[dict[str, Any]] = []
        try:
            for update in self._graph.stream(
                input_data,
                config,
                stream_mode="updates",
            ):
                updates.append(update)
                for node_name in update:
                    label = _NODE_LABELS.get(node_name, node_name)
                    self._emit("stream:step", {
                        "step": node_name,
                        "message": label,
                    })
        except Exception as e:
            logger.error("StreamingLangGraph 流式执行失败: %s", e)
            self._emit("stream:error", {"message": str(e), "scenario": self._scenario})
            raise

        # 流返回空时的降级处理（某些图可能不支持 stream_mode="updates"）
        if not updates:
            logger.warning(
                "graph.stream() 返回空结果（scenario=%s），降级使用 graph.invoke()",
                self._scenario,
            )
            return self._graph.invoke(input_data, config)

        # 合并所有节点输出为最终状态
        final_state = dict(input_data or {})
        for update in updates:
            for node_output in update.values():
                if isinstance(node_output, dict):
                    final_state.update(node_output)

        # 检查人工确认中断（interrupt）
        try:
            snapshot = self._graph.get_state(config)
            if snapshot.next:
                blocked_node = snapshot.next[0]
                self._emit("stream:step", {
                    "step": blocked_node,
                    "message": _NODE_LABELS.get(blocked_node, blocked_node),
                    "status": "blocked",
                })
        except Exception:
            logger.warning("检查图状态（人工确认中断）失败", exc_info=True)

        return final_state

    def _emit(self, event: str, data: dict) -> None:
        """内部辅助方法：发出事件回调。"""
        if self._on_event is not None:
            try:
                self._on_event(event, data)
            except Exception:
                logger.error("事件回调异常（event=%s）", event, exc_info=True)
