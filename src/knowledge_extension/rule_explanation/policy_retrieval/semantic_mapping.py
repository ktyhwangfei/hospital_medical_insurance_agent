from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from .case_context import RawBusinessContext, CaseContext, SemanticMappingResult


DEFAULT_MAPPING = {
    "hospital_level": {
        "三级": "三级",
        "二级": "二级",
        "一级及以下": "一级及以下"
    },
    "service_type": {
        "普通住院": "inpatient",
        "单病种住院": "inpatient",
        "日间手术": "inpatient",
        "普通门诊": "outpatient",
        "急诊": "outpatient",
        "门慢": "outpatient",
        "门特": "outpatient"
    },
    "population": {
        "城镇居民基本医疗保险_学生儿童": "student_child",
        "城镇居民基本医疗保险_无保障老年人": "adult",
        "城镇居民基本医疗保险_无业": "adult",
        "城镇职工": "adult"
    },
    "insurance_type": {
        "城镇居民基本医疗保险_学生儿童": "urban_rural_resident",
        "城镇居民基本医疗保险_无保障老年人": "urban_rural_resident",
        "城镇居民基本医疗保险_无业": "urban_rural_resident",
        "城镇职工": "employee"
    },
}


class SemanticMapper:
    """
    医院业务字段 -> 政策标准语义字段。

    第一版只做字典映射，不做 LLM 裁决。
    配置可以来自 JSON/YAML；如果没有提供配置，使用 DEFAULT_MAPPING。

    v3.0: 支持 lookup_fn 参数，可委托到 SemanticMappingService 进行持久化查询。
          当 lookup_fn 提供时，优先通过它查询；未命中时回退到本地 DEFAULT_MAPPING。
    """

    def __init__(
        self,
        mapping_path: str | Path | None = None,
        lookup_fn: Callable[[str, str], str | None] | None = None,
    ):
        self.mapping = DEFAULT_MAPPING
        self._lookup_fn = lookup_fn

        if mapping_path:
            loaded = self._load_mapping(Path(mapping_path))
            if loaded:
                self.mapping = loaded

    def normalize_case_context(
        self,
        raw: RawBusinessContext,
        *,
        target_object: str | None = None,
        target_amount: float | None = None,
        required_fields: list[str] | None = None,
    ) -> CaseContext:
        required_fields = required_fields or []

        ctx = CaseContext(
            case_id=raw.case_id,
            person_id=raw.person_id,
            settlement_id=raw.settlement_id,
            visit_id=raw.visit_id,
            settlement_year=raw.raw_settlement_year,
            target_amount=target_amount if target_amount is not None else raw.raw_target_amount,
            target_object=target_object,
            raw_context=raw,
        )

        ctx.population = self._map_field(
            ctx,
            field="population",
            raw_value=raw.raw_person_type,
        )

        ctx.insurance_type = self._map_field(
            ctx,
            field="insurance_type",
            raw_value=raw.raw_insurance_type,
        )

        ctx.service_type = self._map_field(
            ctx,
            field="service_type",
            raw_value=raw.raw_service_type,
        )

        ctx.hospital_level = self._map_field(
            ctx,
            field="hospital_level",
            raw_value=raw.raw_hospital_level,
        )

        ctx.admission_order = self._normalize_admission_order(
            raw.raw_admission_count,
        )

        ctx.mapping_logs.append(
            SemanticMappingResult(
                field="admission_order",
                raw_value=raw.raw_admission_count,
                normalized_value=ctx.admission_order,
                confidence=1.0 if ctx.admission_order else 0.0,
                mapping_source="business_rule",
                warning=None if ctx.admission_order else "无法根据 raw_admission_count 推导 admission_order",
            )
        )

        for field in required_fields:
            if getattr(ctx, field, None) in [None, "", "unknown"]:
                ctx.missing_fields.append(field)

        return ctx

    def _map_field(
        self,
        ctx: CaseContext,
        *,
        field: str,
        raw_value: Any,
    ) -> str | None:
        if raw_value is None:
            ctx.mapping_logs.append(
                SemanticMappingResult(
                    field=field,
                    raw_value=None,
                    normalized_value=None,
                    confidence=0.0,
                    mapping_source="dictionary",
                    warning="原始值为空",
                )
            )
            return None

        key = str(raw_value).strip()

        # v3.0: 优先使用外部 lookup_fn（持久化查询）
        if self._lookup_fn is not None:
            external_result = self._lookup_fn(field, key)
            if external_result is not None:
                ctx.mapping_logs.append(
                    SemanticMappingResult(
                        field=field,
                        raw_value=raw_value,
                        normalized_value=external_result,
                        confidence=1.0,
                        mapping_source="persisted",
                    )
                )
                return external_result

        # 回退到本地字典
        mapping = self.mapping.get(field, {})
        normalized = mapping.get(key)

        if normalized:
            ctx.mapping_logs.append(
                SemanticMappingResult(
                    field=field,
                    raw_value=raw_value,
                    normalized_value=normalized,
                    confidence=1.0,
                    mapping_source="dictionary",
                )
            )
            return normalized

        ctx.mapping_logs.append(
            SemanticMappingResult(
                field=field,
                raw_value=raw_value,
                normalized_value="unknown",
                confidence=0.0,
                mapping_source="dictionary",
                warning=f"未找到 {field} 的映射值: {raw_value}",
            )
        )
        return "unknown"

    def _normalize_admission_order(self, admission_count: int | None) -> str | None:
        if admission_count is None:
            return None

        if admission_count <= 1:
            return "1"

        # 政策事实里通常是第二次及以后，统一成 >=2，便于重写和检索
        return ">=2"

    def _load_mapping(self, path: Path) -> dict[str, dict[str, str]] | None:
        if not path.exists():
            return None

        text = path.read_text(encoding="utf-8")

        if path.suffix.lower() == ".json":
            return json.loads(text)

        if path.suffix.lower() in [".yaml", ".yml"]:
            try:
                import yaml
            except ImportError as e:
                raise RuntimeError("读取 YAML 需要安装 PyYAML: pip install pyyaml") from e

            return yaml.safe_load(text)

        raise ValueError(f"不支持的映射配置格式: {path}")
