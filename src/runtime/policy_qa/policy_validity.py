"""政策规则有效期 / 发布状态硬过滤（Issue #33 加固②）。

structured 与 broad 两条读路径共用的版本/有效期判定 helper，
保证两侧语义一致（结构化侧硬、broad 侧不得软）：

- ``publish_status`` 必须为 ``published``（未发布 / 草案 / 已撤销一律硬排除）；
- ``effective_date <= 参考日期``（生效前不得作为答案源）；
- ``expiry_date >= 参考日期`` 或为长期有效哨兵 ``9999-12-31``（过期段命中即丢弃）。

集合层面：collection 缺少对应字段（旧 schema）时跳过该过滤，不误杀可答规则；
实体层面：dynamic key 缺失的实体不参与 expr 匹配（与 Milvus 语义一致，两侧相同）。
"""

from __future__ import annotations

PUBLISHED_STATUS = "published"
DEFAULT_EXPIRY_DATE = "9999-12-31"


def build_publish_status_expr(available_fields: set[str] | None = None) -> str | None:
    """发布状态硬过滤片段；集合无该字段时返回 None（由调用方跳过，不误杀）。"""
    if available_fields is not None and "publish_status" not in available_fields:
        return None
    return f'publish_status == "{PUBLISHED_STATUS}"'


def build_validity_date_expr(
    reference_date: str,
    available_fields: set[str] | None = None,
) -> list[str]:
    """有效期硬过滤片段（effective 起 + expiry 止）。

    边界语义：生效/失效**精确当天**均视为有效（<= / >=），前一天/后一天即排除。
    reference_date 为长期有效哨兵（9999-12-31）时不拼日期过滤（保持既有行为）。
    """
    if not reference_date or reference_date == DEFAULT_EXPIRY_DATE:
        return []
    parts: list[str] = []
    if available_fields is None or "effective_date" in available_fields:
        parts.append(f'effective_date <= "{reference_date}"')
    if available_fields is None or "expiry_date" in available_fields:
        parts.append(
            f'(expiry_date == "{DEFAULT_EXPIRY_DATE}" or expiry_date >= "{reference_date}")'
        )
    return parts
