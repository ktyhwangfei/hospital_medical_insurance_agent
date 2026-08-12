"""Skill 错误归因转换的提示词构造。

只向模型发送脱敏摘要、当时 selected skill、可用 Skill manifest 摘要。
原文患者标识绝不进入提示词。
"""

from __future__ import annotations

import json

from src.runtime.skill_management.regression_transform_service import TransformContext


def build_transform_prompt(context: TransformContext) -> str:
    manifest_block = json.dumps(
        context.available_skill_manifest, ensure_ascii=False
    )
    return (
        "请对以下医保政策问答「回答有误」案例进行错误归因，输出严格 JSON。\n\n"
        f"用户问题（脱敏摘要）：{context.question_excerpt}\n"
        f"原回答（脱敏摘要）：{context.answer_excerpt}\n"
        f"用户备注：{context.comment or '（无）'}\n"
        f"当时命中的 Skill：{context.source_selected_skill_id or '（未命中）'}\n"
        f"可用 Skill 列表：{manifest_block}\n\n"
        "输出字段（不要输出 JSON 以外的内容）：\n"
        "- error_dimension: routing | calculation | policy_content | citation "
        "| answer_quality | safety | other\n"
        "- root_cause: 归因说明\n"
        "- target_skill_id: 目标 Skill ID（other 可为 null）\n"
        "- case_proposal: 与 error_dimension 一致的类型化 proposal（含 case_type 字段）；"
        "若 error_dimension=other 则必须为 null\n"
        "- citations: 可追溯政策证据 [{source_id, ...}]，无证据时返回空数组\n"
        "- uncertainties: 不确定项列表\n\n"
        "约束：case_proposal.case_type 必须等于 error_dimension；"
        "证据不足时用 other 且 case_proposal=null。"
    )
