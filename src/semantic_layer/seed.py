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
    ensure_policy_dictionaries(store)


# ── 政策规则字典（源自 raw/数据模型1.xlsx 字典 sheet，一次性转录）──────────
# xlsx 退为一次性种子：标准值转录进 seed，运行时不再读 xlsx。
# zcgz 维度指标 value_domain 引用此处 5 个域。
_POLICY_DICTIONARY_VALUES: dict[str, tuple[str, list[str]]] = {
    # domain_code: (name, standard_values)
    "insu_type": ("险种类别", [
        "城镇职工基本医疗保险", "城乡居民基本医疗保险", "生育保险",
        "城乡居民大病保险", "企业补充医疗保险",
    ]),
    "med_type": ("医疗类别", [
        "门诊-普通门急诊", "门诊-普通肾透析", "门诊-一般门特", "门诊-门诊贵重药品",
        "门诊-急诊留观", "门诊-家庭病床", "住院-普通住院", "住院-门特住院",
        "住院-精神病住院", "住院-生育", "住院-计划生育",
    ]),
    "hosp_lv": ("医疗机构等级", ["三级", "二级", "一级", "无等级"]),
    "psn_type": ("人群标签", [
        "在职职工", "灵活就业人员", "残疾人员", "优抚对象", "特困供养人员",
        "低收入救助人员", "劳动年龄内居民", "城乡老年人", "退休人员", "学生儿童",
    ]),
    "setl_type": ("结算方式", [
        "按项目付费", "单病种付费", "DRG付费", "DIP付费", "精神病床日定额",
        "精神病项目+定额", "精神病外院费用按普通住院", "精神病试出院",
        "器官移植抗排异定额", "生育定额", "计划生育定额", "产检定额",
    ]),
}


def ensure_policy_dictionaries(store: RegistryStore) -> None:
    """幂等 ensure：把政策规则字典（5 域）灌入语义层值域（standard_values）。

    [来源: raw/数据模型1.xlsx 字典 sheet 一次性转录；zcgz 维度指标 value_domain 引用]
    """
    for domain_code, (name, values) in _POLICY_DICTIONARY_VALUES.items():
        store.save_value_domain(ValueDomain(
            domain_code=domain_code, name=name,
            description=f"政策规则字典（源自数据模型1.xlsx，P8.3 种子）",
            standard_values=list(values),
        ))


def publish_seed_policy_object(registry) -> None:
    """发布 zcgz 种子对象（幂等），解锁提取契约（build_extraction_schema 只收 published）。

    [来源: docs/steering/政策知识管线开发计划.md Phase 8.3 — zcgz 指标 published]
    新鲜环境种子后调用一次；已有版本快照则跳过，避免重复发布产生新版本号。
    """
    obj = registry.get_object("zcgz")
    if obj is None:
        return
    if registry.list_object_versions("zcgz"):
        return  # 已发布过，幂等跳过
    registry.publish_object("zcgz", changelog="P8.3 种子发布政策规则对象，解锁提取契约")


def seed_semantic_layer(store: RegistryStore) -> None:
    """灌入真实语义层：3 域 / 7 对象 / 22 指标（对齐生产 PostgreSQL）。

    所有对象/指标初始为 status=draft。zcgz 的发布在种子完成后由
    ``publish_seed_policy_object``（经 ``publish_object`` 质量门禁）单独执行，
    以解锁提取契约——保持本函数纯净（多测试直接调用并断言 draft）。
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
        ("ybzc", "医保政策", 4),
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
        ("zcgz", "ybzc", "政策规则",
         "从非结构化政策原文中结构化提取的医保规则。每个规则19个字段，来源于政策知识管线(policy_pipeline)的LLM提取结果，存储于PostgreSQL policy_extractions表。来源路径：政策原文 → 政策片段提取 → 规则结构化 → 语义层指标。"),
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
       source_adapter_port=None, value_domain=None, importance="optional",
       default_value=None, metric_kind="field", indexed=False,
       extraction_hint=None, schema_version=1):
    """指标构造助手，减少重复参数。"""
    return Metric(
        metric_code=metric_code, object_code=object_code, name=name,
        definition=definition, metric_type="Atomic", semantic_type=semantic_type,
        unit=unit, required=required, source_object=source_object,
        source_field=source_field, source_adapter_port=source_adapter_port,
        value_domain=value_domain, importance=importance,
        default_value=default_value,
        metric_kind=metric_kind, indexed=indexed,
        extraction_hint=extraction_hint, schema_version=schema_version,
        version="1.0", status="draft",
    )


def _seed_metrics(store: RegistryStore) -> None:
    _ADAPTER = "InsuranceInterfacePort"
    metrics = [
        # ── djxx 参保人登记 ──
        _m("djxx.djh", "djxx", "登记号", "登记号", "String",
           source_field="bjybdb.yb_brdjxx.djh"),
        _m("djxx.hospital_level", "djxx", "医院等级",
           "医院等级（常量：数据库无此字段，固定三级医院）", "Enum",
           default_value="三级医院", importance="core"),
        _m("djxx.fund_type", "djxx", "险种类型", "基本医保险种类型", "Enum",
           source_object="InsuranceTransaction", source_field="bjybdb.yb_brdjxx.FUND_TYPE",
           source_adapter_port=_ADAPTER, value_domain="FUND_TYPE", importance="core"),
        _m("djxx.yllb", "djxx", "医疗类别", "本次医疗服务的业务类别", "Enum",
           source_object="InsuranceTransaction", source_field="bjybdb.yb_brdjxx.yllb",
           source_adapter_port=_ADAPTER, value_domain="YLLB"),
        # ── ypml 药品目录 ──
        _m("ypml.mzxj", "ypml", "带量采购门诊限价", "带量采购门诊限价", "Amount",
           source_object="yb_ypzdml", source_field="bjybdb.yb_ypzdml.A_mzxj"),
        _m("ypml.zyxj", "ypml", "带量采购住院限价", "带量采购住院限价", "Amount",
           source_object="yb_ypzdml", source_field="bjybdb.yb_ypzdml.A_zyxj"),
        # ── zydyxx 住院待遇 ──
        _m("zydyxx.bcqfje", "zydyxx", "起付线",
           "医保开始报销前需先由个人承担的固定金额", "Amount",
           unit="元", required=True, source_object="InsuranceTransaction",
           source_field="bjybdb.yb_dyxxzy.bcqfje", source_adapter_port=_ADAPTER, importance="core"),
        _m("zydyxx.bcybnje", "zydyxx", "医保内费用",
           "本次结算纳入医保报销范围的费用总额", "Amount",
           unit="元", source_object="InsuranceTransaction",
           source_field="bjybdb.yb_dyxxzy.bcybnje", source_adapter_port=_ADAPTER, importance="core"),
        # ── zyfdxx 住院分段 ──
        _m("zyfdxx.bdtczfje", "zyfdxx", "统筹支付",
           "基本医保统筹基金已经支付的部分", "Amount",
           unit="元", required=True, source_object="InsuranceTransaction",
           source_field="bjybdb.yb_zyfdxx.bdtczfje", source_adapter_port=_ADAPTER, importance="core"),
        _m("zyfdxx.bdtczf", "zyfdxx", "统筹自付",
           "基本医保统筹段内按政策比例由个人承担的金额", "Amount",
           unit="元", required=True, source_object="InsuranceTransaction",
           source_field="bjybdb.yb_zyfdxx.bdtczf", source_adapter_port=_ADAPTER, importance="core"),
        _m("zyfdxx.bddezfje", "zyfdxx", "大额支付",
           "大额医疗费用补助基金支付的部分", "Amount",
           unit="元", source_object="InsuranceTransaction",
           source_field="bjybdb.yb_zyfdxx.bddegwyzfje", source_adapter_port=_ADAPTER, importance="core"),
        _m("zyfdxx.bddezf", "zyfdxx", "大额自付",
           "进入大额保障段后个人承担的部分", "Amount",
           unit="元", source_object="InsuranceTransaction",
           source_field="bjybdb.yb_zyfdxx.bddegwyzf", source_adapter_port=_ADAPTER, importance="core"),
        _m("zyfdxx.bdgryf", "zyfdxx", "个人应付",
           "包含多类个人负担，不等于统筹自付", "Amount",
           unit="元", required=True, source_object="InsuranceTransaction",
           source_field="bjybdb.yb_zyfdxx.bdgryf", source_adapter_port=_ADAPTER, importance="core"),
        # ── zyjyxx 住院交易 ──
        _m("zyjyxx.rylb", "zyjyxx", "人员类别", "参保人员类别（在职/退休等）", "Enum",
           source_object="InsuranceTransaction", source_field="bjybdb.yb_zyjyxx.PER_TYPE",
           source_adapter_port=_ADAPTER, value_domain="PERSON_TYPE", importance="core"),
        # ── zyfymx 住院费用明细 ──
        _m("zyfymx.xmbm", "zyfymx", "项目编码",
           "收费项目唯一编码，关联药品、耗材等目录", "Amount",
           source_field="bjybdb.yb_zyfymx.xmdm"),
        _m("zyfymx.xmmc", "zyfymx", "项目名称", "收费项目中文名称", "Amount",
           source_field="bjybdb.yb_zyfymx.xmmc"),
        _m("zyfymx.sfdj", "zyfymx", "收费等级", "收费项目甲乙丙等级分类", "Enum",
           source_field="bjybdb.yb_zyfymx.sfxmdj", value_domain="SFDJ"),
        _m("zyfymx.txbz", "zyfymx", "特需标志", "是否特需医疗项目", "Enum",
           source_field="bjybdb.yb_zyfymx.txbz", value_domain="BOOLEAN"),
        _m("zyfymx.sl", "zyfymx", "数量", None, "Amount",
           source_object="yb_zyfymx", source_field="bjybdb.yb_zyfymx.sl"),
        _m("zyfymx.fsrq", "zyfymx", "发生日期", None, "Amount",
           source_object="yb_zyfymx", source_field="bjybdb.yb_zyfymx.fsrq"),
        _m("zyfymx.ybnje", "zyfymx", "医保内金额", None, "Amount",
           source_object="yb_zyfymx", source_field="bjybdb.yb_zyfymx.ybnje"),
        _m("zyfymx.ybwje", "zyfymx", "医保外金额", None, "Amount",
           source_object="yb_zyfymx", source_field="bjybdb.yb_zyfymx.ybwje"),
        _m("zyfymx.zfbl", "zyfymx", "自付比例", None, "Amount",
           source_object="yb_zyfymx", source_field="bjybdb.yb_zyfymx.SP_SCALE"),
        # ── zcgz 政策规则（19 字段，来源: 非结构化政策 → LLM 提取 → policy_extractions）──
        # 标识符
        _m("zcgz.rule_id", "zcgz", "规则ID", "系统生成的规则唯一标识", "String",
           source_field="zcgz.rule_id", source_object="policy_extractions"),
        _m("zcgz.fact_id", "zcgz", "来源事实ID", "关联的policy_fact标识", "String",
           source_field="zcgz.fact_id", source_object="policy_extractions"),
        _m("zcgz.policy_id", "zcgz", "政策文件ID", "关联的原始政策文件标识", "String",
           source_field="zcgz.policy_id", source_object="policy_extractions"),
        _m("zcgz.clause_id", "zcgz", "条款ID", "关联的政策条款标识", "String",
           source_field="zcgz.clause_id", source_object="policy_extractions"),
        _m("zcgz.source_text", "zcgz", "原始政策文本", "用于解释和溯源的原始文本", "String",
           source_field="zcgz.source_text", source_object="policy_extractions"),
        # 维度指标（有字典关联）
        _m("zcgz.insu_type", "zcgz", "险种类别", "城镇职工、城乡居民、超转人员、生育保险", "Enum",
           source_field="zcgz.insu_type", source_object="policy_extractions", value_domain="insu_type",
           indexed=True, extraction_hint="参保险种，取值见 insu_type 字典：城镇职工/城乡居民/超转人员/生育保险"),
        _m("zcgz.med_type", "zcgz", "医疗类别", "住院-普通住院、门诊-一般门特", "Enum",
           source_field="zcgz.med_type", source_object="policy_extractions", value_domain="med_type",
           indexed=True, extraction_hint="医疗服务类别，取值见 med_type 字典：住院/门诊/门诊特殊病等"),
        _m("zcgz.hosp_lv", "zcgz", "医疗机构等级", "一级医院、二级医院、三级医院、社区", "Enum",
           source_field="zcgz.hosp_lv", source_object="policy_extractions", value_domain="hosp_lv",
           indexed=True, extraction_hint="定点医疗机构等级，取值见 hosp_lv 字典：一级/二级/三级/社区"),
        _m("zcgz.psn_type", "zcgz", "人群标签", "退休、在职、70岁以上、学生儿童（嵌套字段）", "Enum",
           source_field="zcgz.psn_type", source_object="policy_extractions", value_domain="psn_type",
           indexed=True, extraction_hint="适用人群标签，取值见 psn_type 字典：在职/退休/学生儿童等"),
        _m("zcgz.setl_type", "zcgz", "结算方式", "按项目付费、DRG、单病种、床日定额", "Enum",
           source_field="zcgz.setl_type", source_object="policy_extractions", value_domain="setl_type",
           indexed=True, extraction_hint="付费/结算方式，取值见 setl_type 字典：按项目/DRG/单病种/床日定额"),
        _m("zcgz.admission_order", "zcgz", "住院次数", "第几次住院", "Enum",
           source_field="zcgz.admission_order", source_object="policy_extractions"),
        # 数值指标
        _m("zcgz.payment_ratio", "zcgz", "支付比例", "医保基金支付比例", "Amount",
           unit="%", source_field="zcgz.payment_ratio", source_object="policy_extractions"),
        # 个人支付比例（自付一）：与基金支付比例互补，退休人员=职工个人支付比例×系数
        _m("zcgz.personal_payment_ratio", "zcgz", "个人支付比例",
           "参保人个人承担的支付比例（自付一），与基金支付比例互补；退休人员等折算时由系数×基数得出",
           "Amount", unit="%",
           source_field="zcgz.personal_payment_ratio", source_object="policy_extractions",
           extraction_hint="原文「职工支付X%」「个人支付X%」时的个人承担比例；退休等折算时由系数×基数得出"),
        _m("zcgz.deductible_amount", "zcgz", "起付金额", "起付标准金额", "Amount",
           unit="元", source_field="zcgz.deductible_amount", source_object="policy_extractions"),
        _m("zcgz.cap_amount", "zcgz", "封顶金额", "最高支付限额金额", "Amount",
           unit="元", source_field="zcgz.cap_amount", source_object="policy_extractions"),
        # 条件指标
        _m("zcgz.amount_band", "zcgz", "金额分段", "金额分段区间", "String",
           source_field="zcgz.amount_band", source_object="policy_extractions"),
        _m("zcgz.time_period", "zcgz", "时间周期", "医保年度等时间周期", "String",
           source_field="zcgz.time_period", source_object="policy_extractions"),
        # 元指标
        _m("zcgz.priority", "zcgz", "规则优先级", "规则优先级", "String",
           source_field="zcgz.priority", source_object="policy_extractions"),
        _m("zcgz.rule_type", "zcgz", "规则类型", "动态规则类型（嵌套字段）", "String",
           source_field="zcgz.rule_type", source_object="policy_extractions",
           indexed=True, extraction_hint="规则的业务类别，如 起付线/报销比例/封顶线/分段比例"),
        _m("zcgz.rule_value", "zcgz", "规则值", "动态规则值（嵌套字段）", "String",
           source_field="zcgz.rule_value", source_object="policy_extractions"),
        # 迭代 19 修改5：相对比例与跨单元引用（退休人员案例缺失项）
        _m("zcgz.personal_payment_coefficient", "zcgz", "个人支付比例系数",
           "相对支付比例：以职工支付比例等为基数的乘数系数，如「为职工支付比例的60%」→ 0.6", "Ratio",
           source_field="zcgz.personal_payment_coefficient", source_object="policy_extractions",
           extraction_hint="原文相对表达「为…的X%」时提取系数 X（如60%→0.6），并保留基数引用（如职工支付比例）"),
        _m("zcgz.referenced_clause", "zcgz", "跨单元引用条款",
           "本单元引用的前文条款/单元标识（如「上述比例」「按前款」→ 被引用的条款或单元）", "String",
           source_field="zcgz.referenced_clause", source_object="policy_extractions",
           extraction_hint="原文出现「上述/前款/按第X条」等引用时，提取被引用的条款标识或单元路径"),
    ]
    for metric in metrics:
        store.save_metric(metric)
