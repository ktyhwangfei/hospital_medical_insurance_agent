from __future__ import annotations

from .case_context import RawBusinessContext


class MockBusinessDataClient:
    """
    第一版 Mock，不连接真实业务库。

    后续替换为真实 SQL/API 时，只需要保持 get_case_context_raw 的返回结构不变。
    """

    def __init__(self):
        self.mock_data = {
            "S001": RawBusinessContext(
                case_id="case_001",
                person_id="P001",
                settlement_id="S001",
                visit_id="V002",
                raw_person_type="城乡老年人",
                raw_insurance_type="城乡居民医保",
                raw_service_type="21",
                raw_hospital_level="3",
                raw_hospital_name="某三级医院",
                raw_admission_count=2,
                raw_settlement_year=2026,
                raw_target_amount=1950.0,
                raw_data={
                    "note": "mock: 成人城乡居民医保，三级医院，本年度第二次住院",
                },
            ),
            "S002": RawBusinessContext(
                case_id="case_002",
                person_id="P002",
                settlement_id="S002",
                visit_id="V001",
                raw_person_type="学生儿童",
                raw_insurance_type="城乡居民医保",
                raw_service_type="21",
                raw_hospital_level="2",
                raw_hospital_name="某二级医院",
                raw_admission_count=1,
                raw_settlement_year=2026,
                raw_target_amount=400.0,
                raw_data={
                    "note": "mock: 学生儿童，二级医院，首次住院",
                },
            ),
        }

    def get_case_context_raw(
        self,
        *,
        settlement_id: str | None = None,
        person_id: str | None = None,
        visit_id: str | None = None,
        question: str | None = None,
    ) -> RawBusinessContext:
        if settlement_id and settlement_id in self.mock_data:
            return self.mock_data[settlement_id]

        # 没传 settlement_id 时，默认返回 S001，便于 demo
        return self.mock_data["S001"]
