"""语义层种子数据 — 对齐 PostgreSQL 生产环境的真实定义。

数据来源：PostgreSQL semantic_domains / semantic_objects / semantic_metrics 表导出。
内容：基础业务对象、指标，以及门诊交易/费用明细查询模型。

用途：
1. ``InMemoryRegistryStore``（``USE_MEMORY_STORAGE=1`` / 单元测试）的种子数据；
2. ``PostgresRegistryStore._seed_if_empty`` 首次启动的初始化数据源。

编码与 ``skill_manifest.yaml`` 的 ``needed_objects`` 一致（zydyxx.* 物理编码），
是 skill 依赖的唯一真源。旧 Settlement.* 编码已废弃。
"""
from src.semantic_layer.models import (
    BusinessDomain, BusinessObject, Metric, ValueDomain, ValueDomainMapping,
    SemanticDataset, DatasetKey, SemanticField, DatasetRelation, DataQualityRule,
)
from src.semantic_layer.registry import RegistryStore


OUTPATIENT_P1_TRADE_FIELDS = (
    ("data_batch_id", "String"),
    ("source_lsn", "String"),
    ("semantic_version", "String"),
    ("quality_status", "Enum"),
    ("context_quality", "Enum"),
    ("settlement_chain_id", "String"),
    ("settlement_lifecycle", "Enum"),
)

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
        "80": "军休干部", "999": "国家平台险种",
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
    "MZ_PERSON_TYPE": {
        "11": "在职", "12": "在职长期驻外", "14": "城镇婴幼儿",
        "15": "城镇学生", "16": "城镇非在校生", "17": "城镇老年人",
        "21": "退休", "31": "离休", "35": "在职司局级医照人员",
        "37": "在职副部级医照人员", "70": "城镇无业居民",
        "133": "在职正部级医疗照顾人员", "140": "征地超转人员",
        "143": "离休副市（部）长级标准人员", "171": "在职突出贡献专家",
        "172": "退休突出贡献专家", "173": "离休突出贡献专家",
        "174": "在职高端人才A类", "175": "退休高端人才A类",
        "176": "离休高端人才A类", "177": "在职高端人才B类",
        "178": "退休高端人才B类", "179": "离休高端人才B类",
        "180": "在职高端人才C类", "181": "退休高端人才C类",
        "182": "离休高端人才C类", "803": "军休公费医疗人员",
        "806": "退休副省（部）长级标准报销医疗费人员",
    },
    "MZ_CURE_TYPE": {
        "11": "普通门诊", "17": "门诊挂号", "18": "急诊挂号", "19": "普通急诊",
    },
    "MILITARY_DISABILITY_LEVEL": {
        "0": "不享受伤残待遇", "1": "享受一级伤残待遇", "2": "享受二级伤残待遇",
        "3": "享受三级伤残待遇", "4": "享受四级伤残待遇", "5": "享受五级伤残待遇",
        "6": "享受六级伤残待遇", "7": "享受七级伤残待遇", "8": "享受八级伤残待遇",
        "9": "享受九级伤残待遇",
    },
    "NATIONAL_FUND_TYPE": {
        "310": "城镇职工", "320": "城乡居民", "330": "离休人员",
        "340": "超转人员", "350": "医照人员", "360": "生育保险",
    },
    "MZ_HOSPITAL_LEVEL_BY_CODE": {},
}


def ensure_yb_dictionary_mappings(store: RegistryStore) -> None:
    """幂等 ensure：把医保字典码→标签映射补入语义层值域。

    每次进程启动调用一次（幂等，upsert）。弥合语义层与 business_sql.yaml
    的「转换差异」：语义层取数后应用 resolve_value，即可产出与手写 CASE 一致的中文标签。
    """
    domain_names = {
        "FUND_TYPE": "险种类型", "YLLB": "医疗类别", "PERSON_TYPE": "人员类别",
        "MZ_PERSON_TYPE": "门诊人员类别", "MZ_CURE_TYPE": "门诊医疗类别",
        "MILITARY_DISABILITY_LEVEL": "军残待遇等级",
        "NATIONAL_FUND_TYPE": "国家平台险种",
        "MZ_HOSPITAL_LEVEL_BY_CODE": "门诊医疗机构等级",
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
    并集语义：域已存在时只补齐缺失的 seed 值，保留治理新增（如 hosp_lv「社区」）；
    整值覆盖会把语义发现/人工裁决新增的值在每次重启时丢掉。
    """
    for domain_code, (name, values) in _POLICY_DICTIONARY_VALUES.items():
        existing = store.get_value_domain(domain_code)
        if existing is None:
            store.save_value_domain(ValueDomain(
                domain_code=domain_code, name=name,
                description="政策规则字典（源自数据模型1.xlsx，P8.3 种子）",
                standard_values=list(values),
            ))
            continue
        missing = [v for v in values if v not in existing.standard_values]
        if missing:
            store.save_value_domain(ValueDomain(
                domain_code=domain_code, name=existing.name or name,
                description=existing.description,
                standard_values=list(existing.standard_values) + missing,
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


def _seed_settlement_query_model(store: RegistryStore) -> None:
    """住院费用查询模型：登记锚点、待遇分段、支付分段和交易信息。"""
    object_code = "inpatient_settlement"
    if store.get_object(object_code) is None:
        store.save_object(BusinessObject(
            object_code=object_code, domain_code="ybjs", name="住院结算",
            definition="以登记号锚定整次住院，按结算分段预聚合并汇总全部住院费用。",
            status="draft",
        ))
    if store.get_dataset("inpatient_registration") is not None:
        return
    datasets = [
        SemanticDataset(dataset_code="inpatient_registration", object_code=object_code,
                        datasource_id="bjybdb", table_name="yb_brdjxx", name="住院登记"),
        SemanticDataset(dataset_code="benefit_segments", object_code=object_code,
                        datasource_id="bjybdb", table_name="yb_dyxxzy", name="住院待遇分段"),
        SemanticDataset(dataset_code="payment_segments", object_code=object_code,
                        datasource_id="bjybdb", table_name="yb_zyfdxx", name="住院支付分段"),
        SemanticDataset(dataset_code="inpatient_transaction", object_code=object_code,
                        datasource_id="bjybdb", table_name="yb_zyjyxx", name="住院交易"),
    ]
    for dataset in datasets:
        store.save_dataset(dataset)

    keys = [
        DatasetKey(key_code="registration_pk", dataset_code="inpatient_registration",
                   entity_code="inpatient_admission", key_type="primary", columns=["djh"]),
        DatasetKey(key_code="benefit_segment_pk", dataset_code="benefit_segments",
                   entity_code="admission_segment", key_type="primary",
                   columns=["djh", "bcqsrq", "zqxh"]),
        DatasetKey(key_code="benefit_admission_fk", dataset_code="benefit_segments",
                   entity_code="inpatient_admission", key_type="foreign", columns=["djh"]),
        DatasetKey(key_code="benefit_payment_key", dataset_code="benefit_segments",
                   entity_code="admission_segment", key_type="unique", columns=["djh", "bcqsrq"]),
        DatasetKey(key_code="payment_segment_pk", dataset_code="payment_segments",
                   entity_code="admission_segment", key_type="primary",
                   columns=["djh", "bdqsrq", "bdjsrq"]),
        DatasetKey(key_code="payment_admission_fk", dataset_code="payment_segments",
                   entity_code="inpatient_admission", key_type="foreign", columns=["djh"]),
        DatasetKey(key_code="payment_segment_fk", dataset_code="payment_segments",
                   entity_code="admission_segment", key_type="foreign", columns=["djh", "bdqsrq"]),
        DatasetKey(key_code="transaction_pk", dataset_code="inpatient_transaction",
                   entity_code="inpatient_admission", key_type="primary", columns=["djh"]),
    ]
    for key in keys:
        store.save_dataset_key(key)

    field_specs = [
        ("inpatient_registration.registration_id", "inpatient_registration", "djh", "登记号", "identifier", "String", False),
        ("inpatient_registration.insurance_type", "inpatient_registration", "FUND_TYPE", "险种类型", "dimension", "Enum", True),
        ("inpatient_registration.service_type", "inpatient_registration", "yllb", "医疗类别", "dimension", "Enum", True),
        ("benefit_segments.admission_id", "benefit_segments", "djh", "住院登记号", "identifier", "String", False),
        ("benefit_segments.segment_start_date", "benefit_segments", "bcqsrq", "分段开始日期", "identifier", "Date", False),
        ("benefit_segments.segment_end_date", "benefit_segments", "bcjsrq", "分段结束日期", "dimension", "Date", True),
        ("benefit_segments.cycle_no", "benefit_segments", "zqxh", "周期序号", "identifier", "String", False),
        ("benefit_segments.deductible", "benefit_segments", "bcqfje", "起付线", "fact", "Amount", True),
        ("benefit_segments.medical_insurance_inner_amount", "benefit_segments", "bcybnje", "医保内费用", "fact", "Amount", True),
        ("payment_segments.admission_id", "payment_segments", "djh", "住院登记号", "identifier", "String", False),
        ("payment_segments.segment_start_date", "payment_segments", "bdqsrq", "分段开始日期", "identifier", "Date", False),
        ("payment_segments.segment_end_date", "payment_segments", "bdjsrq", "分段结束日期", "identifier", "Date", False),
        ("payment_segments.total_amount", "payment_segments", "bdfyzje", "住院总费用", "fact", "Amount", True),
        ("payment_segments.basic_pooling_payment", "payment_segments", "bdtczfje", "统筹支付", "fact", "Amount", True),
        ("payment_segments.basic_pooling_self_pay", "payment_segments", "bdtczf", "统筹自付", "fact", "Amount", True),
        ("payment_segments.large_amount_payment", "payment_segments", "bddegwyzfje", "大额支付", "fact", "Amount", True),
        ("payment_segments.large_amount_self_pay", "payment_segments", "bddegwyzf", "大额自付", "fact", "Amount", True),
        ("payment_segments.personal_total_pay", "payment_segments", "bdgryf", "个人总支付", "fact", "Amount", True),
        ("inpatient_transaction.admission_id", "inpatient_transaction", "djh", "住院登记号", "identifier", "String", False),
        ("inpatient_transaction.person_type", "inpatient_transaction", "PER_TYPE", "人员类别", "dimension", "Enum", True),
    ]
    for code, dataset, column, name, role, semantic_type, nullable in field_specs:
        store.save_field(SemanticField(
            field_code=code, dataset_code=dataset, column_name=column, name=name,
            field_role=role, semantic_type=semantic_type, nullable=nullable,
            value_domain={
                "inpatient_registration.insurance_type": "FUND_TYPE",
                "inpatient_registration.service_type": "YLLB",
                "inpatient_transaction.person_type": "PERSON_TYPE",
            }.get(code),
        ))

    for relation in [
        DatasetRelation(relation_code="registration_to_benefit", object_code=object_code,
                        from_dataset="inpatient_registration", from_key="registration_pk",
                        to_dataset="benefit_segments", to_key="benefit_admission_fk",
                        cardinality="one_to_many"),
        DatasetRelation(relation_code="benefit_to_payment", object_code=object_code,
                        from_dataset="benefit_segments", from_key="benefit_payment_key",
                        to_dataset="payment_segments", to_key="payment_segment_fk",
                        cardinality="one_to_one"),
        DatasetRelation(relation_code="registration_to_transaction", object_code=object_code,
                        from_dataset="inpatient_registration", from_key="registration_pk",
                        to_dataset="inpatient_transaction", to_key="transaction_pk",
                        cardinality="one_to_one"),
    ]:
        store.save_dataset_relation(relation)

    query_metrics = [
        ("total_amount", "住院总费用", "payment_segments.total_amount", "sum"),
        ("medical_insurance_inner_amount", "医保内费用", "benefit_segments.medical_insurance_inner_amount", "sum"),
        ("deductible", "起付线", "benefit_segments.deductible", "sum"),
        ("basic_pooling_payment", "统筹支付", "payment_segments.basic_pooling_payment", "sum"),
        ("basic_pooling_self_pay", "统筹自付", "payment_segments.basic_pooling_self_pay", "sum"),
        ("large_amount_payment", "大额支付", "payment_segments.large_amount_payment", "sum"),
        ("large_amount_self_pay", "大额自付", "payment_segments.large_amount_self_pay", "sum"),
        ("personal_total_pay", "个人总支付", "payment_segments.personal_total_pay", "sum"),
        ("yearly_cycle_count", "结算周期数", "benefit_segments.cycle_no", "count_distinct"),
        ("person_type", "人员类别", "inpatient_transaction.person_type", "max"),
        ("insurance_type", "险种类型", "inpatient_registration.insurance_type", "max"),
        ("service_type", "医疗类别", "inpatient_registration.service_type", "max"),
    ]
    for short_code, name, field_code, aggregation in query_metrics:
        store.save_metric(Metric(
            metric_code=f"{object_code}.{short_code}", object_code=object_code,
            name=name, definition=f"整次住院{name}", metric_type="aggregate",
            semantic_type="Amount" if aggregation in {"sum", "count_distinct"} else "Enum",
            unit="元" if aggregation == "sum" else None,
            fact_field_code=field_code, aggregation=aggregation,
            status="draft", importance="core",
        ))

    for rule in [
        DataQualityRule(rule_code="benefit_segment_key_unique", object_code=object_code,
                        rule_type="uniqueness", target_dataset_or_relation="benefit_segments",
                        severity="blocking", parameters={"key_code": "benefit_segment_pk"}),
        DataQualityRule(rule_code="payment_segment_key_unique", object_code=object_code,
                        rule_type="uniqueness", target_dataset_or_relation="payment_segments",
                        severity="blocking", parameters={"key_code": "payment_segment_pk"}),
        DataQualityRule(rule_code="payment_segments_cover_segment_spine", object_code=object_code,
                        rule_type="coverage", target_dataset_or_relation="benefit_to_payment",
                        severity="warning", parameters={"reference_dataset": "benefit_segments"}),
        DataQualityRule(rule_code="registration_anchor_not_null", object_code=object_code,
                        rule_type="not_null", target_dataset_or_relation="inpatient_registration",
                        severity="blocking", parameters={"field_code": "inpatient_registration.registration_id"}),
    ]:
        store.save_quality_rule(rule)




def publish_seed_query_object(registry) -> None:
    """幂等发布住院结算查询模型，供运行时只读已发布快照。"""
    if registry.get_object("inpatient_settlement") is None:
        return
    if registry.list_object_versions("inpatient_settlement"):
        return
    registry.publish_object(
        "inpatient_settlement",
        changelog="住院费用整次住院分段汇总查询模型",
    )



def publish_seed_outpatient_query_object(registry) -> None:
    """幂等发布门诊结算查询模型，供内存运行时和测试使用。"""
    if registry.get_object("mzjyxx") is None or registry.list_object_versions("mzjyxx"):
        return
    registry.publish_object("mzjyxx", changelog="门诊交易与费用明细查询模型")


def ensure_outpatient_query_model(store: RegistryStore) -> None:
    """为已有 Registry 幂等补入门诊查询对象与元数据。"""
    if store.get_object("mzjyxx") is None:
        store.save_object(BusinessObject(
            object_code="mzjyxx", domain_code="ybjs", name="门诊结算",
            definition="settlement_id 对应 T_TradeNo，以门诊交易号锚定单次交易，并关联费用项目明细。",
            identifier="settlement_id", version="1.0", status="draft",
        ))
    _seed_outpatient_query_model(store)


def switch_outpatient_query_model_to_postgres(store: RegistryStore) -> None:
    """把现有门诊模型绑定切到已发布的 PostgreSQL 视图。"""
    for dataset_code in ("mz_trade", "mz_fee_item"):
        dataset = store.get_dataset(dataset_code)
        if dataset is None:
            raise ValueError(f"门诊数据集不存在: {dataset_code}")
        store.save_dataset(dataset.model_copy(update={
            "datasource_id": "outpatient_postgres",
            "schema_name": "public",
            "table_name": dataset_code,
            "status": "draft",
        }))
    for column, semantic_type in OUTPATIENT_P1_TRADE_FIELDS:
        store.save_field(SemanticField(
            field_code=f"mz_trade.{column}", dataset_code="mz_trade",
            column_name=column, name=column, field_role="dimension",
            semantic_type=semantic_type, nullable=column != "data_batch_id",
        ))


def seed_semantic_layer(store: RegistryStore) -> None:
    """灌入真实语义层基础对象、指标和门诊查询模型。

    所有对象/指标初始为 status=draft。zcgz 的发布在种子完成后由
    ``publish_seed_policy_object``（经 ``publish_object`` 质量门禁）单独执行，
    以解锁提取契约——保持本函数纯净（多测试直接调用并断言 draft）。
    """
    _seed_domains(store)
    _seed_objects(store)
    _seed_metrics(store)
    _seed_settlement_query_model(store)
    ensure_outpatient_query_model(store)
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
        ("mzjyxx", "ybjs", "门诊结算",
         "settlement_id 对应 T_TradeNo，以门诊交易号锚定单次交易，并关联费用项目明细。"),
    ]
    for code, domain, name, definition in objects:
        store.save_object(BusinessObject(
            object_code=code, domain_code=domain, name=name, definition=definition,
            identifier="settlement_id" if code == "mzjyxx" else None,
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


def _seed_outpatient_query_model(store: RegistryStore) -> None:
    """门诊交易和费用明细查询模型；生产口径仍须经发现中心审核后发布。"""
    object_code = "mzjyxx"
    if store.get_dataset("mz_trade") is not None:
        return
    for dataset in [
        SemanticDataset(
            dataset_code="mz_trade", object_code=object_code,
            datasource_id="outpatient_postgres", schema_name="public",
            table_name="mz_trade", name="门诊交易",
        ),
        SemanticDataset(
            dataset_code="mz_fee_item", object_code=object_code,
            datasource_id="outpatient_postgres", schema_name="public",
            table_name="mz_fee_item", name="门诊费用明细",
        ),
    ]:
        store.save_dataset(dataset)

    for key in [
        DatasetKey(
            key_code="mz_trade_pk", dataset_code="mz_trade",
            entity_code="outpatient_transaction", key_type="primary",
            columns=["T_TradeNo"],
        ),
        DatasetKey(
            key_code="mz_fee_item_pk", dataset_code="mz_fee_item",
            entity_code="outpatient_fee_item", key_type="primary",
            columns=["T_TradeNo", "ItemId", "ItemNo"],
        ),
        DatasetKey(
            key_code="mz_fee_item_trade_fk", dataset_code="mz_fee_item",
            entity_code="outpatient_transaction", key_type="foreign",
            columns=["T_TradeNo"],
        ),
    ]:
        store.save_dataset_key(key)

    trade_types = {
        "String": {
            "T_TradeNo", "T_SetTid", "T_FeeNo", "T_OraginalTradeNo",
            "T_HospCode", "PN_ChronicCode", "T_pneno",
        },
        "Date": {"T_TradeDate", "T_OraginalTradeDate", "SETL_DATE"},
        "Count": {"TB_MZTimes", "TA_MZTimes"},
        "Ratio": {"NT_OUT2_SCALE"},
        "Enum": {
            "T_State", "T_HasRefundmented", "T_PartialReturnFlag",
            "NP_Settle_State", "NT_ReTradeFlag", "T_DiagType", "P_FundType",
            "PN_PersonType", "T_CureType", "P_JCLevel", "P_HospFlag",
            "P_Official", "PN_ChronicFlag", "PN_IsChronicHosp",
            "PN_NoRightReason", "PN_OutTransaction", "PN_NationFundType",
            "P_retirementflag", "P_CivilFlag", "P_CivilType",
            "RETIRE_OFFICER_FLAG", "T_GFBelongFlag", "T_CompHospFlag",
            "T_SpSetlFlag", "NT_AllSelfPayFlag",
        },
    }
    trade_amounts = {
        "T_FirstPay", "T_SelfPay1", "T_SelfPay2", "T_SelfPayAll",
        "T_BigPay", "T_BigSelfPay", "T_BeyondBig", "T_FundPay",
        "T_PersonCountPay", "T_CashPay", "PN_PersonCount",
        "T_PersonCountAfter", "T_BCPay", "T_JCPay", "T_FeeAll",
        "T_FeeIn", "T_FeeOut", "T_OfficalPay", "T_BigillPay",
        "NT_BasicPay", "NT_CivilPay", "NT_OtherPay", "NT_AgencySumPay",
        "RETIRE_OFFICER_PAY", "NT_OUT2_PRICE", "TB_FeeIn", "TA_FeeIn",
        "TB_BigPay", "TA_BigPay", "TB_FeeAfterBig", "TA_FeeAfterBig",
        "TB_BeyondFeeIn", "TA_BeyondFeeIn", "TB_BigillComm",
        "TA_BigillComm", "TB_BigillPay", "TA_BigillPay", "TB_CivilComm",
        "TA_CivilComm", "TB_CivilPay", "TA_CivilPay", "TB_FeeInL1",
        "TA_FeeInL1", "TB_BigPayL1", "TA_BigPayL1",
        "TB_FeeAfterBigL1", "TA_FeeAfterBigL1",
    }
    trade_types["Amount"] = trade_amounts

    detail_types = {
        "String": {
            "T_TradeNo", "ItemId", "ItemNo", "ItemCode", "StandardCode", "ItemName",
        },
        "Enum": {"ItemType", "FeeType", "F_LEVEL", "SPEDRUG_FLAG", "State"},
        "Count": {"Count"},
        "Ratio": {"FEE_SP_SCALE"},
        "Amount": {
            "UnitPrice", "Fee", "FeeIn", "FeeOut", "SelfPay2", "FEE_MEDIC_L", "MEDIC_L",
        },
    }
    display_names = {
        "T_SetTid": "结算标识", "T_TradeNo": "交易号", "T_FeeNo": "费用号",
        "T_TradeDate": "交易日期", "T_State": "交易状态",
        "P_FundType": "险种类型", "PN_PersonType": "人员类别",
        "T_CureType": "医疗类别", "P_JCLevel": "军残待遇等级",
        "T_HospCode": "医疗机构编码", "HospitalLevel": "医疗机构等级",
        "T_FirstPay": "起付金额", "T_SelfPay1": "个人自付一",
        "T_SelfPay2": "个人自付二", "T_SelfPayAll": "个人支付总金额",
        "T_BigPay": "大额基金支付", "T_BigSelfPay": "大额自付",
        "T_FundPay": "基金支付总金额", "T_PersonCountPay": "个人账户支付",
        "T_CashPay": "现金支付", "T_FeeAll": "费用总金额",
        "T_FeeIn": "医保范围内金额", "T_FeeOut": "医保范围外金额",
        "T_OfficalPay": "公务员或公疗支付", "T_BigillPay": "大病支付",
        "T_BCPay": "补充保险支付", "T_JCPay": "军残补助支付",
        "RETIRE_OFFICER_PAY": "退役医疗支付", "ItemName": "费用项目名称",
        "F_LEVEL": "项目医保等级", "Fee": "项目金额",
        "FeeIn": "项目医保内金额", "FeeOut": "项目医保外金额",
        "FEE_SP_SCALE": "项目先自付比例", "FEE_MEDIC_L": "项目医保限额",
        "MEDIC_L": "项目医疗限额", "SPEDRUG_FLAG": "特殊药品标志",
    }
    key_columns = {"T_TradeNo", "ItemId", "ItemNo"}
    value_domains = {
        "P_FundType": "FUND_TYPE", "PN_PersonType": "MZ_PERSON_TYPE",
        "T_CureType": "MZ_CURE_TYPE", "P_JCLevel": "MILITARY_DISABILITY_LEVEL",
        "PN_NationFundType": "NATIONAL_FUND_TYPE",
    }

    def save_fields(dataset_code: str, specs: dict[str, set[str]]) -> None:
        for semantic_type, columns in specs.items():
            for column in sorted(columns):
                store.save_field(SemanticField(
                    field_code=f"{dataset_code}.{column}", dataset_code=dataset_code,
                    column_name=column, name=display_names.get(column, column),
                    field_role=(
                        "identifier" if column in key_columns
                        else "fact" if semantic_type in {"Amount", "Count", "Ratio"}
                        else "dimension"
                    ),
                    semantic_type=semantic_type, value_domain=value_domains.get(column),
                    nullable=column not in key_columns,
                ))

    save_fields("mz_trade", trade_types)
    save_fields("mz_fee_item", detail_types)
    for column, semantic_type in OUTPATIENT_P1_TRADE_FIELDS:
        store.save_field(SemanticField(
            field_code=f"mz_trade.{column}", dataset_code="mz_trade",
            column_name=column, name=column, field_role="dimension",
            semantic_type=semantic_type, nullable=column != "data_batch_id",
        ))

    relation = DatasetRelation(
        relation_code="mz_trade_to_fee_item", object_code=object_code,
        from_dataset="mz_trade", from_key="mz_trade_pk",
        to_dataset="mz_fee_item", to_key="mz_fee_item_trade_fk",
        cardinality="one_to_many",
    )
    store.save_dataset_relation(relation)

    core_metrics = {
        "T_TradeNo", "T_TradeDate", "T_State", "P_FundType", "PN_PersonType",
        "T_CureType", "P_JCLevel", "T_FirstPay", "T_SelfPay1", "T_SelfPay2",
        "T_SelfPayAll", "T_BigPay", "T_BigSelfPay", "T_FundPay",
        "T_PersonCountPay", "T_CashPay", "T_FeeAll", "T_FeeIn", "T_FeeOut",
    }
    for semantic_type, columns in trade_types.items():
        for column in sorted(columns):
            store.save_metric(Metric(
                metric_code=f"{object_code}.{column}", object_code=object_code,
                name=display_names.get(column, column),
                definition=f"门诊交易字段：{display_names.get(column, column)}",
                metric_type="aggregate", semantic_type=semantic_type,
                unit="元" if semantic_type == "Amount" else "%" if semantic_type == "Ratio" else None,
                source_object="o_Trade", source_field=f"o_Trade.{column}",
                value_domain=value_domains.get(column),
                importance="core" if column in core_metrics else "optional",
                fact_field_code=f"mz_trade.{column}", aggregation="max",
            ))

    store.save_metric(Metric(
        metric_code=f"{object_code}.HospitalLevel", object_code=object_code,
        name="医疗机构等级", definition="由门诊交易医疗机构编码经医院字典解析的机构等级",
        metric_type="aggregate", semantic_type="Enum", source_object="o_Trade",
        source_field="o_Trade.T_HospCode", value_domain="MZ_HOSPITAL_LEVEL_BY_CODE",
        importance="core", fact_field_code="mz_trade.T_HospCode", aggregation="max",
    ))

    detail_metric_codes = {"SelfPay2": "FeeItem_SelfPay2", "State": "FeeItem_State"}
    detail_sum = {"Count", "Fee", "FeeIn", "FeeOut", "SelfPay2"}
    for semantic_type, columns in detail_types.items():
        for column in sorted(columns - {"T_TradeNo", "ItemId", "ItemNo"}):
            code = detail_metric_codes.get(column, column)
            store.save_metric(Metric(
                metric_code=f"{object_code}.{code}", object_code=object_code,
                name=display_names.get(column, column),
                definition=f"门诊费用明细字段：{display_names.get(column, column)}",
                metric_type="aggregate", semantic_type=semantic_type,
                unit="元" if semantic_type == "Amount" else "%" if semantic_type == "Ratio" else None,
                source_object="o_FeeItem", source_field=f"o_FeeItem.{column}",
                importance="core" if column in {"ItemName", "Fee", "FeeIn", "FeeOut"} else "optional",
                fact_field_code=f"mz_fee_item.{column}",
                aggregation="sum" if column in detail_sum else "max",
            ))

    governed = {
        "T_State": ("门诊有效结算笔数", "count", "笔", 0),
        "T_FeeAll": ("门诊总费用", "sum", "元", 2),
        "T_FundPay": ("门诊统筹基金支付金额", "sum", "元", 2),
        "T_SelfPayAll": ("门诊个人支付金额", "sum", "元", 2),
    }
    for column, (name, aggregation, unit, precision) in governed.items():
        metric = store.get_metric(f"{object_code}.{column}")
        if metric is None:
            continue
        store.save_metric(metric.model_copy(update={
            "name": name, "definition": f"按门诊交易统计{name}",
            "synonyms": [name], "compatible_dimensions": ["time", "organization.department", "insurance_type", "settlement_status"],
            "default_time_role": "settlement_time", "refresh_frequency": "5m",
            "permission_level": "summary", "owner": "医保数据组", "reviewer": "医保业务组",
            "precision": precision, "unit": unit, "aggregation": aggregation,
            "status": "published",
        }))
    store.save_metric(Metric(
        metric_code=f"{object_code}.average_fee", object_code=object_code,
        name="门诊次均费用", definition="门诊总费用除以有效结算笔数",
        metric_type="aggregate", semantic_type="Amount", unit="元", precision=2,
        fact_field_code="mz_trade.T_FeeAll", aggregation="avg",
        dependencies=[f"{object_code}.T_FeeAll", f"{object_code}.T_State"],
        synonyms=["门诊平均费用", "次均费用"],
        compatible_dimensions=["time", "organization.department", "insurance_type", "settlement_status"],
        default_time_role="settlement_time", refresh_frequency="5m", permission_level="summary",
        owner="医保数据组", reviewer="医保业务组", source_object="mz_trade", status="published",
    ))
    store.save_metric(Metric(
        metric_code=f"{object_code}.insured_encounter_count", object_code=object_code,
        name="门诊医保就诊人次", definition="按唯一就诊标识统计医保门诊人次",
        metric_type="Aggregate", semantic_type="Count", unit="人次", aggregation="count_distinct",
        fact_field_code="mz_trade.T_TradeNo", source_object="mz_trade", status="draft",
    ))

    for rule in [
        DataQualityRule(
            rule_code="mz_trade_key_unique", object_code=object_code,
            rule_type="uniqueness", target_dataset_or_relation="mz_trade",
            severity="blocking", parameters={"key_code": "mz_trade_pk"},
        ),
        DataQualityRule(
            rule_code="mz_fee_item_key_unique", object_code=object_code,
            rule_type="uniqueness", target_dataset_or_relation="mz_fee_item",
            severity="blocking", parameters={"key_code": "mz_fee_item_pk"},
        ),
        DataQualityRule(
            rule_code="mz_fee_item_coverage", object_code=object_code,
            rule_type="coverage", target_dataset_or_relation=relation.relation_code,
            severity="warning", parameters={"reference_dataset": "mz_fee_item"},
        ),
        DataQualityRule(
            rule_code="mz_trade_anchor_not_null", object_code=object_code,
            rule_type="not_null", target_dataset_or_relation="mz_trade",
            severity="blocking", parameters={"field_code": "mz_trade.T_TradeNo"},
        ),
    ]:
        store.save_quality_rule(rule)
