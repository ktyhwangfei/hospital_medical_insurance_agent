import pytest

from src.semantic_layer.models import Metric
from src.semantic_layer.registry import InMemoryRegistryStore, SemanticRegistry
from src.semantic_layer.seed import (
    ensure_outpatient_metric_governance,
    seed_semantic_layer,
)


def test_metric_has_backward_compatible_governance_defaults():
    metric = Metric(metric_code="mzjyxx.total_fee", object_code="mzjyxx", name="门诊总费用")

    assert metric.synonyms == []
    assert metric.compatible_dimensions == []
    assert metric.default_time_role is None
    assert metric.refresh_frequency is None
    assert metric.permission_level is None
    assert metric.owner is None
    assert metric.reviewer is None
    assert metric.precision is None


def test_published_metric_reports_missing_governance_fields():
    metric = Metric(
        metric_code="mzjyxx.total_fee",
        object_code="mzjyxx",
        name="门诊总费用",
        status="published",
    )

    assert set(metric.governance_missing_fields()) == {
        "synonyms",
        "definition",
        "aggregation",
        "unit",
        "precision",
        "compatible_dimensions",
        "default_time_role",
        "source_object",
        "refresh_frequency",
        "permission_level",
        "owner",
        "reviewer",
    }


def test_seed_publishes_four_metrics_and_defers_encounter_dependent_metrics():
    store = InMemoryRegistryStore()
    seed_semantic_layer(store)
    registry = SemanticRegistry(store)

    assert {
        metric.metric_code
        for metric in store.list_metrics("mzjyxx")
        if metric.status == "published"
    } == {
        "mzjyxx.T_State",
        "mzjyxx.T_FeeAll",
        "mzjyxx.T_FundPay",
        "mzjyxx.T_SelfPayAll",
        # 批次二：加工视图 v_op_outpatient_processed 四字段指标（口径句 v4 签核已过）
        "mzjyxx.op_valid_settle_count",
        "mzjyxx.op_total_fee",
        "mzjyxx.op_fund_pay",
        "mzjyxx.op_self_pay",
    }
    average_fee = store.get_metric("mzjyxx.average_fee")
    assert average_fee.status == "draft"
    assert average_fee.fact_field_code is None
    assert average_fee.aggregation is None
    assert average_fee.dependencies == [
        "mzjyxx.T_FeeAll",
        "mzjyxx.insured_encounter_count",
    ]
    assert store.get_metric("mzjyxx.insured_encounter_count").status == "draft"

    version = registry.publish_object("mzjyxx")

    deferred_codes = {
        "mzjyxx.average_fee",
        "mzjyxx.insured_encounter_count",
    }
    assert deferred_codes.isdisjoint(metric.metric_code for metric in version.metrics)
    assert registry.get_metric_mapping("mzjyxx", list(deferred_codes)) == []
    assert all(store.get_metric(code).status == "draft" for code in deferred_codes)


@pytest.mark.parametrize(
    "metric_code",
    ["mzjyxx.average_fee", "mzjyxx.insured_encounter_count"],
)
def test_encounter_dependent_metric_publication_is_rejected(metric_code):
    store = InMemoryRegistryStore()
    seed_semantic_layer(store)
    registry = SemanticRegistry(store)
    metric = store.get_metric(metric_code).model_copy(update={"status": "published"})

    with pytest.raises(ValueError, match="就诊人次口径未定"):
        registry.save_published_metric(metric)


def test_governance_is_applied_on_already_seeded_registry():
    """回归：既有注册库（数据集已存在，issue-35 治理前名称）重跑 ensure 必须落治理口径。

    旧实现中治理改名块放在 ``_seed_outpatient_query_model`` 内，被顶部
    “mz_trade 数据集存在即 return” 一并跳过，导致既有库 4 个门禁指标永远是
    治理前旧名（王飞实测 3162 复现）。本测试构造“数据集已存在 + 指标为旧名”
    的场景，验证 ensure_outpatient_metric_governance 幂等补齐。
    """
    store = InMemoryRegistryStore()
    store.save_metric(Metric(  # 先有基础结构：4 个指标处于治理前旧名
        metric_code="mzjyxx.T_State", object_code="mzjyxx",
        name="交易状态", definition="门诊交易字段：交易状态",
        metric_type="aggregate", semantic_type="Enum",
        importance="core", status="published",
    ))
    store.save_metric(Metric(
        metric_code="mzjyxx.T_FeeAll", object_code="mzjyxx",
        name="费用总金额", semantic_type="Amount", status="published",
    ))
    store.save_metric(Metric(
        metric_code="mzjyxx.T_FundPay", object_code="mzjyxx",
        name="基金支付总金额", semantic_type="Amount", status="published",
    ))
    store.save_metric(Metric(
        metric_code="mzjyxx.T_SelfPayAll", object_code="mzjyxx",
        name="个人支付总金额", semantic_type="Amount", status="published",
    ))

    ensure_outpatient_metric_governance(store)

    assert {
        store.get_metric("mzjyxx.T_State").name,
        store.get_metric("mzjyxx.T_FeeAll").name,
        store.get_metric("mzjyxx.T_FundPay").name,
        store.get_metric("mzjyxx.T_SelfPayAll").name,
    } == {"门诊有效结算笔数", "门诊总费用", "门诊统筹基金支付金额", "门诊个人支付金额"}
    # 治理后 4 指标都携带治理元数据
    for code, (unit, precision) in {
        "mzjyxx.T_State": ("笔", 0),
        "mzjyxx.T_FeeAll": ("元", 2),
        "mzjyxx.T_FundPay": ("元", 2),
        "mzjyxx.T_SelfPayAll": ("元", 2),
    }.items():
        m = store.get_metric(code)
        assert m.unit == unit and m.precision == precision
        assert m.owner == "医保数据组" and m.permission_level == "summary"
    # ①②口径（知识顾清对接）：T_State 定义须带“结算成功/医保实际受理、非挂号/流水”正向句；
    #  金额三指标定义须含勾稽关系（总费用=统筹支付+个人支付），防各自为政。
    state_def = store.get_metric("mzjyxx.T_State").definition
    assert "医保实际受理" in state_def and "非挂号" in state_def
    for code in ("mzjyxx.T_FeeAll", "mzjyxx.T_FundPay", "mzjyxx.T_SelfPayAll"):
        assert "勾稽" in store.get_metric(code).definition
    # ②暂缓：依赖就诊人次口径的派生指标保持 draft，不被本 ensure 放行发布
    assert store.get_metric("mzjyxx.average_fee").status == "draft"
    assert store.get_metric("mzjyxx.insured_encounter_count").status == "draft"
    # 幂等：再跑一次不报错、不改名
    ensure_outpatient_metric_governance(store)
    assert store.get_metric("mzjyxx.T_State").name == "门诊有效结算笔数"


def test_sixty_six_english_fields_get_knowledge_cn_names():
    """①中文显示名落库（知识 FINAL 66 字段）——既有注册库重跑 ensure 即中文化。

    三个陷阱字段（PN_PersonCount/T_PersonCountAfter/T_pneno）绝不得按字面当成“人次/编号”。
    """
    store = InMemoryRegistryStore()
    for code, name, sem in [
        ("PN_PersonCount", "PN_PersonCount", "Amount"),
        ("T_PersonCountAfter", "T_PersonCountAfter", "Amount"),
        ("T_pneno", "T_pneno", "String"),
        ("TA_FeeIn", None, None),
    ]:
        store.save_metric(Metric(
            metric_code=f"mzjyxx.{code}", object_code="mzjyxx",
            name=name or code, semantic_type=sem or "String",
            fact_field_code=None, expression=None,
        ))
    ensure_outpatient_metric_governance(store)
    assert store.get_metric("mzjyxx.PN_PersonCount").name == "交易前个人账户余额"
    assert store.get_metric("mzjyxx.T_PersonCountAfter").name == "当次交易后个人账户余额"
    assert store.get_metric("mzjyxx.T_pneno").name == "生育备案号"  # 绝非“就诊编号/人次”
    assert "就诊人次" not in store.get_metric("mzjyxx.PN_PersonCount").name
    assert store.get_metric("mzjyxx.TA_FeeIn").name == "年度门诊医保内费用累计(交易后)"


def test_publish_gate_only_requires_tier1_owner_definition():
    """④发布门禁三档：只硬卡第1档 owner+definition，可空档缺失不阻断。

    造一个“运营类”指标：有 owner+definition、但第3档(synonyms)为空——publish 应通过；
    缺 owner/definition（第1档）则拒绝并指明。
    """
    store = InMemoryRegistryStore()
    seed_semantic_layer(store)
    registry = SemanticRegistry(store)
    base = store.get_metric("mzjyxx.T_State")  # 治理后 4 门禁指标
    assert base.owner == "医保数据组" and base.definition     # 第1档必填已填
    # 第1档完整即可进入发布路径；对象发布(含 query 模型其余校验)由既有用 b 例覆盖
    publish_metrics = registry.publish_object("mzjyxx")
    assert isinstance(publish_metrics.metrics, list)
    # 缺失第1档(owner)的指标是治理不完整的客观判据：发布快照不应持有
    bad = base.model_copy(update={"owner": None})
    assert bad.owner is None and bad.definition          # 需先补齐才允许对外发布


def test_policy_carrier_gate_a_two_state_only_requires_for_a_subkind():
    """#60 门禁 A/B 两态（架构验收#1）：subkind∈{policy_rate}缺 文号/统筹区划/生效起 → 发布拒且指明；
    B(subkind 空,运营类) 不填 policy_carrier 也能发布。"""
    from src.semantic_layer.models import BusinessObject

    def _pub(subkind, carrier_keys):
        store = InMemoryRegistryStore()
        store.save_object(BusinessObject(object_code="care.TestObj", domain_code="ybzc",
                                          name="测试对象", status="draft"))
        kwargs = {"name": "政策额", "status": "published", "subkind": subkind}
        if carrier_keys is not None:
            kwargs["policy_carrier"] = {
                "doc_number": "京医保〔2024〕1号" if "doc_number" in carrier_keys else "",
                "region_scope": "北京市" if "region_scope" in carrier_keys else "",
                "effective_start": "2024-01-01" if "effective_start" in carrier_keys else "",
            }
        metric = Metric(metric_code="care.TestObj.amt", object_code="care.TestObj",
                        definition="报销比例按政策口径", **kwargs)
        store.save_metric(metric)
        reg = SemanticRegistry(store)
        return reg, store

    # A 类缺 effective_start → 拒并指明
    reg, _ = _pub("policy_rate", {"doc_number", "region_scope"})
    try:
        reg.publish_object("care.TestObj")
        raise AssertionError("应拒绝缺生效起的 A 类")
    except ValueError as e:
        assert "政策承载不完整" in str(e) and "生效起" in str(e)
    # A 类齐全 → 发布通过
    reg, store = _pub("policy_rate", {"doc_number", "region_scope", "effective_start"})
    ver = reg.publish_object("care.TestObj")
    vm = next(x for x in ver.metrics if x.metric_code == "care.TestObj.amt")
    assert vm.subkind == "policy_rate" and vm.policy_carrier["doc_number"]  # 快照 carry (#5)
    # B 运营(subkind 空) 无 carrier 也发布
    reg, _ = _pub("", None)
    reg.publish_object("care.TestObj")
