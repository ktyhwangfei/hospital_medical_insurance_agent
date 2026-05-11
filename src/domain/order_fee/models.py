from dataclasses import dataclass


@dataclass(frozen=True)
class Order:
    """医嘱：医生开具的诊疗医嘱信息。"""

    order_id: str
    patient_id: str
    encounter_id: str
    order_type: str
    status: str
    items: tuple["FeeItem", ...]
    total_amount: float


@dataclass(frozen=True)
class FeeItem:
    """费用明细：医嘱对应的单项费用记录。"""

    item_id: str
    category: str  # "drug", "consumable", "treatment"
    code: str
    name: str
    quantity: int
    unit_price: float
    total_price: float


@dataclass(frozen=True)
class Drug:
    """药品信息：医保药品目录中的药品记录。"""

    drug_code: str
    drug_name: str
    specification: str
    is_medical_insurance: bool
    reimbursement_category: str  # "甲类", "乙类", "丙类"


@dataclass(frozen=True)
class Consumable:
    """耗材信息：医用耗材目录中的耗材记录。"""

    consumable_code: str
    consumable_name: str
    specification: str
    is_medical_insurance: bool


@dataclass(frozen=True)
class Treatment:
    """诊疗项目：医疗服务项目的价格与医保属性。"""

    treatment_code: str
    treatment_name: str
    is_medical_insurance: bool
    price_standard: float
