"""
PostgreSQL 实现的技能存储
"""
import json
import logging
from typing import Any

from src.config.production import DATABASE_URL, DB_RETRY_ATTEMPTS, DB_RETRY_DELAY
from src.data_platform.storage.postgresql.client import PostgreSQLClient
from src.data_platform.storage.skill.models import SkillStorageHealth, SkillStorageHealthStatus
from src.data_platform.storage.skill.ports import SkillStorage
from src.domain.skill.models import Skill

logger = logging.getLogger(__name__)

SKILL_TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS skills (
    skill_id VARCHAR(128) PRIMARY KEY,
    name VARCHAR(256) NOT NULL,
    description TEXT,
    owner VARCHAR(128),
    steps JSONB DEFAULT '[]',
    intent_keywords JSONB DEFAULT '[]',
    required_roles JSONB DEFAULT '[]',
    enabled BOOLEAN DEFAULT TRUE,
    risk_level VARCHAR(32) DEFAULT 'LOW',
    license VARCHAR(128),
    compatibility TEXT,
    allowed_tools JSONB DEFAULT '[]',
    skill_metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_skills_owner ON skills(owner);
"""


class PostgresSkillStorage(SkillStorage):
    """PostgreSQL-backed skill storage implementation."""

    def __init__(self, database_url: str | None = None):
        self._database_url = database_url or DATABASE_URL
        self._client: PostgreSQLClient | None = None

    def _get_client(self) -> PostgreSQLClient:
        """获取数据库客户端（延迟初始化）"""
        if self._client is None:
            try:
                self._client = PostgreSQLClient(self._database_url)
                self._ensure_schema()
                logger.info("PostgreSQL skill storage initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize PostgreSQL skill storage: {e}")
                raise
        return self._client

    def _ensure_schema(self) -> None:
        """确保数据库表结构存在"""
        try:
            self._client.execute(SKILL_TABLE_SCHEMA)
            logger.debug("Skill table schema ensured")
        except Exception as e:
            logger.error(f"Failed to ensure skill table schema: {e}")
            raise

    def save_skill(self, skill: Skill) -> None:
        """保存技能到数据库"""
        try:
            client = self._get_client()
            sql = """
                INSERT INTO skills (skill_id, name, description, owner, steps, intent_keywords, required_roles, enabled, risk_level, license, compatibility, allowed_tools, skill_metadata, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (skill_id) DO UPDATE SET
                    name = EXCLUDED.name,
                    description = EXCLUDED.description,
                    owner = EXCLUDED.owner,
                    steps = EXCLUDED.steps,
                    intent_keywords = EXCLUDED.intent_keywords,
                    required_roles = EXCLUDED.required_roles,
                    enabled = EXCLUDED.enabled,
                    risk_level = EXCLUDED.risk_level,
                    license = EXCLUDED.license,
                    compatibility = EXCLUDED.compatibility,
                    allowed_tools = EXCLUDED.allowed_tools,
                    skill_metadata = EXCLUDED.skill_metadata,
                    updated_at = CURRENT_TIMESTAMP
            """
            params = (
                skill.skill_id,
                skill.name,
                skill.description,
                str(skill.owner),
                json.dumps([s.model_dump() for s in skill.steps], ensure_ascii=False),
                json.dumps(skill.intent_keywords, ensure_ascii=False),
                json.dumps(list(skill.required_roles), ensure_ascii=False),
                skill.enabled,
                str(skill.risk_level),
                skill.license,
                skill.compatibility,
                json.dumps(skill.allowed_tools, ensure_ascii=False),
                json.dumps(skill.skill_metadata.model_dump(), ensure_ascii=False),
            )
            client.execute(sql, params)
            logger.debug(f"Saved skill: {skill.skill_id}")
        except Exception as e:
            logger.error(f"Failed to save skill {skill.skill_id}: {e}")
            raise

    def get_skill(self, skill_id: str) -> Skill | None:
        """从数据库获取技能"""
        try:
            client = self._get_client()
            sql = "SELECT * FROM skills WHERE skill_id = %s"
            rows = client.execute(sql, (skill_id,))
            if not rows:
                return None
            return self._row_to_skill(rows[0])
        except Exception as e:
            logger.error(f"Failed to get skill {skill_id}: {e}")
            raise

    def list_skills(self) -> list[Skill]:
        """列出所有技能"""
        try:
            client = self._get_client()
            sql = "SELECT * FROM skills ORDER BY skill_id"
            rows = client.execute(sql)
            return [self._row_to_skill(row) for row in rows]
        except Exception as e:
            logger.error(f"Failed to list skills: {e}")
            raise

    def list_skills_by_owner(self, owner: str) -> list[Skill]:
        """按所有者列出技能"""
        try:
            client = self._get_client()
            sql = "SELECT * FROM skills WHERE owner = %s ORDER BY skill_id"
            rows = client.execute(sql, (owner,))
            return [self._row_to_skill(row) for row in rows]
        except Exception as e:
            logger.error(f"Failed to list skills by owner {owner}: {e}")
            raise

    def list_skills_by_role(self, role: str) -> list[Skill]:
        """按角色列出技能"""
        try:
            client = self._get_client()
            sql = "SELECT * FROM skills WHERE owner = %s OR required_roles @> %s ORDER BY skill_id"
            rows = client.execute(sql, (role, json.dumps([role])))
            return [self._row_to_skill(row) for row in rows]
        except Exception as e:
            logger.error(f"Failed to list skills by role {role}: {e}")
            raise

    def delete_skill(self, skill_id: str) -> bool:
        """删除技能"""
        try:
            client = self._get_client()
            sql = "DELETE FROM skills WHERE skill_id = %s"
            result = client.execute(sql, (skill_id,))
            return len(result) > 0
        except Exception as e:
            logger.error(f"Failed to delete skill {skill_id}: {e}")
            raise

    def health(self) -> SkillStorageHealth:
        """健康检查"""
        try:
            client = self._get_client()
            client.execute("SELECT 1")
            return SkillStorageHealth(
                status=SkillStorageHealthStatus.HEALTHY,
                details={"backend": "postgresql", "url": self._database_url.split("@")[-1]},
            )
        except Exception as e:
            logger.error(f"Skill storage health check failed: {e}")
            return SkillStorageHealth(
                status=SkillStorageHealthStatus.UNHEALTHY,
                details={"backend": "postgresql", "error": str(e)},
            )

    @staticmethod
    def _row_to_skill(row: dict[str, Any]) -> Skill:
        """将数据库行转换为Skill对象"""
        from src.domain.skill.models import SkillMetadata, SkillStep
        from src.knowledge_extension.mcp_registry.models import McpRiskLevel
        
        steps_data = json.loads(row["steps"]) if isinstance(row.get("steps"), str) else row.get("steps", [])
        required_roles = json.loads(row["required_roles"]) if isinstance(row.get("required_roles"), str) else row.get("required_roles", [])
        metadata_data = json.loads(row["skill_metadata"]) if isinstance(row.get("skill_metadata"), str) else row.get("skill_metadata", {})
        
        return Skill(
            skill_id=row["skill_id"],
            name=row["name"],
            description=row.get("description", ""),
            owner=row.get("owner", ""),
            steps=[SkillStep(**s) for s in steps_data],
            intent_keywords=json.loads(row["intent_keywords"]) if isinstance(row.get("intent_keywords"), str) else row.get("intent_keywords", []),
            required_roles=set(required_roles) if isinstance(required_roles, list) else required_roles,
            enabled=row.get("enabled", True),
            risk_level=McpRiskLevel(row["risk_level"]) if row.get("risk_level") else McpRiskLevel.LOW,
            license=row.get("license"),
            compatibility=row.get("compatibility"),
            allowed_tools=json.loads(row["allowed_tools"]) if isinstance(row.get("allowed_tools"), str) else row.get("allowed_tools", []),
            skill_metadata=SkillMetadata(**metadata_data) if metadata_data else SkillMetadata(),
        )
