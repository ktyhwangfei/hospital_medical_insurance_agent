"""批次一静态 T1：v_op_outpatient_processed 加工口径（口径句 v4，不连库夹具）。

派工单: docs/processing/batch1-view.md
断言依据: docs/processing/outpatient_processed_view.sql（与 view-dispatch.md 定稿一致）

四组:
① 公式逐值×4       四个字段各自对合法行算出精确值
② 冲正/负数排除    退费/红冲/未受理/负金额冲正行不进任何字段
③ 跨险种去重键     COUNT(DISTINCT T_TradeNo)，同 trade_no 多险种行只计 1 笔、金额全计
④ 勾稽恒等         过滤后 总费用 = 统筹 + 个人（被排除的失衡行不泄漏）
"""
import pytest

# 门诊档 = MZ_CURE_TYPE 已发布值域（seed.py: 11 普通门诊/17 门诊挂号/18 急诊挂号/19 普通急诊）
CURE_TYPE_OUTPATIENT = frozenset({11, 17, 18, 19})


def _passes(tr: dict) -> bool:
    """镜像 SQL WHERE（口径句 v4）。"""
    return (
        tr["T_State"] in (2, 3)
        and tr["NP_Settle_State"] == 1
        and tr["T_HasRefundmented"] != 1
        and (tr["T_PartialReturnFlag"] is None or tr["T_PartialReturnFlag"] == "")
        and (tr["T_CureType"] in CURE_TYPE_OUTPATIENT or tr["T_CureType"] is None)
    )


def v_op_outpatient_processed(rows):
    """镜像 SELECT 四字段聚合。"""
    kept = [r for r in rows if _passes(r)]
    return {
        "op_valid_settle_count": len({r["T_TradeNo"] for r in kept}),
        "op_total_fee": sum(r["T_FeeAll"] for r in kept),
        "op_fund_pay": sum(r["T_FundPay"] for r in kept),
        "op_self_pay": sum(r["T_SelfPayAll"] for r in kept),
    }


# ── 夹具 ────────────────────────────────────────────────────────

def make(**over):
    row = {
        "T_TradeNo": "TN",
        "P_FundType": "3",  # 险种（城镇职工），仅用于③区分行
        "T_State": 2,
        "NP_Settle_State": 1,
        "T_HasRefundmented": 0,
        "T_PartialReturnFlag": None,
        "T_CureType": 11,
        "T_FeeAll": 0,
        "T_FundPay": 0,
        "T_SelfPayAll": 0,
    }
    row.update(over)
    return row


# ① 公式逐值 ×4 ──────────────────────────────────────────────────

def test_公式逐值_四字段精确值():
    """三条合法行（档 11/17/NULL），各字段期望值手算断言。"""
    rows = [
        make(T_TradeNo="TN-1", T_CureType=11, T_FeeAll=100.0, T_FundPay=60.0, T_SelfPayAll=40.0),
        make(T_TradeNo="TN-2", T_CureType=17, T_FeeAll=250.0, T_FundPay=200.0, T_SelfPayAll=50.0),
        make(T_TradeNo="TN-3", T_CureType=None, T_FeeAll=30.0, T_FundPay=0.0, T_SelfPayAll=30.0),  # 空=通用门诊规则
    ]
    out = v_op_outpatient_processed(rows)
    assert out["op_valid_settle_count"] == 3
    assert out["op_total_fee"] == 380.0  # 100+250+30
    assert out["op_fund_pay"] == 260.0   # 60+200+0
    assert out["op_self_pay"] == 120.0   # 40+50+30


def test_公式_不含脏行():
    """混入一条被过滤行，四字段均不受其数值污染。"""
    rows = [
        make(T_TradeNo="TN-A", T_FeeAll=100.0, T_FundPay=60.0, T_SelfPayAll=40.0),
        make(T_TradeNo="TN-B", T_State=4, T_FeeAll=999.0, T_FundPay=999.0, T_SelfPayAll=999.0),  # 冲正档
    ]
    out = v_op_outpatient_processed(rows)
    assert out == {"op_valid_settle_count": 1, "op_total_fee": 100.0,
                   "op_fund_pay": 60.0, "op_self_pay": 40.0}


# ② 冲正/负数排除 ────────────────────────────────────────────────

@pytest.mark.parametrize("broken", [
    {"T_State": 4},                # 负金额冲正档（非 2/3）
    {"T_State": 1},                # 未完成结算档
    {"NP_Settle_State": 0},        # 国家平台未受理
    {"T_HasRefundmented": 1},      # 已退费
    {"T_PartialReturnFlag": "1"},  # 部分退费红冲
    {"T_PartialReturnFlag": "0"},  # 非空标记即红冲（口径句 v4: 仅 NULL/'' 可过）
    {"T_CureType": 21},            # 非门诊档（住院类别）
])
def test_冲正_负数_单条越界即排除(broken):
    """任意一项触犯外过滤 → 该行笔数/金额全部剔除。"""
    rows = [make(T_TradeNo="TN-X", T_FeeAll=-50.0, T_FundPay=-30.0, T_SelfPayAll=-20.0, **broken)]
    out = v_op_outpatient_processed(rows)
    assert out == {"op_valid_settle_count": 0, "op_total_fee": 0,
                   "op_fund_pay": 0, "op_self_pay": 0}


def test_负金额冲正行_不影响合法行():
    """冲正负数行与合法行共存，总和只含合法行。"""
    rows = [
        make(T_TradeNo="TN-OK", T_FeeAll=200.0, T_FundPay=150.0, T_SelfPayAll=50.0),
        make(T_TradeNo="TN-REV", T_State=4, T_FeeAll=-200.0, T_FundPay=-150.0, T_SelfPayAll=-50.0),
    ]
    out = v_op_outpatient_processed(rows)
    assert out == {"op_valid_settle_count": 1, "op_total_fee": 200.0,
                   "op_fund_pay": 150.0, "op_self_pay": 50.0}


# ③ 跨险种 trade_no 去重键 ───────────────────────────────────────

def test_同trade_no跨险种只计一笔_金额全计():
    """同一 trade_no 在多个险种行 → 笔数去重为 1，金额逐行累加。"""
    rows = [
        make(T_TradeNo="TN-SAME", P_FundType="3", T_FeeAll=100.0, T_FundPay=60.0, T_SelfPayAll=40.0),
        make(T_TradeNo="TN-SAME", P_FundType="320", T_FeeAll=50.0, T_FundPay=30.0, T_SelfPayAll=20.0),  # 城乡居民
    ]
    out = v_op_outpatient_processed(rows)
    assert out["op_valid_settle_count"] == 1  # COUNT(DISTINCT T_TradeNo)
    assert out["op_total_fee"] == 150.0
    assert out["op_fund_pay"] == 90.0
    assert out["op_self_pay"] == 60.0


def test_不同trade_no分别计笔():
    """两个独立 trade_no → 2 笔。"""
    rows = [
        make(T_TradeNo="TN-1", T_FeeAll=10.0, T_FundPay=5.0, T_SelfPayAll=5.0),
        make(T_TradeNo="TN-2", T_FeeAll=10.0, T_FundPay=5.0, T_SelfPayAll=5.0),
    ]
    out = v_op_outpatient_processed(rows)
    assert out["op_valid_settle_count"] == 2


# ④ 勾稽恒等（总 = 统筹 + 个人）──────────────────────────────────

def test_勾稽恒等():
    """混合合法行（行内平衡）+ 被排除行（行内失衡）：聚合后恒等式成立，失衡行不泄漏。"""
    rows = [
        make(T_TradeNo="TN-1", T_FeeAll=100.0, T_FundPay=60.0, T_SelfPayAll=40.0),
        make(T_TradeNo="TN-2", T_FeeAll=300.0, T_FundPay=280.0, T_SelfPayAll=20.0),
        make(T_TradeNo="TN-BAD", T_State=4, T_FeeAll=1000.0, T_FundPay=1.0, T_SelfPayAll=1.0),  # 失衡但被排除
        make(T_TradeNo="TN-REF", T_HasRefundmented=1, T_FeeAll=500.0, T_FundPay=499.0, T_SelfPayAll=0.0),
    ]
    out = v_op_outpatient_processed(rows)
    assert out["op_total_fee"] == out["op_fund_pay"] + out["op_self_pay"]
    assert out["op_valid_settle_count"] == 2
    assert out["op_total_fee"] == 400.0  # 100+300，排除行不泄漏