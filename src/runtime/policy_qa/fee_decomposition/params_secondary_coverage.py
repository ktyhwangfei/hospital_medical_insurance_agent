"""两条门特链路共用的二次保障参数，来源：2026-10-13 用户补充规则。"""
from datetime import date
from decimal import Decimal

EFFECTIVE_DATE = date(2023, 1, 1)
BIG_ILL_DEDUCTIBLE = Decimal("30404")
BIG_ILL_FIRST_BAND = Decimal("50000")
BIG_ILL_RATES = (Decimal("0.60"), Decimal("0.70"))
ASSISTED_RATE_INCREMENT = Decimal("0.05")
# 门特按住院救助标准（京医保发〔2022〕37号第七条）；None为无封顶。
SPECIAL_AID_POLICIES: dict[str, tuple[Decimal, Decimal | None]] = {
    "25": (Decimal("1"), None),
    "26": (Decimal("1"), None),
    "336001": (Decimal("0.85"), None),
    "336011": (Decimal("0.85"), Decimal("160000")),
    "2364": (Decimal("0.85"), Decimal("160000")),
}
DB_SOURCE = "https://ybj.beijing.gov.cn/zwgk/2024zcwj/202406/t20240614_3712569.html"
AID_SOURCE = "https://www.beijing.gov.cn/zhengce/zhengcefagui/202303/t20230328_2946600.html"
