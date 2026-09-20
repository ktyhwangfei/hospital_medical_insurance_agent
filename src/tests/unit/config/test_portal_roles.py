"""门户角色权限矩阵测试 — Issue #75（矩阵 = 治理接口 scope 词汇表全集收口）。"""
from __future__ import annotations

from src.config.security_policy.portal_roles import (
    ALL_PORTAL_PERMISSIONS,
    PORTAL_ROLE_PERMISSIONS,
    permissions_for_role,
)


def test_admin_covers_all_permissions():
    assert set(PORTAL_ROLE_PERMISSIONS["admin"]) == set(ALL_PORTAL_PERMISSIONS)


def test_role_matrix_covers_existing_scope_vocabulary():
    # 与后端各路由实际校验的 scope 对齐（新增治理 scope 必须同步这里与 admin 角色）
    expected = {
        "workflow:read", "workflow:write",
        "ops:read", "ops:write",
        "question_library:read", "question_library:write",
        "data_governance:read", "data_governance:write",
        "semantic:review",
        "flow:read",
        "model_governance:read", "model_governance:write",
        "model_governance:review", "model_governance:publish",
        "skill:evaluate", "skill:release:test",
        "policy_qa:ask",
    }
    assert expected == set(ALL_PORTAL_PERMISSIONS)


def test_minimal_roles_grant_minimal_permissions():
    # policy_qa:ask 是业务入口，所有角色默认持有（P1）
    assert permissions_for_role("reviewer") == ["policy_qa:ask", "semantic:review"]
    assert "data_governance:write" not in permissions_for_role("ops_admin")
    assert "workflow:write" in permissions_for_role("governance_admin")
    assert "semantic:review" in permissions_for_role("knowledge_admin")


def test_unknown_role_expands_to_empty():
    assert permissions_for_role("no-such-role") == []
