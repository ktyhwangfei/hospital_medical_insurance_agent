"""门户角色 → 权限矩阵（Issue #75 最小切片）。

矩阵即现有治理接口 scope 词汇表的全集收口，不新增 scope 语义。
签发时角色展开为 permissions 写入 JWT；后端校验只认 token 内 permissions。
"""
from __future__ import annotations

# 治理权限全集（后端各路由实际校验的 scope）
WORKFLOW_PERMISSIONS = ["workflow:read", "workflow:write"]
OPS_PERMISSIONS = ["ops:read", "ops:write"]
QUESTION_LIBRARY_PERMISSIONS = ["question_library:read", "question_library:write"]
DATA_GOVERNANCE_PERMISSIONS = ["data_governance:read", "data_governance:write"]
SEMANTIC_REVIEW_PERMISSIONS = ["semantic:review"]
FLOW_PERMISSIONS = ["flow:read"]
MODEL_GOVERNANCE_PERMISSIONS = [
    "model_governance:read",
    "model_governance:write",
    "model_governance:review",
    "model_governance:publish",
]
SKILL_PERMISSIONS = ["skill:evaluate", "skill:release:test"]
# 政策问答主链路（/policy-qa/*）：业务入口，所有门户角色默认持有（P1 鉴权）
POLICY_QA_PERMISSIONS = ["policy_qa:ask"]

ALL_PORTAL_PERMISSIONS: tuple[str, ...] = tuple(
    sorted(
        WORKFLOW_PERMISSIONS
        + OPS_PERMISSIONS
        + QUESTION_LIBRARY_PERMISSIONS
        + DATA_GOVERNANCE_PERMISSIONS
        + SEMANTIC_REVIEW_PERMISSIONS
        + FLOW_PERMISSIONS
        + MODEL_GOVERNANCE_PERMISSIONS
        + SKILL_PERMISSIONS
        + POLICY_QA_PERMISSIONS
    )
)

# 角色 → 权限映射（一个账号一个角色，#43 三级矩阵在此基础上扩展）
PORTAL_ROLE_PERMISSIONS: dict[str, tuple[str, ...]] = {
    "admin": ALL_PORTAL_PERMISSIONS,
    "governance_admin": tuple(
        sorted(
            DATA_GOVERNANCE_PERMISSIONS
            + WORKFLOW_PERMISSIONS
            + FLOW_PERMISSIONS
            + POLICY_QA_PERMISSIONS
        )
    ),
    "ops_admin": tuple(sorted(OPS_PERMISSIONS + POLICY_QA_PERMISSIONS)),
    "knowledge_admin": tuple(
        sorted(
            QUESTION_LIBRARY_PERMISSIONS
            + SEMANTIC_REVIEW_PERMISSIONS
            + POLICY_QA_PERMISSIONS
        )
    ),
    "reviewer": tuple(sorted(SEMANTIC_REVIEW_PERMISSIONS + POLICY_QA_PERMISSIONS)),
    "skill_admin": tuple(
        sorted(
            SKILL_PERMISSIONS + MODEL_GOVERNANCE_PERMISSIONS + POLICY_QA_PERMISSIONS
        )
    ),
}


def permissions_for_role(role: str) -> list[str]:
    """角色展开为权限列表；未知角色返回空（签发侧应视为配置错误）。"""
    return list(PORTAL_ROLE_PERMISSIONS.get(role, ()))
