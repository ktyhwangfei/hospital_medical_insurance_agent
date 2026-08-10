"""回归案例脱敏快照单元测试。"""

from __future__ import annotations

from src.security.desensitization.service import (
    SanitizedSnapshot,
    sanitize_regression_snapshot,
)


def test_sanitize_masks_mainland_id_number() -> None:
    snap = sanitize_regression_snapshot(
        question="患者身份证 110101199003071234 的起付线", answer="", comment=None
    )
    assert "110101199003071234" not in snap.question
    assert "[身份证号]" in snap.question
    assert "起付线" in snap.question


def test_sanitize_masks_mobile_number() -> None:
    snap = sanitize_regression_snapshot(
        question="联系电话 13800138000", answer="", comment=None
    )
    assert "13800138000" not in snap.question
    assert "[手机号]" in snap.question


def test_sanitize_masks_keyword_anchored_identifiers() -> None:
    snap = sanitize_regression_snapshot(
        question="住院号123456，结算号S001，病案号BL002",
        answer="",
        comment=None,
    )
    assert "123456" not in snap.question
    assert "S001" not in snap.question
    assert "BL002" not in snap.question


def test_sanitize_preserves_normal_business_text() -> None:
    snap = sanitize_regression_snapshot(
        question="起付线怎么计算",
        answer="按年度累计计算",
        comment="计算口径不对",
    )
    assert snap.question == "起付线怎么计算"
    assert snap.answer == "按年度累计计算"
    assert snap.comment == "计算口径不对"
    assert snap.masked_patterns == []


def test_sanitize_returns_typed_snapshot() -> None:
    snap = sanitize_regression_snapshot(question="x", answer="y", comment="z")
    assert isinstance(snap, SanitizedSnapshot)
