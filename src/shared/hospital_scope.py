"""部署级院区身份（一套产品多院复用的最小接缝）。

A 形态（一院一套部署）：部署时设 `PLATFORM_HOSPITAL_CODE=HOSP-A`，运行时据此
选择院区级配置（workflow 关键词/启停等）与校验院区专属语义绑定。
B 形态（一套实例多院）需要请求级院区解析，届时把本函数换成从请求上下文取值，
调用方不需要改签名。
"""

from __future__ import annotations

import os


def current_hospital_code() -> str:
    """当前生效的院区编码；空串 = 平台默认（单院或未配置院区）。"""
    return os.getenv("PLATFORM_HOSPITAL_CODE", "").strip()
