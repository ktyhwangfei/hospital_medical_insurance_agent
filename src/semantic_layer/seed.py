"""语义层种子数据 — 对齐 PostgreSQL 生产环境的真实定义。

数据来源：PostgreSQL semantic_domains / semantic_objects / semantic_metrics 表导出。
内容：3 域 / 7 对象 / 22 指标，全部 status=draft（待发布）。

用途：
1. ``InMemoryRegistryStore``（``USE_MEMORY_STORAGE=1`` / 单元测试）的种子数据；
2. ``PostgresRegistryStore._seed_if_empty`` 首次启动的初始化数据源。

编码与 ``skill_manifest.yaml`` 的 ``needed_objects`` 一致（zydyxx.* 物理编码），
是 skill 依赖的唯一真源。旧 Settlement.* 编码已废弃。
"""
from src.semantic_layer.models import (
    BusinessDomain, BusinessObject, Metric, ValueDomain, ValueDomainMapping,
)
from src.semantic_layer.registry import RegistryStore

# ── 医保字典标准映射（源自 business_sql.yaml 的 CASE 转换）──────────
# 将散落在 SQL CASE 里的码→标签映射，声明式收敛进语义层值域。
# [来源: business_sql.yaml settlement_context 的 CASE a.FUND_TYPE / CASE a.yllb
#  + settlement_data_provider._normalize_person_type]
# 语义层成为码→标签转换的唯一真源，business_sql.yaml 退役后此处保留。
_YB_DICTIONARY_MAPPINGS: dict[str, dict[str, str]] = {
    # 险种类型 FUND_TYPE
    "FUND_TYPE": {
        "3": "城镇职工", "4": "工伤保险", "31": "离休统筹",
        "32": "公疗医照", "33": "征地超转人员",
        "91": "城镇居民基本医疗保险_学生儿童",
        "92": "城镇居民基本医疗保险_无保障老年人",
        "93": "城镇居民基本医疗保险_无业",
    },
    # 医疗类别 YLLB
    "YLLB": {
        "11": "普通门诊", "12": "急诊", "14": "门慢", "16": "门特",
        "21": "普通住院", "22": "单病种住院", "24": "日间手术", "31": "药店购药",
    },
    # 人员类别 PERSON_TYPE（PER_TYPE 原始码 → 中文标签）
    "PERSON_TYPE": {
        "1": "在职人员", "2": "退休人员", "3": "离休人员",
        "4": "学生儿童", "5": "无保障老年人", "6": "无业人员",
    },
}


def ensure_yb_dictionary_mappings(store: RegistryStore) -> None:
    """幂等 ensure：把医保字典码→标签映射补入语义层值域。

    每次进程启动调用一次（幂等，upsert）。弥合语义层与 business_sql.yaml
    的「转换差异」：语义层取数后应用 resolve_value，即可产出与手写 CASE 一致的中文标签。
    """
    domain_names = {
        "FUND_TYPE": "险种类型", "YLLB": "医疗类别", "PERSON_TYPE": "人员类别",
    }
    for domain_code, mapping in _YB_DICTIONARY_MAPPINGS.items():
        store.save_value_domain(ValueDomain(
            domain_code=domain_code, name=domain_names.get(domain_code, domain_code),
            description="医保系统码→中文标签（源自 business_sql.yaml CASE）",
        ))
        for source_value, standard_value in mapping.items():
            store.save_value_mapping(ValueDomainMapping(
                domain_code=domain_code,
                source_value=source_value,
                standard_value=standard_value,
            ))


def seed_semantic_layer(store: RegistryStore) -> None:
    """灌入真实语义层：3 域 / 7 对象 / 22 指标（对齐生产 PostgreSQL）。

    所有对象/指标初始为 status=draft，需经发布流程（阶段2）转为 published。
    """
    _seed_domains(store)
    _seed_objects(store)
    _seed_metrics(store)
    ensure_yb_dictionary_mappings(store)


# 旧名兼容：PG store 与部分测试仍在引用，逐步迁移到 seed_semantic_layer。
seed_settlement_domain = seed_semantic_layer


# ── 业务域 ────────────────────────────────────────────────────

def _seed_domains(store: RegistryStore) -> None:
    for code, name, order in [
        ("ybdy", "医保待遇", 1),
        ("ybjs", "医保结算", 2),
        ("ybml", "医保目录", 3),
    ]:
        store.save_domain(BusinessDomain(domain_code=code, name=name, sort_order=order))


# ── 业务对象 ──────────────────────────────────────────────────

def _seed_objects(store: RegistryStore) -> None:
    # (object_code, domain_code, name, definition)
    objects = [
        ("djxx", "ybdy", "参保人登记",
         "参保人基本信息：登记号、险种类型、医疗类别。用于识别患者身份和待遇资格。"),
        ("nddyxx", "ybdy", "年度待遇",
         "年度统筹累计支付信息：费用年度、年度累计金额。用于判断年度封顶线和起付线状态。"),
        ("ypml", "ybml", "药品目录",
         "药品支付标准：住院限价、医保支付标准。用于费用归因时判断限价影响。"),
        ("zydyxx", "ybdy", "住院待遇", "住院待遇信息"),
        ("zyfdxx", "ybjs", "住院分段", "住院分段信息"),
        ("zyfymx", "ybjs", "住院费用明细",
         "住院费用明细项目：项目编码/名称、收费等级、特需标志、数量、金额（总/医保内/医保外）、自付比例、归因分类。是费用解释树的数据来源。"),
        ("zyjyxx", "ybjs", "住院交易", "住院交易信息"),
    ]
    for code, domain, name, definition in objects:
        store.save_object(BusinessObject(
            object_code=code, domain_code=domain, name=name, definition=definition,
            version="1.0", status="draft",
        ))


# ── 业务指标（22 个，对齐 PG 生产数据）─────────────────────────
# 字段含义见 src/semantic_layer/models.py: Metric
# 注意：PG 中存在 metric_code="djh"（缺对象前缀）的数据 bug，此处修正为 djxx.djh。

def _m(metric_code, object_code, name, definition, semantic_type, *,
       unit=None, required=False, source_object=None, source_field=None,
       source_adapter_port=None, value_domain=None, importance="optional"):
    """指标构造助手，减少重复参数。"""
    store_save = None  # 占位，实际由调用方 save
    return Metric(
        metric_code=metric_code, object_code=object_code, name=name,
        definition=definition, metric_type="Atomic", semantic_type=semantic_type,
        unit=unit, required=required, source_object=source_object,
        source_field=source_field, source_adapter_port=source_adapter_port,
        value_domain=value_domain, importance=importance,
        version="1.0", status="draft",
    )


def _seed_metrics(store: RegistryStore) -> None:
    _ADAPTER = "InsuranceInterfacePort"
    metrics = [
        # ── djxx 参保人登记 ──
        _m("djxx.djh", "djxx", "登记号", "登记号", "String",
           source_field="yb_brdjxx.djh"),
        _m("djxx.fund_type", "djxx", "险种类型", "基本医保险种类型", "Enum",
           source_object="InsuranceTransaction", source_field="yb_brdjxx.FUND_TYPE",
           source_adapter_port=_ADAPTER, value_domain="FUND_TYPE", importance="core"),
        _m("djxx.yllb", "djxx", "医疗类别", "本次医疗服务的业务类别", "Enum",
           source_object="InsuranceTransaction", source_field="yb_brdjxx.yllb",
           source_adapter_port=_ADAPTER, value_domain="YLLB"),
        # ── ypml 药品目录 ──
        _m("ypml.mzxj", "ypml", "带量采购门诊限价", "带量采购门诊限价", "Amount",
           source_object="yb_ypzdml", source_field="A_mzxj"),
        _m("ypml.zyxj", "ypml", "带量采购住院限价", "带量采购住院限价", "Amount",
           source_object="yb_ypzdml", source_field="A_zyxj"),
        # ── zydyxx 住院待遇 ──
        _m("zydyxx.bcqfje", "zydyxx", "起付线",
           "医保开始报销前需先由个人承担的固定金额", "Amount",
           unit="元", required=True, source_object="InsuranceTransaction",
           source_field="yb_dyxxzy.bcqfje", source_adapter_port=_ADAPTER, importance="core"),
        _m("zydyxx.bcybnje", "zydyxx", "医保内费用",
           "本次结算纳入医保报销范围的费用总额", "Amount",
           unit="元", source_object="InsuranceTransaction",
           source_field="yb_dyxxzy.bcybnje", source_adapter_port=_ADAPTER, importance="core"),
        # ── zyfdxx 住院分段 ──
        _m("zyfdxx.bdtczfje", "zyfdxx", "统筹支付",
           "基本医保统筹基金已经支付的部分", "Amount",
           unit="元", required=True, source_object="InsuranceTransaction",
           source_field="yb_zyfdxx.bdtczfje", source_adapter_port=_ADAPTER, importance="core"),
        _m("zyfdxx.bdtczf", "zyfdxx", "统筹自付",
           "基本医保统筹段内按政策比例由个人承担的金额", "Amount",
           unit="元", required=True, source_object="InsuranceTransaction",
           source_field="yb_zyfdxx.bdtczf", source_adapter_port=_ADAPTER, importance="core"),
        _m("zyfdxx.bddezfje", "zyfdxx", "大额支付",
           "大额医疗费用补助基金支付的部分", "Amount",
           unit="元", source_object="InsuranceTransaction",
           source_field="yb_zyfdxx.bddegwyzfje", source_adapter_port=_ADAPTER, importance="core"),
        _m("zyfdxx.bddezf", "zyfdxx", "大额自付",
           "进入大额保障段后个人承担的部分", "Amount",
           unit="元", source_object="InsuranceTransaction",
           source_field="yb_zyfdxx.bddegwyzf", source_adapter_port=_ADAPTER, importance="core"),
        _m("zyfdxx.bdgryf", "zyfdxx", "个人应付",
           "包含多类个人负担，不等于统筹自付", "Amount",
           unit="元", required=True, source_object="InsuranceTransaction",
           source_field="yb_zyfdxx.bdgryf", source_adapter_port=_ADAPTER, importance="core"),
        # ── zyjyxx 住院交易 ──
        _m("zyjyxx.rylb", "zyjyxx", "人员类别", "参保人员类别（在职/退休等）", "Enum",
           source_object="InsuranceTransaction", source_field="yb_zyjyxx.PER_TYPE",
           source_adapter_port=_ADAPTER, value_domain="PERSON_TYPE", importance="core"),
        # ── zyfymx 住院费用明细 ──
        _m("zyfymx.xmbm", "zyfymx", "项目编码",
           "收费项目唯一编码，关联药品、耗材等目录", "Amount",
           source_field="yb_zyfymx.xmdm"),
        _m("zyfymx.xmmc", "zyfymx", "项目名称", "收费项目中文名称", "Amount",
           source_field="yb_zyfymx.xmmc"),
        _m("zyfymx.sfdj", "zyfymx", "收费等级", "收费项目甲乙丙等级分类", "Enum",
           source_field="yb_zyfymx.sfxmdj", value_domain="SFDJ"),
        _m("zyfymx.txbz", "zyfymx", "特需标志", "是否特需医疗项目", "Enum",
           source_field="yb_zyfymx.txbz", value_domain="BOOLEAN"),
        _m("zyfymx.sl", "zyfymx", "数量", None, "Amount",
           source_object="yb_zyfymx", source_field="yb_zyfymx.sl"),
        _m("zyfymx.fsrq", "zyfymx", "发生日期", None, "Amount",
           source_object="yb_zyfymx", source_field="yb_zyfymx.fsrq"),
        _m("zyfymx.ybnje", "zyfymx", "医保内金额", None, "Amount",
           source_object="yb_zyfymx", source_field="yb_zyfymx.ybnje"),
        _m("zyfymx.ybwje", "zyfymx", "医保外金额", None, "Amount",
           source_object="yb_zyfymx", source_field="yb_zyfymx.ybwje"),
        _m("zyfymx.zfbl", "zyfymx", "自付比例", None, "Amount",
           source_object="yb_zyfymx", source_field="yb_zyfymx.SP_SCALE"),
    ]
    for metric in metrics:
        store.save_metric(metric)
