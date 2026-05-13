"""
PostgreSQL 数据访问层
患者和医保交易数据的数据库实现
"""
import logging
from typing import Any

from src.config.production import DATABASE_URL
from src.data_platform.storage.postgresql.client import PostgreSQLClient
from src.domain.insurance.models import InsuranceTransaction
from src.domain.patient.models import Patient

logger = logging.getLogger(__name__)

# 表结构定义
PATIENTS_TABLE = """
CREATE TABLE IF NOT EXISTS patients (
    patient_id VARCHAR(64) PRIMARY KEY,
    name VARCHAR(128) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

TRANSACTIONS_TABLE = """
CREATE TABLE IF NOT EXISTS insurance_transactions (
    id SERIAL PRIMARY KEY,
    patient_id VARCHAR(64) NOT NULL,
    encounter_id VARCHAR(64) NOT NULL,
    settlement_status VARCHAR(32),
    upload_status VARCHAR(32),
    error_code VARCHAR(64),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(patient_id, encounter_id)
);
CREATE INDEX IF NOT EXISTS idx_transactions_patient ON insurance_transactions(patient_id);
"""

# 种子数据
SEED_PATIENTS = [
    Patient(patient_id='P001', name='张三'),
]

SEED_TRANSACTIONS = [
    InsuranceTransaction(
        patient_id='P001',
        encounter_id='E001',
        settlement_status='failed',
        upload_status='failed',
        error_code='E-UPLOAD-001',
    ),
]


class PostgresDataStore:
    """PostgreSQL 数据访问实现"""

    def __init__(self, database_url: str | None = None):
        self._database_url = database_url or DATABASE_URL
        self._client: PostgreSQLClient | None = None

    def _get_client(self) -> PostgreSQLClient:
        if self._client is None:
            try:
                self._client = PostgreSQLClient(self._database_url)
                self._ensure_schema()
                logger.info("PostgreSQL data store initialized")
            except Exception as e:
                logger.error(f"Failed to initialize PostgreSQL data store: {e}")
                raise
        return self._client

    def _ensure_schema(self) -> None:
        """确保表结构存在"""
        try:
            self._client.execute(PATIENTS_TABLE)
            self._client.execute(TRANSACTIONS_TABLE)
            logger.debug("Data store schema ensured")
        except Exception as e:
            logger.error(f"Failed to ensure data store schema: {e}")
            raise

    def seed_data(self) -> None:
        """加载种子数据"""
        try:
            client = self._get_client()
            for patient in SEED_PATIENTS:
                sql = """
                    INSERT INTO patients (patient_id, name)
                    VALUES (%s, %s)
                    ON CONFLICT (patient_id) DO UPDATE SET name = EXCLUDED.name
                """
                client.execute(sql, (patient.patient_id, patient.name))

            for txn in SEED_TRANSACTIONS:
                sql = """
                    INSERT INTO insurance_transactions (patient_id, encounter_id, settlement_status, upload_status, error_code)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (patient_id, encounter_id) DO UPDATE SET
                        settlement_status = EXCLUDED.settlement_status,
                        upload_status = EXCLUDED.upload_status,
                        error_code = EXCLUDED.error_code
                """
                client.execute(sql, (txn.patient_id, txn.encounter_id, txn.settlement_status, txn.upload_status, txn.error_code))

            logger.info("Seed data loaded successfully")
        except Exception as e:
            logger.error(f"Failed to load seed data: {e}")
            raise

    def get_patient(self, patient_id: str) -> Patient | None:
        """获取患者信息"""
        try:
            client = self._get_client()
            sql = "SELECT patient_id, name FROM patients WHERE patient_id = %s"
            rows = client.execute(sql, (patient_id,))
            if not rows:
                return None
            row = rows[0]
            return Patient(patient_id=row['patient_id'], name=row['name'])
        except Exception as e:
            logger.error(f"Failed to get patient {patient_id}: {e}")
            raise

    def get_insurance_transaction(self, patient_id: str, encounter_id: str) -> InsuranceTransaction | None:
        """获取医保交易"""
        try:
            client = self._get_client()
            sql = """
                SELECT patient_id, encounter_id, settlement_status, upload_status, error_code
                FROM insurance_transactions
                WHERE patient_id = %s AND encounter_id = %s
            """
            rows = client.execute(sql, (patient_id, encounter_id))
            if not rows:
                return None
            row = rows[0]
            return InsuranceTransaction(
                patient_id=row['patient_id'],
                encounter_id=row['encounter_id'],
                settlement_status=row['settlement_status'],
                upload_status=row['upload_status'],
                error_code=row['error_code'],
            )
        except Exception as e:
            logger.error(f"Failed to get transaction {patient_id}/{encounter_id}: {e}")
            raise

    def health(self) -> dict[str, Any]:
        """健康检查"""
        try:
            client = self._get_client()
            client.execute("SELECT 1")
            return {"status": "healthy", "backend": "postgresql"}
        except Exception as e:
            return {"status": "unhealthy", "backend": "postgresql", "error": str(e)}
