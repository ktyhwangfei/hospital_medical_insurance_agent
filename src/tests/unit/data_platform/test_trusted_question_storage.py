"""可信问题库存储单元测试（Issue #37 Slice 1）。

- 内存适配器：端口契约全行为覆盖（CRUD/乐观锁/状态机/同义表达运营/列表过滤分页）。
- PG 适配器：DDL 双写防回归（INSERT 列 ⊆ CREATE+ALTER 列，且 CREATE 列逐列有 ALTER），
  不连真实库；真实 PG 行为验证在开发完成验证流程中单独执行并标注环境依赖。
"""

from __future__ import annotations

import inspect
import re
from datetime import datetime, timedelta, timezone

import pytest

from src.data_platform.storage.trusted_question.trusted_question_in_memory import (
    InMemoryTrustedQuestionStorage,
)
from src.data_platform.storage.trusted_question.trusted_question_ports import (
    TrustedQuestionConflictError,
    TrustedQuestionNotFoundError,
)
from src.data_platform.storage.trusted_question.trusted_question_postgres import (
    TRUSTED_QUESTION_COLUMNS_DDL,
    TRUSTED_QUESTION_TABLE_SCHEMA,
    PostgresTrustedQuestionStorage,
)
from src.domain.trusted_qa.models import (
    TrustedQuestion,
    TrustedQuestionInvalidTransitionError,
    TrustedQuestionStatus,
    TrustedQuestionSynonym,
)

_BASE_TIME = datetime(2026, 9, 7, 8, 0, 0, tzinfo=timezone.utc)


def _make_question(
    question_id: str = "tq_001",
    *,
    standard_question: str = "门诊统筹报销比例是多少",
    synonyms: list[TrustedQuestionSynonym] | None = None,
    status: TrustedQuestionStatus = TrustedQuestionStatus.DRAFT,
    version: int = 1,
    created_at: datetime | None = None,
) -> TrustedQuestion:
    now = created_at or _BASE_TIME
    return TrustedQuestion(
        question_id=question_id,
        standard_question=standard_question,
        synonyms=synonyms or [],
        applicable_roles=["CASHIER"],
        metric_codes=["payment_ratio"],
        query_plan={"plan_hash": "abc123", "branches": []},
        expected_result_traits={"row_count": 1},
        status=status,
        created_by="tester",
        version=version,
        created_at=now,
        updated_at=now,
    )


@pytest.fixture()
def storage() -> InMemoryTrustedQuestionStorage:
    return InMemoryTrustedQuestionStorage()


class TestSaveAndGet:
    def test_save_and_get_roundtrip(self, storage: InMemoryTrustedQuestionStorage) -> None:
        saved = storage.save_question(_make_question())
        fetched = storage.get_question("tq_001")
        assert fetched is not None
        assert fetched.standard_question == "门诊统筹报销比例是多少"
        assert fetched.metric_codes == ["payment_ratio"]
        assert fetched.query_plan == {"plan_hash": "abc123", "branches": []}
        # 深拷贝：返回值不是同一对象
        assert saved is not fetched

    def test_save_duplicate_raises_conflict(
        self, storage: InMemoryTrustedQuestionStorage
    ) -> None:
        storage.save_question(_make_question())
        with pytest.raises(TrustedQuestionConflictError):
            storage.save_question(_make_question())

    def test_get_missing_returns_none(
        self, storage: InMemoryTrustedQuestionStorage
    ) -> None:
        assert storage.get_question("tq_missing") is None


class TestListQuestions:
    def test_filter_by_status(self, storage: InMemoryTrustedQuestionStorage) -> None:
        storage.save_question(_make_question("tq_a"))
        storage.save_question(
            _make_question("tq_b", status=TrustedQuestionStatus.ACTIVE)
        )
        drafts = storage.list_questions(status=TrustedQuestionStatus.DRAFT)
        assert [q.question_id for q in drafts] == ["tq_a"]

    def test_keyword_matches_standard_question(
        self, storage: InMemoryTrustedQuestionStorage
    ) -> None:
        storage.save_question(_make_question("tq_a", standard_question="门诊报销比例"))
        storage.save_question(_make_question("tq_b", standard_question="住院起付线"))
        hits = storage.list_questions(keyword="门诊")
        assert [q.question_id for q in hits] == ["tq_a"]

    def test_keyword_matches_synonym(
        self, storage: InMemoryTrustedQuestionStorage
    ) -> None:
        storage.save_question(
            _make_question(
                "tq_a",
                synonyms=[TrustedQuestionSynonym(expression="统筹自付怎么算")],
            )
        )
        hits = storage.list_questions(keyword="统筹自付")
        assert [q.question_id for q in hits] == ["tq_a"]

    def test_order_and_pagination(self, storage: InMemoryTrustedQuestionStorage) -> None:
        for i in range(3):
            storage.save_question(
                _make_question(
                    f"tq_{i}", created_at=_BASE_TIME + timedelta(minutes=i)
                )
            )
        page1 = storage.list_questions(limit=2, offset=0)
        page2 = storage.list_questions(limit=2, offset=2)
        # created_at 倒序：最新在前
        assert [q.question_id for q in page1] == ["tq_2", "tq_1"]
        assert [q.question_id for q in page2] == ["tq_0"]


class TestUpdateQuestion:
    def test_update_success_increments_version(
        self, storage: InMemoryTrustedQuestionStorage
    ) -> None:
        storage.save_question(_make_question())
        edited = _make_question(standard_question="门诊统筹支付比例是多少", version=2)
        updated = storage.update_question(edited, expected_version=1)
        assert updated.version == 2
        assert updated.standard_question == "门诊统筹支付比例是多少"

    def test_update_stale_version_conflict(
        self, storage: InMemoryTrustedQuestionStorage
    ) -> None:
        storage.save_question(_make_question())
        edited = _make_question(version=2)
        with pytest.raises(TrustedQuestionConflictError):
            storage.update_question(edited, expected_version=99)

    def test_update_version_must_increment(
        self, storage: InMemoryTrustedQuestionStorage
    ) -> None:
        storage.save_question(_make_question())
        not_incremented = _make_question(version=1)
        with pytest.raises(TrustedQuestionConflictError):
            storage.update_question(not_incremented, expected_version=1)

    def test_update_missing_raises_not_found(
        self, storage: InMemoryTrustedQuestionStorage
    ) -> None:
        with pytest.raises(TrustedQuestionNotFoundError):
            storage.update_question(_make_question(version=2), expected_version=1)

    def test_update_active_question_rejected(
        self, storage: InMemoryTrustedQuestionStorage
    ) -> None:
        storage.save_question(
            _make_question(status=TrustedQuestionStatus.ACTIVE)
        )
        edited = _make_question(status=TrustedQuestionStatus.ACTIVE, version=2)
        with pytest.raises(TrustedQuestionInvalidTransitionError):
            storage.update_question(edited, expected_version=1)


class TestTransitionStatus:
    def test_full_review_flow(self, storage: InMemoryTrustedQuestionStorage) -> None:
        storage.save_question(_make_question())
        submitted = storage.transition_status(
            "tq_001", TrustedQuestionStatus.PENDING_REVIEW, expected_version=1
        )
        assert submitted.status == TrustedQuestionStatus.PENDING_REVIEW
        assert submitted.version == 2
        approved = storage.transition_status(
            "tq_001",
            TrustedQuestionStatus.ACTIVE,
            expected_version=2,
            operator="reviewer-1",
        )
        assert approved.status == TrustedQuestionStatus.ACTIVE
        assert approved.reviewed_by == "reviewer-1"
        assert approved.reviewed_at is not None
        retired = storage.transition_status(
            "tq_001", TrustedQuestionStatus.RETIRED, expected_version=3
        )
        assert retired.status == TrustedQuestionStatus.RETIRED

    def test_reject_returns_to_draft_with_note(
        self, storage: InMemoryTrustedQuestionStorage
    ) -> None:
        storage.save_question(_make_question())
        storage.transition_status(
            "tq_001", TrustedQuestionStatus.PENDING_REVIEW, expected_version=1
        )
        rejected = storage.transition_status(
            "tq_001",
            TrustedQuestionStatus.DRAFT,
            expected_version=2,
            operator="reviewer-1",
            review_note="查询计划缺失",
        )
        assert rejected.status == TrustedQuestionStatus.DRAFT
        assert rejected.reviewed_by == "reviewer-1"
        assert rejected.review_note == "查询计划缺失"

    def test_invalid_transition_raises(
        self, storage: InMemoryTrustedQuestionStorage
    ) -> None:
        storage.save_question(_make_question())
        with pytest.raises(TrustedQuestionInvalidTransitionError):
            storage.transition_status(
                "tq_001", TrustedQuestionStatus.ACTIVE, expected_version=1
            )

    def test_transition_stale_version_conflict(
        self, storage: InMemoryTrustedQuestionStorage
    ) -> None:
        storage.save_question(_make_question())
        with pytest.raises(TrustedQuestionConflictError):
            storage.transition_status(
                "tq_001", TrustedQuestionStatus.PENDING_REVIEW, expected_version=99
            )

    def test_transition_missing_raises_not_found(
        self, storage: InMemoryTrustedQuestionStorage
    ) -> None:
        with pytest.raises(TrustedQuestionNotFoundError):
            storage.transition_status(
                "tq_missing", TrustedQuestionStatus.PENDING_REVIEW, expected_version=1
            )


class TestSynonymOperations:
    def test_add_synonym_records_operator(
        self, storage: InMemoryTrustedQuestionStorage
    ) -> None:
        storage.save_question(_make_question())
        updated = storage.add_synonym(
            "tq_001",
            TrustedQuestionSynonym(expression="门诊报销多少", added_by="ops-1"),
            expected_version=1,
        )
        assert len(updated.synonyms) == 1
        assert updated.synonyms[0].expression == "门诊报销多少"
        assert updated.synonyms[0].added_by == "ops-1"
        assert updated.version == 2

    def test_add_synonym_dedupes_by_expression(
        self, storage: InMemoryTrustedQuestionStorage
    ) -> None:
        storage.save_question(_make_question())
        syn = TrustedQuestionSynonym(expression="门诊报销多少")
        storage.add_synonym("tq_001", syn, expected_version=1)
        updated = storage.add_synonym("tq_001", syn, expected_version=2)
        assert len(updated.synonyms) == 1

    def test_add_synonym_allowed_on_active(
        self, storage: InMemoryTrustedQuestionStorage
    ) -> None:
        """同义表达运营不受内容编辑状态限制，active 也可运营。"""
        storage.save_question(_make_question(status=TrustedQuestionStatus.ACTIVE))
        updated = storage.add_synonym(
            "tq_001",
            TrustedQuestionSynonym(expression="门诊报销多少"),
            expected_version=1,
        )
        assert len(updated.synonyms) == 1

    def test_remove_synonym(self, storage: InMemoryTrustedQuestionStorage) -> None:
        storage.save_question(_make_question())
        storage.add_synonym(
            "tq_001", TrustedQuestionSynonym(expression="门诊报销多少"),
            expected_version=1,
        )
        updated = storage.remove_synonym(
            "tq_001", "门诊报销多少", expected_version=2
        )
        assert updated.synonyms == []
        assert updated.version == 3

    def test_remove_missing_synonym_raises(
        self, storage: InMemoryTrustedQuestionStorage
    ) -> None:
        storage.save_question(_make_question())
        with pytest.raises(TrustedQuestionNotFoundError):
            storage.remove_synonym("tq_001", "不存在的表达", expected_version=1)


class TestFactory:
    def test_memory_switch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from src.data_platform.storage.trusted_question.trusted_question_factory import (
            get_trusted_question_storage,
        )

        get_trusted_question_storage.cache_clear()
        monkeypatch.setenv("USE_MEMORY_STORAGE", "1")
        try:
            assert isinstance(
                get_trusted_question_storage(), InMemoryTrustedQuestionStorage
            )
        finally:
            monkeypatch.delenv("USE_MEMORY_STORAGE")
            get_trusted_question_storage.cache_clear()

    def test_default_is_postgres(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from src.data_platform.storage.trusted_question.trusted_question_factory import (
            get_trusted_question_storage,
        )

        get_trusted_question_storage.cache_clear()
        monkeypatch.delenv("USE_MEMORY_STORAGE", raising=False)
        try:
            assert isinstance(
                get_trusted_question_storage(), PostgresTrustedQuestionStorage
            )
        finally:
            get_trusted_question_storage.cache_clear()


class TestPostgresDdlDoubleWrite:
    """防回归：INSERT 列必须 ⊆ DDL 列（CREATE + ALTER ADD COLUMN），且 CREATE 列逐列有 ALTER。

    旧库已建表时 CREATE TABLE IF NOT EXISTS 不补列，缺 ALTER 会 UndefinedColumn 500。
    参照 test_skill_eval_runs_insert_columns_covered_by_ddl。
    """

    @staticmethod
    def _create_columns() -> set[str]:
        create_block = re.search(
            r"CREATE TABLE IF NOT EXISTS trusted_questions \((.*?)\)\s*;",
            TRUSTED_QUESTION_TABLE_SCHEMA,
            re.DOTALL,
        )
        assert create_block, "未找到 trusted_questions CREATE TABLE 块"
        cols = set()
        for line in create_block.group(1).splitlines():
            token = line.strip().split()[0] if line.strip() else ""
            if token.isidentifier():
                cols.add(token)
        return cols

    @staticmethod
    def _alter_columns() -> set[str]:
        return set(
            re.findall(
                r"ALTER TABLE trusted_questions\s+ADD COLUMN IF NOT EXISTS (\w+)",
                TRUSTED_QUESTION_COLUMNS_DDL,
            )
        )

    def test_insert_columns_covered_by_ddl(self) -> None:
        ddl_cols = self._create_columns() | self._alter_columns()
        src = inspect.getsource(PostgresTrustedQuestionStorage.save_question)
        insert_match = re.search(
            r"INSERT INTO trusted_questions \(([^)]*)\)", src, re.DOTALL
        )
        assert insert_match, "未找到 save_question INSERT 语句"
        insert_cols = {
            c.strip().split()[0] for c in insert_match.group(1).split(",") if c.strip()
        }
        missing = insert_cols - ddl_cols
        assert not missing, (
            f"save_question INSERT 列未在 DDL（CREATE+ALTER）定义: {missing}。"
            "旧库 CREATE IF NOT EXISTS 不补列，必须配 ALTER ADD COLUMN IF NOT EXISTS。"
        )

    def test_every_create_column_has_alter(self) -> None:
        """双写完整性：CREATE 中每一列都必须有对应的 ALTER ADD COLUMN IF NOT EXISTS。"""
        create_cols = self._create_columns()
        alter_cols = self._alter_columns()
        missing_alter = create_cols - alter_cols
        assert not missing_alter, f"CREATE 列缺少对应 ALTER 双写: {missing_alter}"

    def test_update_columns_covered_by_ddl(self) -> None:
        ddl_cols = self._create_columns() | self._alter_columns()
        src = inspect.getsource(PostgresTrustedQuestionStorage.update_question)
        set_block = re.search(r"SET\s+(.*?)\s+WHERE", src, re.DOTALL)
        assert set_block, "未找到 update_question SET 块"
        set_cols = {
            m.group(1)
            for m in re.finditer(r"(\w+)\s*=", set_block.group(1))
        }
        missing = set_cols - ddl_cols
        assert not missing, f"update_question SET 列未在 DDL 定义: {missing}"
