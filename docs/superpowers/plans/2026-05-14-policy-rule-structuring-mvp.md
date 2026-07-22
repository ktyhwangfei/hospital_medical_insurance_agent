# 医保政策规则结构化引擎（MVP：住院起付线）Implementation Plan
 
> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
 
**Goal:** 在 `src/knowledge_extension/rule_explanation/` 下新增“医保政策规则结构化引擎”，实现政策条款切分→条款分类→候选规则抽取→规则 JSON 结构化→规则校验→人工审核状态→存储→Demo API（聚焦住院起付线规则）。
 
**Architecture:** 采用分层数据模型（policy_documents → policy_chunks → rule_candidates → medical_insurance_rules → rule_execution_log），LLM 仅用于“候选规则抽取/解释”，金额计算与规则落库必须由程序校验与人工审核守门；存储方式对齐当前工程的 `CREATE TABLE IF NOT EXISTS + PostgreSQLClient` 模式，并通过独立模块提供可替换的 in_memory/postgres 实现。
 
**Tech Stack:** FastAPI（路由）、Pydantic v2（结构化模型与 JSON Schema）、PostgreSQLClient/psycopg（持久化）、ModelGateway（OpenAI 兼容模型调用）。
 
---
 
## Scope（本阶段只做 MVP）
 
- 仅覆盖规则类型中的：`deductible_rule`（起付线）与 `period_rule`（90 天周期）两类的最小闭环。
- 仅覆盖业务场景：`medical_scene="住院"`。
- 规则抽取结果先落 `rule_candidates`，校验通过但未审核仍不能进入 `medical_insurance_rules` 的 `review_status="approved"`。
- 不实现“真实院内系统接入/真实患者数据计算”；仅提供 Demo 计算输入（入院次数、医院等级、是否跨周期）并输出“计算过程 + 解释 + 政策依据字段”。
 
## Planned File Structure
 
**Create (new package):**
- `src/knowledge_extension/rule_explanation/policy_structuring/__init__.py`
- `src/knowledge_extension/rule_explanation/policy_structuring/enums.py`
- `src/knowledge_extension/rule_explanation/policy_structuring/models.py`
- `src/knowledge_extension/rule_explanation/policy_structuring/json_schema.py`
- `src/knowledge_extension/rule_explanation/policy_structuring/text_cleaner.py`
- `src/knowledge_extension/rule_explanation/policy_structuring/clause_splitter.py`
- `src/knowledge_extension/rule_explanation/policy_structuring/clause_classifier.py`
- `src/knowledge_extension/rule_explanation/policy_structuring/prompts.py`
- `src/knowledge_extension/rule_explanation/policy_structuring/rule_extractor.py`
- `src/knowledge_extension/rule_explanation/policy_structuring/rule_validator.py`
- `src/knowledge_extension/rule_explanation/policy_structuring/service.py`
- `src/knowledge_extension/rule_explanation/policy_structuring/storage/__init__.py`
- `src/knowledge_extension/rule_explanation/policy_structuring/storage/ports.py`
- `src/knowledge_extension/rule_explanation/policy_structuring/storage/in_memory.py`
- `src/knowledge_extension/rule_explanation/policy_structuring/storage/postgres.py`
 
**Modify (API wiring):**
- `src/runtime/api/app.py`
- `src/runtime/api/schemas.py`
- `src/runtime/api/policy_structuring_routes.py` (new router file)
 
**Tests:**
- `src/tests/unit/knowledge_extension/test_policy_structuring.py`
- `src/tests/integration/api/test_policy_structuring_routes.py`
 
---
 
### Task 1: 定义规则结构化数据模型 + JSON Schema（MVP 子集）
 
**Files:**
- Create: `src/knowledge_extension/rule_explanation/policy_structuring/enums.py`
- Create: `src/knowledge_extension/rule_explanation/policy_structuring/models.py`
- Create: `src/knowledge_extension/rule_explanation/policy_structuring/json_schema.py`
- Test: `src/tests/unit/knowledge_extension/test_policy_structuring.py`
 
- [ ] **Step 1: Write failing unit test for Rule model JSON schema generation**
 
```python
from src.knowledge_extension.rule_explanation.policy_structuring.models import MedicalInsuranceRule, RuleType
 
 
def test_rule_model_generates_json_schema():
    schema = MedicalInsuranceRule.model_json_schema()
    assert schema["title"] == "MedicalInsuranceRule"
    assert "properties" in schema
    assert "rule_type" in schema["properties"]
 
 
def test_rule_type_contains_deductible_and_period():
    assert RuleType.DEDUCTIBLE_RULE.value == "deductible_rule"
    assert RuleType.PERIOD_RULE.value == "period_rule"
```
 
- [ ] **Step 2: Run the test to verify it fails**
 
Run: `python -m pytest src/tests/unit/knowledge_extension/test_policy_structuring.py -v`  
Expected: FAIL with `ModuleNotFoundError: ... policy_structuring ...`
 
- [ ] **Step 3: Create enums + models (MVP fields only, but兼容 AGENTS.md 统一结构)**
 
```python
from enum import StrEnum
 
 
class RuleType(StrEnum):
    DEDUCTIBLE_RULE = "deductible_rule"
    PERIOD_RULE = "period_rule"
 
 
class ReviewStatus(StrEnum):
    PENDING = "pending"
    VALIDATED = "validated"
    REJECTED = "rejected"
    APPROVED = "approved"
```
 
```python
from datetime import date
from typing import Any
 
from pydantic import BaseModel, Field
 
from src.knowledge_extension.rule_explanation.policy_structuring.enums import ReviewStatus, RuleType
 
 
class SourceEvidence(BaseModel):
    document_title: str = ""
    policy_no: str = ""
    publish_date: str = ""
    source_url: str = ""
    chunk_id: str = ""
    original_text: str = ""
 
 
class MedicalInsuranceRule(BaseModel):
    rule_code: str = ""
    rule_name: str = ""
    rule_type: RuleType
    region: str = "北京市"
    insurance_type: str = ""
    person_type: str = ""
    medical_scene: str = ""
    hospital_level: str = ""
 
    applicable_condition: dict[str, Any] = Field(default_factory=dict)
    calculation: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)
    period_rule: dict[str, Any] = Field(default_factory=dict)
    exception_rule: list[dict[str, Any]] = Field(default_factory=list)
 
    source_evidence: SourceEvidence = Field(default_factory=SourceEvidence)
    confidence: float = 0.0
    review_status: ReviewStatus = ReviewStatus.PENDING
 
    version: str = "draft"
    effective_date: date | None = None
    enabled: bool = True
```
 
```python
from src.knowledge_extension.rule_explanation.policy_structuring.models import MedicalInsuranceRule
 
 
def medical_insurance_rule_json_schema() -> dict:
    return MedicalInsuranceRule.model_json_schema()
```
 
- [ ] **Step 4: Run unit test again**
 
Run: `python -m pytest src/tests/unit/knowledge_extension/test_policy_structuring.py -v`  
Expected: PASS for the added tests
 
- [ ] **Step 5: Commit**
 
```bash
git add src/knowledge_extension/rule_explanation/policy_structuring src/tests/unit/knowledge_extension/test_policy_structuring.py
git commit -m "feat: add policy rule structuring models and schema"
```
 
---
 
### Task 2: 文本清洗 + 法律结构条款切分器（按“章/条/款/项”）
 
**Files:**
- Create: `src/knowledge_extension/rule_explanation/policy_structuring/text_cleaner.py`
- Create: `src/knowledge_extension/rule_explanation/policy_structuring/clause_splitter.py`
- Test: `src/tests/unit/knowledge_extension/test_policy_structuring.py`
 
- [ ] **Step 1: Add failing tests for clause splitting**
 
```python
from src.knowledge_extension.rule_explanation.policy_structuring.clause_splitter import split_policy_clauses
 
 
def test_split_policy_clauses_by_articles_and_items():
    text = "第一章 总则\n第一条 为规范管理...\n（一）适用范围...\n（二）定义...\n第二条 住院治疗每90天为一个结算周期。"
    chunks = split_policy_clauses(text, document_id="doc-1")
    assert len(chunks) >= 3
    assert chunks[0].path.startswith("第一章")
    assert any("第一条" in c.path for c in chunks)
    assert any("第二条" in c.path for c in chunks)
```
 
- [ ] **Step 2: Run unit tests to confirm failure**
 
Run: `python -m pytest src/tests/unit/knowledge_extension/test_policy_structuring.py -v`  
Expected: FAIL with `ModuleNotFoundError` for splitter
 
- [ ] **Step 3: Implement cleaner + splitter returning structured chunks**
 
```python
import re
 
 
def clean_policy_text(text: str) -> str:
    t = text.replace("\r\n", "\n").replace("\r", "\n")
    t = re.sub(r"[ \t]+\n", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()
```
 
```python
import re
from dataclasses import dataclass
 
from src.knowledge_extension.rule_explanation.policy_structuring.text_cleaner import clean_policy_text
 
 
@dataclass(frozen=True)
class PolicyChunk:
    chunk_id: str
    document_id: str
    path: str
    heading: str
    text: str
    order_index: int
 
 
_CHAPTER_RE = re.compile(r"^(第[一二三四五六七八九十百千]+章)\s*(.*)$")
_ARTICLE_RE = re.compile(r"^(第[一二三四五六七八九十百千]+条)\s*(.*)$")
_CN_ITEM_RE = re.compile(r"^（([一二三四五六七八九十百千]+)）\s*(.*)$")
_NUM_ITEM_RE = re.compile(r"^(\d+)[\.、]\s*(.*)$")
 
 
def split_policy_clauses(text: str, document_id: str) -> list[PolicyChunk]:
    t = clean_policy_text(text)
    lines = [ln.strip() for ln in t.split("\n") if ln.strip()]
 
    chapter = ""
    article = ""
    current_path = ""
    buf: list[str] = []
    chunks: list[PolicyChunk] = []
    idx = 0
 
    def flush(heading: str, path: str) -> None:
        nonlocal idx, buf, chunks
        if not buf:
            return
        idx += 1
        chunk_id = f"pc-{document_id}-{idx:04d}"
        chunks.append(
            PolicyChunk(
                chunk_id=chunk_id,
                document_id=document_id,
                path=path,
                heading=heading,
                text="\n".join(buf).strip(),
                order_index=idx,
            )
        )
        buf = []
 
    for ln in lines:
        m = _CHAPTER_RE.match(ln)
        if m:
            flush(heading=current_path or chapter or "正文", path=current_path or chapter or "正文")
            chapter = m.group(1)
            chapter_title = m.group(2).strip()
            current_path = f"{chapter}{(' ' + chapter_title) if chapter_title else ''}"
            article = ""
            continue
 
        m = _ARTICLE_RE.match(ln)
        if m:
            flush(heading=current_path or chapter or "正文", path=current_path or chapter or "正文")
            article = m.group(1)
            article_title = m.group(2).strip()
            current_path = "/".join([p for p in [chapter, f"{article}{(' ' + article_title) if article_title else ''}"] if p])
            buf.append(ln)
            continue
 
        m = _CN_ITEM_RE.match(ln) or _NUM_ITEM_RE.match(ln)
        if m and article:
            flush(heading=current_path, path=current_path)
            item_title = ln
            current_path = "/".join([p for p in [chapter, article, item_title] if p])
            buf.append(ln)
            continue
 
        buf.append(ln)
 
    flush(heading=current_path or chapter or "正文", path=current_path or chapter or "正文")
    return chunks
```
 
- [ ] **Step 4: Run unit tests**
 
Run: `python -m pytest src/tests/unit/knowledge_extension/test_policy_structuring.py -v`  
Expected: PASS for clause splitting tests
 
- [ ] **Step 5: Commit**
 
```bash
git add src/knowledge_extension/rule_explanation/policy_structuring/text_cleaner.py src/knowledge_extension/rule_explanation/policy_structuring/clause_splitter.py src/tests/unit/knowledge_extension/test_policy_structuring.py
git commit -m "feat: add legal-structure clause splitter"
```
 
---
 
### Task 3: 条款分类（MVP：住院起付线 vs 结算周期）
 
**Files:**
- Create: `src/knowledge_extension/rule_explanation/policy_structuring/clause_classifier.py`
- Test: `src/tests/unit/knowledge_extension/test_policy_structuring.py`
 
- [ ] **Step 1: Add failing tests for classification**
 
```python
from src.knowledge_extension.rule_explanation.policy_structuring.clause_classifier import classify_clause
 
 
def test_classify_clause_deductible():
    assert classify_clause("第二次及以后住院起付线减半") == "deductible"
 
 
def test_classify_clause_period():
    assert classify_clause("住院治疗每90天为一个结算周期") == "period"
```
 
- [ ] **Step 2: Run unit tests**
 
Run: `python -m pytest src/tests/unit/knowledge_extension/test_policy_structuring.py -v`  
Expected: FAIL with missing classifier
 
- [ ] **Step 3: Implement deterministic classifier (keyword + regex)**
 
```python
import re
 
 
_DEDUCTIBLE_PATTERNS = [
    re.compile(r"起付线"),
    re.compile(r"减半"),
]
 
_PERIOD_PATTERNS = [
    re.compile(r"\b90天\b"),
    re.compile(r"结算周期"),
    re.compile(r"周期"),
]
 
 
def classify_clause(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return "unknown"
    if any(p.search(t) for p in _DEDUCTIBLE_PATTERNS):
        return "deductible"
    if any(p.search(t) for p in _PERIOD_PATTERNS):
        return "period"
    return "unknown"
```
 
- [ ] **Step 4: Run unit tests**
 
Run: `python -m pytest src/tests/unit/knowledge_extension/test_policy_structuring.py -v`  
Expected: PASS
 
- [ ] **Step 5: Commit**
 
```bash
git add src/knowledge_extension/rule_explanation/policy_structuring/clause_classifier.py src/tests/unit/knowledge_extension/test_policy_structuring.py
git commit -m "feat: add clause classifier for deductible and period"
```
 
---
 
### Task 4: 候选规则抽取（ModelGateway）+ 规则校验（Pydantic 结构/字段约束）
 
**Files:**
- Create: `src/knowledge_extension/rule_explanation/policy_structuring/prompts.py`
- Create: `src/knowledge_extension/rule_explanation/policy_structuring/rule_extractor.py`
- Create: `src/knowledge_extension/rule_explanation/policy_structuring/rule_validator.py`
- Test: `src/tests/unit/knowledge_extension/test_policy_structuring.py`
 
- [ ] **Step 1: Add failing tests for extractor (mock ModelGateway output)**
 
```python
from unittest.mock import MagicMock
 
from src.knowledge_extension.rule_explanation.policy_structuring.models import MedicalInsuranceRule, RuleType
from src.knowledge_extension.rule_explanation.policy_structuring.rule_extractor import extract_rule_candidates
 
 
def test_extract_rule_candidates_parses_json_from_model_output():
    gateway = MagicMock()
    gateway.generate.return_value.content = '{"rule_type":"deductible_rule","rule_name":"第二次及以后住院起付线减半","medical_scene":"住院","applicable_condition":{"hospitalization_count":">=2"},"calculation":{"deductible_amount":"standard_deductible * 0.5"},"source_evidence":{"original_text":"第二次及以后住院起付线减半"}}'
 
    rules = extract_rule_candidates(
        gateway=gateway,
        clause_text="第二次及以后住院起付线减半",
        chunk_id="pc-doc-0001",
        document_title="测试政策",
        source_url="http://example.com",
        publish_date="2026-01-01",
    )
    assert rules
    assert isinstance(rules[0], MedicalInsuranceRule)
    assert rules[0].rule_type is RuleType.DEDUCTIBLE_RULE
    assert rules[0].source_evidence.chunk_id == "pc-doc-0001"
```
 
- [ ] **Step 2: Run unit tests**
 
Run: `python -m pytest src/tests/unit/knowledge_extension/test_policy_structuring.py -v`  
Expected: FAIL with missing extractor
 
- [ ] **Step 3: Implement prompts**
 
```python
RULE_EXTRACTION_SYSTEM_PROMPT = """你是医保政策规则结构化引擎。你的任务是把政策条款抽取为可计算的候选规则 JSON。
要求：
1. 仅输出 JSON（禁止 Markdown、禁止多余解释文字）
2. rule_type 必须是 deductible_rule 或 period_rule
3. medical_scene 固定输出 住院（如果条款与住院无关则输出 {}）
4. source_evidence.original_text 必须包含原条款
"""
 
 
RULE_EXTRACTION_USER_PROMPT_TEMPLATE = """请从以下条款抽取候选规则：
条款：{clause_text}
 
输出示例（仅示例结构，具体值由你填充）：
{{
  "rule_code": "",
  "rule_name": "",
  "rule_type": "deductible_rule",
  "region": "北京市",
  "insurance_type": "",
  "person_type": "",
  "medical_scene": "住院",
  "hospital_level": "",
  "applicable_condition": {{}},
  "calculation": {{}},
  "result": {{}},
  "period_rule": {{}},
  "exception_rule": [],
  "source_evidence": {{
    "document_title": "{document_title}",
    "policy_no": "",
    "publish_date": "{publish_date}",
    "source_url": "{source_url}",
    "chunk_id": "{chunk_id}",
    "original_text": "{clause_text}"
  }},
  "confidence": 0.0,
  "review_status": "pending",
  "version": "draft",
  "enabled": true
}}
"""
```
 
- [ ] **Step 4: Implement extractor (single JSON object output → list[MedicalInsuranceRule])**
 
```python
import json
 
from src.model_service import Message, ModelGateway
 
from src.knowledge_extension.rule_explanation.policy_structuring.models import MedicalInsuranceRule
from src.knowledge_extension.rule_explanation.policy_structuring.prompts import (
    RULE_EXTRACTION_SYSTEM_PROMPT,
    RULE_EXTRACTION_USER_PROMPT_TEMPLATE,
)
 
 
def _safe_json_loads(text: str) -> dict:
    t = (text or "").strip()
    if not t:
        return {}
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        start = t.find("{")
        end = t.rfind("}")
        if start >= 0 and end > start:
            return json.loads(t[start : end + 1])
        raise
 
 
def extract_rule_candidates(
    gateway: ModelGateway,
    clause_text: str,
    chunk_id: str,
    document_title: str,
    source_url: str,
    publish_date: str,
    model_type: str = "llm",
    scene: str = "policy_rule_extraction",
) -> list[MedicalInsuranceRule]:
    user_prompt = RULE_EXTRACTION_USER_PROMPT_TEMPLATE.format(
        clause_text=clause_text,
        chunk_id=chunk_id,
        document_title=document_title,
        source_url=source_url,
        publish_date=publish_date,
    )
    resp = gateway.generate(
        messages=[
            Message(role="system", content=RULE_EXTRACTION_SYSTEM_PROMPT),
            Message(role="user", content=user_prompt),
        ],
        model_type=model_type,
        scene=scene,
    )
    data = _safe_json_loads(resp.content)
    if not data:
        return []
    rule = MedicalInsuranceRule.model_validate(data)
    return [rule]
```
 
- [ ] **Step 5: Implement validator for MVP constraints**
 
```python
from src.knowledge_extension.rule_explanation.policy_structuring.enums import ReviewStatus, RuleType
from src.knowledge_extension.rule_explanation.policy_structuring.models import MedicalInsuranceRule
 
 
def validate_rule(rule: MedicalInsuranceRule) -> tuple[bool, list[str]]:
    errors: list[str] = []
 
    if rule.rule_type is RuleType.DEDUCTIBLE_RULE:
        if "deductible_amount" not in rule.calculation and "deductible" not in rule.calculation:
            errors.append("deductible_rule 缺少 calculation.deductible_amount（或 deductible）")
        if "hospitalization_count" not in rule.applicable_condition:
            errors.append("deductible_rule 缺少 applicable_condition.hospitalization_count")
 
    if rule.rule_type is RuleType.PERIOD_RULE:
        cycle_days = rule.period_rule.get("cycle_days")
        if cycle_days is None:
            errors.append("period_rule 缺少 period_rule.cycle_days")
        elif not isinstance(cycle_days, int) or cycle_days <= 0:
            errors.append("period_rule.period_rule.cycle_days 必须是正整数")
 
    if not rule.source_evidence.original_text.strip():
        errors.append("source_evidence.original_text 不能为空")
 
    ok = not errors
    if ok and rule.review_status is ReviewStatus.PENDING:
        rule.review_status = ReviewStatus.VALIDATED
    return ok, errors
```
 
- [ ] **Step 6: Run unit tests**
 
Run: `python -m pytest src/tests/unit/knowledge_extension/test_policy_structuring.py -v`  
Expected: PASS
 
- [ ] **Step 7: Commit**
 
```bash
git add src/knowledge_extension/rule_explanation/policy_structuring/prompts.py src/knowledge_extension/rule_explanation/policy_structuring/rule_extractor.py src/knowledge_extension/rule_explanation/policy_structuring/rule_validator.py src/tests/unit/knowledge_extension/test_policy_structuring.py
git commit -m "feat: add model-based rule extraction and validation"
```
 
---
 
### Task 5: 存储层（policy_documents / policy_chunks / rule_candidates / medical_insurance_rules / rule_execution_log）
 
**Files:**
- Create: `src/knowledge_extension/rule_explanation/policy_structuring/storage/ports.py`
- Create: `src/knowledge_extension/rule_explanation/policy_structuring/storage/in_memory.py`
- Create: `src/knowledge_extension/rule_explanation/policy_structuring/storage/postgres.py`
- Test: `src/tests/unit/knowledge_extension/test_policy_structuring.py`
 
- [ ] **Step 1: Add failing tests for in-memory repository**
 
```python
from src.knowledge_extension.rule_explanation.policy_structuring.models import MedicalInsuranceRule, RuleType
from src.knowledge_extension.rule_explanation.policy_structuring.storage.in_memory import InMemoryPolicyRuleRepository
 
 
def test_in_memory_repo_saves_and_lists_rules():
    repo = InMemoryPolicyRuleRepository()
    rule = MedicalInsuranceRule(
        rule_type=RuleType.DEDUCTIBLE_RULE,
        rule_name="第二次及以后住院起付线减半",
        medical_scene="住院",
    )
    rid = repo.save_rule(rule)
    items = repo.list_rules(rule_type="deductible_rule")
    assert rid
    assert any(i.rule_name == "第二次及以后住院起付线减半" for i in items)
```
 
- [ ] **Step 2: Run tests**
 
Run: `python -m pytest src/tests/unit/knowledge_extension/test_policy_structuring.py -v`  
Expected: FAIL with missing repo
 
- [ ] **Step 3: Implement storage ports**
 
```python
from typing import Protocol
 
from src.knowledge_extension.rule_explanation.policy_structuring.models import MedicalInsuranceRule
 
 
class PolicyRuleRepository(Protocol):
    def save_rule(self, rule: MedicalInsuranceRule) -> str: ...
    def get_rule(self, rule_id: str) -> MedicalInsuranceRule | None: ...
    def list_rules(self, rule_type: str | None = None) -> list[MedicalInsuranceRule]: ...
```
 
- [ ] **Step 4: Implement in-memory repo**
 
```python
from uuid import uuid4
 
from src.knowledge_extension.rule_explanation.policy_structuring.models import MedicalInsuranceRule
from src.knowledge_extension.rule_explanation.policy_structuring.storage.ports import PolicyRuleRepository
 
 
class InMemoryPolicyRuleRepository(PolicyRuleRepository):
    def __init__(self):
        self._rules: dict[str, MedicalInsuranceRule] = {}
 
    def save_rule(self, rule: MedicalInsuranceRule) -> str:
        rid = rule.rule_code or f"mir-{uuid4().hex[:12]}"
        stored = rule.model_copy(deep=True)
        stored.rule_code = rid
        self._rules[rid] = stored
        return rid
 
    def get_rule(self, rule_id: str) -> MedicalInsuranceRule | None:
        r = self._rules.get(rule_id)
        return r.model_copy(deep=True) if r else None
 
    def list_rules(self, rule_type: str | None = None) -> list[MedicalInsuranceRule]:
        items = list(self._rules.values())
        if rule_type:
            items = [i for i in items if i.rule_type.value == rule_type]
        return [i.model_copy(deep=True) for i in items]
```
 
- [ ] **Step 5: Implement Postgres schema + minimal CRUD（对齐 PostgreSQLClient 模式）**
 
```python
import json
from typing import Any
from uuid import uuid4
 
from src.config.production import DATABASE_URL
from src.data_platform.storage.postgresql.client import PostgreSQLClient
from src.knowledge_extension.rule_explanation.policy_structuring.models import MedicalInsuranceRule
 
 
_DDL = """
CREATE TABLE IF NOT EXISTS policy_documents (
  document_id VARCHAR(128) PRIMARY KEY,
  title TEXT NOT NULL,
  publish_date VARCHAR(32),
  source_url TEXT,
  document_type VARCHAR(64),
  content TEXT,
  attachments JSONB DEFAULT '[]',
  metadata JSONB DEFAULT '{}',
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS policy_chunks (
  chunk_id VARCHAR(160) PRIMARY KEY,
  document_id VARCHAR(128) NOT NULL,
  path TEXT,
  heading TEXT,
  text TEXT,
  order_index INT,
  clause_type VARCHAR(64),
  metadata JSONB DEFAULT '{}',
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_policy_chunks_doc ON policy_chunks(document_id);
CREATE TABLE IF NOT EXISTS rule_candidates (
  candidate_id VARCHAR(128) PRIMARY KEY,
  chunk_id VARCHAR(160) NOT NULL,
  rule_type VARCHAR(64),
  candidate_json JSONB NOT NULL,
  confidence FLOAT DEFAULT 0,
  review_status VARCHAR(32) DEFAULT 'pending',
  metadata JSONB DEFAULT '{}',
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_rule_candidates_chunk ON rule_candidates(chunk_id);
CREATE TABLE IF NOT EXISTS medical_insurance_rules (
  rule_id VARCHAR(128) PRIMARY KEY,
  rule_code VARCHAR(128),
  rule_name TEXT,
  rule_type VARCHAR(64),
  region VARCHAR(64),
  insurance_type VARCHAR(64),
  person_type VARCHAR(64),
  medical_scene VARCHAR(64),
  hospital_level VARCHAR(64),
  applicable_condition JSONB DEFAULT '{}',
  calculation JSONB DEFAULT '{}',
  result JSONB DEFAULT '{}',
  period_rule JSONB DEFAULT '{}',
  exception_rule JSONB DEFAULT '[]',
  source_evidence JSONB DEFAULT '{}',
  confidence FLOAT DEFAULT 0,
  review_status VARCHAR(32) DEFAULT 'pending',
  version VARCHAR(64) DEFAULT 'draft',
  enabled BOOLEAN DEFAULT TRUE,
  metadata JSONB DEFAULT '{}',
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_med_rules_type ON medical_insurance_rules(rule_type);
CREATE TABLE IF NOT EXISTS rule_execution_log (
  execution_id VARCHAR(128) PRIMARY KEY,
  rule_id VARCHAR(128),
  patient_id VARCHAR(64),
  encounter_id VARCHAR(64),
  input_context JSONB DEFAULT '{}',
  calculation_steps JSONB DEFAULT '[]',
  output_result JSONB DEFAULT '{}',
  explanation TEXT,
  citations JSONB DEFAULT '[]',
  status VARCHAR(32) DEFAULT 'success',
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""
 
 
class PostgresPolicyRuleRepository:
    def __init__(self, database_url: str | None = None):
        self._database_url = database_url or DATABASE_URL
        self._client: PostgreSQLClient | None = None
 
    def _get_client(self) -> PostgreSQLClient:
        if self._client is None:
            self._client = PostgreSQLClient(self._database_url)
            self._client.execute(_DDL)
        return self._client
 
    def save_rule(self, rule: MedicalInsuranceRule) -> str:
        client = self._get_client()
        rid = rule.rule_code or f"mir-{uuid4().hex[:12]}"
        r = rule.model_copy(deep=True)
        r.rule_code = rid
        sql = """
          INSERT INTO medical_insurance_rules (
            rule_id, rule_code, rule_name, rule_type, region, insurance_type, person_type,
            medical_scene, hospital_level, applicable_condition, calculation, result,
            period_rule, exception_rule, source_evidence, confidence, review_status, version, enabled, metadata, updated_at
          ) VALUES (
            %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,CURRENT_TIMESTAMP
          )
          ON CONFLICT (rule_id) DO UPDATE SET
            rule_code=EXCLUDED.rule_code, rule_name=EXCLUDED.rule_name, rule_type=EXCLUDED.rule_type,
            region=EXCLUDED.region, insurance_type=EXCLUDED.insurance_type, person_type=EXCLUDED.person_type,
            medical_scene=EXCLUDED.medical_scene, hospital_level=EXCLUDED.hospital_level,
            applicable_condition=EXCLUDED.applicable_condition, calculation=EXCLUDED.calculation,
            result=EXCLUDED.result, period_rule=EXCLUDED.period_rule, exception_rule=EXCLUDED.exception_rule,
            source_evidence=EXCLUDED.source_evidence, confidence=EXCLUDED.confidence,
            review_status=EXCLUDED.review_status, version=EXCLUDED.version, enabled=EXCLUDED.enabled,
            metadata=EXCLUDED.metadata, updated_at=CURRENT_TIMESTAMP
        """
        client.execute(sql, (
            rid, rid, r.rule_name, r.rule_type.value, r.region, r.insurance_type, r.person_type,
            r.medical_scene, r.hospital_level,
            json.dumps(r.applicable_condition), json.dumps(r.calculation), json.dumps(r.result),
            json.dumps(r.period_rule), json.dumps(r.exception_rule), json.dumps(r.source_evidence.model_dump()),
            r.confidence, r.review_status.value, r.version, r.enabled, json.dumps({}),
        ))
        return rid
 
    def get_rule(self, rule_id: str) -> MedicalInsuranceRule | None:
        client = self._get_client()
        rows = client.execute("SELECT * FROM medical_insurance_rules WHERE rule_id = %s", (rule_id,))
        if not rows:
            return None
        return MedicalInsuranceRule.model_validate(rows[0])
 
    def list_rules(self, rule_type: str | None = None) -> list[MedicalInsuranceRule]:
        client = self._get_client()
        if rule_type:
            rows = client.execute(
                "SELECT * FROM medical_insurance_rules WHERE rule_type = %s ORDER BY rule_id",
                (rule_type,),
            )
        else:
            rows = client.execute("SELECT * FROM medical_insurance_rules ORDER BY rule_id", ())
        return [MedicalInsuranceRule.model_validate(r) for r in rows]
```
 
- [ ] **Step 6: Run unit tests**
 
Run: `python -m pytest src/tests/unit/knowledge_extension/test_policy_structuring.py -v`  
Expected: PASS (仅覆盖 in-memory；postgres 通过 integration 测试与 mock 覆盖)
 
- [ ] **Step 7: Commit**
 
```bash
git add src/knowledge_extension/rule_explanation/policy_structuring/storage src/tests/unit/knowledge_extension/test_policy_structuring.py
git commit -m "feat: add policy rule repositories (memory/postgres) and schema ddl"
```
 
---
 
### Task 6: Pipeline Service（清洗→切分→分类→抽取→校验→落库候选/规则）
 
**Files:**
- Create: `src/knowledge_extension/rule_explanation/policy_structuring/service.py`
- Test: `src/tests/unit/knowledge_extension/test_policy_structuring.py`
 
- [ ] **Step 1: Add failing unit test for service end-to-end (mock gateway)**
 
```python
from unittest.mock import MagicMock
 
from src.knowledge_extension.rule_explanation.policy_structuring.service import PolicyStructuringService
from src.knowledge_extension.rule_explanation.policy_structuring.storage.in_memory import InMemoryPolicyRuleRepository
 
 
def test_service_runs_pipeline_and_saves_rule():
    gateway = MagicMock()
    gateway.generate.return_value.content = '{"rule_type":"period_rule","rule_name":"住院治疗90天周期","medical_scene":"住院","period_rule":{"cycle_days":90},"source_evidence":{"original_text":"住院治疗每90天为一个结算周期"}}'
 
    repo = InMemoryPolicyRuleRepository()
    svc = PolicyStructuringService(rule_repo=repo, gateway=gateway)
 
    out = svc.structuring_from_document_text(
        document_id="doc-1",
        document_title="测试政策",
        publish_date="2026-01-01",
        source_url="http://example.com",
        text="第二条 住院治疗每90天为一个结算周期。",
    )
    assert out["rules_saved"] >= 1
```
 
- [ ] **Step 2: Run tests**
 
Run: `python -m pytest src/tests/unit/knowledge_extension/test_policy_structuring.py -v`  
Expected: FAIL with missing service
 
- [ ] **Step 3: Implement service**
 
```python
from src.model_service import ModelGateway
 
from src.knowledge_extension.rule_explanation.policy_structuring.clause_classifier import classify_clause
from src.knowledge_extension.rule_explanation.policy_structuring.clause_splitter import split_policy_clauses
from src.knowledge_extension.rule_explanation.policy_structuring.rule_extractor import extract_rule_candidates
from src.knowledge_extension.rule_explanation.policy_structuring.rule_validator import validate_rule
from src.knowledge_extension.rule_explanation.policy_structuring.storage.ports import PolicyRuleRepository
 
 
class PolicyStructuringService:
    def __init__(self, rule_repo: PolicyRuleRepository, gateway: ModelGateway | None = None):
        self._rule_repo = rule_repo
        self._gateway = gateway or ModelGateway()
 
    def structuring_from_document_text(
        self,
        document_id: str,
        document_title: str,
        publish_date: str,
        source_url: str,
        text: str,
    ) -> dict:
        chunks = split_policy_clauses(text, document_id=document_id)
        rules_saved = 0
        candidates_total = 0
        errors_total: list[str] = []
 
        for c in chunks:
            clause_type = classify_clause(c.text)
            if clause_type not in ("deductible", "period"):
                continue
            rules = extract_rule_candidates(
                gateway=self._gateway,
                clause_text=c.text,
                chunk_id=c.chunk_id,
                document_title=document_title,
                source_url=source_url,
                publish_date=publish_date,
            )
            candidates_total += len(rules)
            for r in rules:
                ok, errs = validate_rule(r)
                if not ok:
                    errors_total.extend(errs)
                    continue
                self._rule_repo.save_rule(r)
                rules_saved += 1
 
        return {
            "document_id": document_id,
            "chunks": len(chunks),
            "candidates_total": candidates_total,
            "rules_saved": rules_saved,
            "validation_errors": errors_total,
        }
```
 
- [ ] **Step 4: Run unit tests**
 
Run: `python -m pytest src/tests/unit/knowledge_extension/test_policy_structuring.py -v`  
Expected: PASS
 
- [ ] **Step 5: Commit**
 
```bash
git add src/knowledge_extension/rule_explanation/policy_structuring/service.py src/tests/unit/knowledge_extension/test_policy_structuring.py
git commit -m "feat: add policy structuring pipeline service"
```
 
---
 
### Task 7: Demo API（policy structuring + rules query）
 
**Files:**
- Create: `src/runtime/api/policy_structuring_routes.py`
- Modify: `src/runtime/api/app.py`
- Modify: `src/runtime/api/schemas.py`
- Test: `src/tests/integration/api/test_policy_structuring_routes.py`
 
- [ ] **Step 1: Add failing API tests (FastAPI TestClient)**
 
```python
from unittest.mock import MagicMock, patch
 
from fastapi.testclient import TestClient
 
from src.runtime.api.app import create_app
 
 
PREFIX = "/api/v1/medical-insurance-ai-agent"
client = TestClient(create_app())
 
 
def test_structuring_demo_endpoint_returns_pipeline_stats():
    with patch("src.knowledge_extension.rule_explanation.policy_structuring.service.ModelGateway") as mg:
        gw = MagicMock()
        gw.generate.return_value.content = '{"rule_type":"period_rule","rule_name":"住院治疗90天周期","medical_scene":"住院","period_rule":{"cycle_days":90},"source_evidence":{"original_text":"住院治疗每90天为一个结算周期"}}'
        mg.return_value = gw
        resp = client.post(f"{PREFIX}/policy-structuring/demo", json={
            "document_id": "doc-1",
            "document_title": "测试政策",
            "publish_date": "2026-01-01",
            "source_url": "http://example.com",
            "text": "第二条 住院治疗每90天为一个结算周期。",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["rules_saved"] >= 1
 
 
def test_list_structured_rules_endpoint_returns_list():
    resp = client.get(f"{PREFIX}/policy-structuring/rules")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
```
 
- [ ] **Step 2: Run integration test**
 
Run: `python -m pytest src/tests/integration/api/test_policy_structuring_routes.py -v`  
Expected: FAIL with 404 or missing router
 
- [ ] **Step 3: Add request/response schemas**
 
```python
from pydantic import BaseModel
 
 
class PolicyStructuringDemoRequest(BaseModel):
    document_id: str
    document_title: str
    publish_date: str = ""
    source_url: str = ""
    text: str
```
 
- [ ] **Step 4: Implement router (in-memory repo for demo; production可切换到 PostgresPolicyRuleRepository)**
 
```python
from fastapi import APIRouter, Query
 
from src.knowledge_extension.rule_explanation.policy_structuring.service import PolicyStructuringService
from src.knowledge_extension.rule_explanation.policy_structuring.storage.in_memory import InMemoryPolicyRuleRepository
from src.runtime.api.schemas import PolicyStructuringDemoRequest
 
 
router = APIRouter()
_repo = InMemoryPolicyRuleRepository()
_svc = PolicyStructuringService(rule_repo=_repo)
 
 
@router.post("/policy-structuring/demo")
def policy_structuring_demo(request: PolicyStructuringDemoRequest) -> dict:
    return _svc.structuring_from_document_text(
        document_id=request.document_id,
        document_title=request.document_title,
        publish_date=request.publish_date,
        source_url=request.source_url,
        text=request.text,
    )
 
 
@router.get("/policy-structuring/rules")
def list_structured_rules(rule_type: str | None = Query(None)) -> list[dict]:
    return [r.model_dump() for r in _repo.list_rules(rule_type=rule_type)]
```
 
- [ ] **Step 5: Register router in app**
 
```python
from src.runtime.api.policy_structuring_routes import router as policy_structuring_router
 
app.include_router(policy_structuring_router, prefix="/api/v1/medical-insurance-ai-agent")
```
 
- [ ] **Step 6: Run integration test again**
 
Run: `python -m pytest src/tests/integration/api/test_policy_structuring_routes.py -v`  
Expected: PASS
 
- [ ] **Step 7: Commit**
 
```bash
git add src/runtime/api/policy_structuring_routes.py src/runtime/api/app.py src/runtime/api/schemas.py src/tests/integration/api/test_policy_structuring_routes.py
git commit -m "feat: add policy structuring demo api"
```
 
---
 
## Verification (Hard Order)
 
1) 单元测试（仅本模块）  
Run: `python -m pytest src/tests/unit/knowledge_extension -v`
 
2) API 测试  
Run: `python -m pytest src/tests/integration/api/test_policy_structuring_routes.py -v`
 
3) Flow 测试（本阶段不新增 flow 用例；若新增路由被 flow 覆盖则跑全量）  
Run: `python -m pytest src/tests/integration/flow -v`
 
---
 
## Execution Handoff
 
Plan complete and saved to `docs/superpowers/plans/2026-05-14-policy-rule-structuring-mvp.md`. Two execution options:
 
1. Subagent-Driven (recommended) — I dispatch a fresh subagent per task, review between tasks
2. Inline Execution — Execute tasks in this session with checkpoints
