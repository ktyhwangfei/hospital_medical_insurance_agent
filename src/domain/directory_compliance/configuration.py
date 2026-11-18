"""配置文档到领域规则的一处转换，存储和治理入口后续复用。"""
from datetime import date

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.domain.directory_compliance.models import (
    ComplianceRule, ConditionGroup, NonBlank, RuleStatus,
)


class RuleItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    code: NonBlank
    name: NonBlank


class CatalogVersion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    effective_from: date
    effective_to: date
    source: str = ""


class RuleDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    rule_id: NonBlank
    rule_revision: int = Field(default=1, ge=1)
    engine_version: str = "1.1"
    status: RuleStatus = RuleStatus.DRAFT
    item: RuleItem
    catalog_version: CatalogVersion
    source_bz: NonBlank
    condition_groups: tuple[ConditionGroup, ...] = Field(min_length=1)
    reviewed_by: str = ""
    created_by: str = ""
    content_hash: str = ""
    published_at: str | None = None

    @model_validator(mode="after")
    def validate_domain_rule(self) -> "RuleDocument":
        self.to_rule()
        return self

    def to_rule(self) -> ComplianceRule:
        return ComplianceRule(
            rule_id=self.rule_id, revision=self.rule_revision, status=self.status,
            item_code=self.item.code, item_name=self.item.name,
            catalog_effective_from=self.catalog_version.effective_from,
            catalog_effective_to=self.catalog_version.effective_to,
            source_bz=self.source_bz, condition_groups=self.condition_groups,
            reviewed_by=self.reviewed_by,
            catalog_source=self.catalog_version.source,
        )

    @classmethod
    def from_rule(cls, rule: ComplianceRule) -> "RuleDocument":
        return cls(
            rule_id=rule.rule_id, rule_revision=rule.revision, status=rule.status,
            item=RuleItem(code=rule.item_code, name=rule.item_name),
            catalog_version=CatalogVersion(effective_from=rule.catalog_effective_from,
                                           effective_to=rule.catalog_effective_to, source=rule.catalog_source),
            source_bz=rule.source_bz, condition_groups=rule.condition_groups,
            reviewed_by=rule.reviewed_by,
        )
