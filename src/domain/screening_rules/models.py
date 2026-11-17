"""筛查规则领域模型 — issue #86 规则管理（管理入口）。

表口径与 issue #86 任务书一致（Grok 问数侧只读引用，字段名/取值不得漂移）：

- ai_screen_rule：规则（候选/已批准/已关闭），class 为上传条目三分类
  （executable / needs_mapping / not_executable），source_clause 必填原条款；
- ai_screen_run：执行批次（running / succeeded / failed）；
- ai_screen_run_rule：批次 × 规则关联；
- ai_screen_finding：疑点命中（mismatch 明显对不上 / insufficient_material
  材料不足），同一费用只计一次金额——主疑点 primary_finding_id = 自身
  finding_id，其余命中指向主疑点。

纪律（issue #86）：引不出原条款的疑点不输出；未批准规则不得执行；关闭的
规则不再进入后续批次；命中只是疑点，判定与整改留在医保办。
"""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class RuleClass(StrEnum):
    """上传条目三分类。"""

    EXECUTABLE = "executable"
    NEEDS_MAPPING = "needs_mapping"
    NOT_EXECUTABLE = "not_executable"


class RuleStatus(StrEnum):
    CANDIDATE = "candidate"
    APPROVED = "approved"
    DISABLED = "disabled"


class RunStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class FindingType(StrEnum):
    MISMATCH = "mismatch"
    INSUFFICIENT_MATERIAL = "insufficient_material"


class VerifyStatus(StrEnum):
    PENDING = "pending"
    FOLLOW = "follow"
    NOT_FOLLOW = "not_follow"
    INSUFFICIENT = "insufficient"


def new_rule_id() -> str:
    return f"sr_{uuid.uuid4().hex[:12]}"


def new_run_id() -> str:
    return f"srun_{uuid.uuid4().hex[:12]}"


def new_finding_id() -> str:
    return f"sfind_{uuid.uuid4().hex[:12]}"


class ScreeningRule(BaseModel):
    """筛查规则：上传条目分类后生成候选，人批准后才可进入执行批次。"""

    rule_id: str
    source_doc: str
    source_clause: str = Field(min_length=1)  # 必填：原条款
    title: str
    condition_text: str
    rule_class: RuleClass
    mapping_gap: str | None = None  # needs_mapping 时写清缺什么
    status: RuleStatus = RuleStatus.CANDIDATE
    condition_spec: dict[str, Any] | None = None  # 可执行条件的结构化形式
    source_item_ref: str | None = None  # 上传清单中的条目序号
    created_at: datetime
    updated_at: datetime
    approved_at: datetime | None = None
    approved_by: str | None = None


class ScreeningRun(BaseModel):
    run_id: str
    started_at: datetime
    finished_at: datetime | None = None
    status: RunStatus = RunStatus.RUNNING
    time_range_start: datetime
    time_range_end: datetime
    error_message: str | None = None
    created_by: str


class ScreeningFinding(BaseModel):
    finding_id: str
    run_id: str
    rule_id: str
    settlement_key: str  # = o_Trade.T_TradeNo，可关联结算/费用/诊断/科室
    fee_line_id: str | None = None
    item_code: str | None = None
    item_name: str | None = None
    amount: float | None = None
    finding_type: FindingType
    primary_finding_id: str  # 主疑点 = 自身 finding_id
    evidence_clause: str  # 原条款
    evidence_facts: dict[str, Any] = Field(default_factory=dict)  # 对照事实
    verify_status: VerifyStatus = VerifyStatus.PENDING
    created_at: datetime


class ChecklistItem(BaseModel):
    """上传清单解析出的单条条目及其分类结果。"""

    item_ref: str
    clause: str
    rule_class: RuleClass
    mapping_gap: str | None = None
    candidate_rule_id: str | None = None


class ScreeningRuleNotFoundError(Exception):
    def __init__(self, rule_id: str) -> None:
        super().__init__(f"规则不存在: {rule_id}")
        self.rule_id = rule_id


class ScreeningRunNotFoundError(Exception):
    def __init__(self, run_id: str) -> None:
        super().__init__(f"执行批次不存在: {run_id}")
        self.run_id = run_id


class ScreeningFindingNotFoundError(Exception):
    def __init__(self, finding_id: str) -> None:
        super().__init__(f"疑点不存在: {finding_id}")
        self.finding_id = finding_id


class RuleNotApprovedError(Exception):
    """未批准的规则不得跑数（issue #86 批准门禁）。"""

    def __init__(self, rule_ids: list[str]) -> None:
        super().__init__(f"存在未批准规则，执行被拒绝: {', '.join(rule_ids)}")
        self.rule_ids = rule_ids


class NoApprovedRulesError(Exception):
    def __init__(self) -> None:
        super().__init__("没有已批准的规则可执行，请先在规则管理中批准规则")
