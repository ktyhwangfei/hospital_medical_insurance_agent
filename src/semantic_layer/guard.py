"""院区（租户）隔离守卫：语义绑定不得跨院区使用。

一套产品多院复用的接缝：`hospital_code` 为空 = 平台通用绑定（多院共用）；
非空 = 院区专属绑定，只允许在同院区部署内使用。跨院区使用即拒（fail-closed），
避免 A 院的字段映射/数据源被 B 院静默复用。
"""

from __future__ import annotations

from typing import Any

from src.shared.hospital_scope import current_hospital_code


class HospitalScopeViolationError(ValueError):
    """语义绑定与当前部署院区不匹配。"""


def assert_hospital_scope(datasets: Any) -> None:
    """校验数据集绑定的院区归属；不匹配抛 HospitalScopeViolationError。"""
    current = current_hospital_code()
    for item in datasets:
        if item.hospital_code and item.hospital_code != current:
            raise HospitalScopeViolationError(
                f"数据集 {item.dataset_code} 属院区 {item.hospital_code}，"
                f"当前部署院区为 {current or '未配置'}，不得跨院区使用该语义绑定"
            )
