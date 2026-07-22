from __future__ import annotations

from pymilvus import Collection, CollectionSchema, DataType, FieldSchema, connections, utility


POLICY_RULES_COLLECTION = "policy_rules"

POLICY_RULES_OUTPUT_FIELDS = [
    "rule_id",
    "fact_id",
    "policy_id",
    "clause_id",
    "source_text",
    "insu_type",
    "med_type",
    "hosp_lv",
    "psn_type",
    "setl_type",
    "payment_ratio",
    "deductible_amount",
    "cap_amount",
    "time_period",
    "admission_order",
    "amount_band",
    "priority",
    "rule_type",
    "rule_value",
    "embedding_text",
]


def connect_milvus(host: str = "127.0.0.1", port: str = "19121", alias: str = "default") -> None:
    """连接Milvus，注意端口为19121（非默认19530）"""
    connections.connect(alias=alias, host=host, port=port)


def create_policy_rules_collection(dim: int = 768, drop_existing: bool = False) -> Collection:
    """创建policy_rules集合，用于存储结构化医保政策规则（数据模型1）"""
    if utility.has_collection(POLICY_RULES_COLLECTION):
        if drop_existing:
            utility.drop_collection(POLICY_RULES_COLLECTION)
        else:
            return Collection(POLICY_RULES_COLLECTION)

    fields = [
        # 原始字段（与数据模型1.xlsx 政策规则表完全一致）
        FieldSchema("rule_id", DataType.VARCHAR, is_primary=True, max_length=64, description="规则ID"),
        FieldSchema("fact_id", DataType.VARCHAR, max_length=64, description="来源事实ID，关联policy_fact"),
        FieldSchema("policy_id", DataType.VARCHAR, max_length=64, description="政策文件ID，关联原始政策"),
        FieldSchema("clause_id", DataType.VARCHAR, max_length=64, description="条款ID，关联政策条款"),
        FieldSchema("source_text", DataType.VARCHAR, max_length=4096, description="原始政策文本，用于解释和溯源"),
        FieldSchema("insu_type", DataType.VARCHAR, max_length=32, description="险种类别：城镇职工、城乡居民、超转人员、生育保险"),
        FieldSchema("med_type", DataType.VARCHAR, max_length=32, description="医疗类别：住院-普通住院、门诊-一般门特"),
        FieldSchema("hosp_lv", DataType.VARCHAR, max_length=32, description="医疗机构等级：一级医院、二级医院、三级医院、社区"),
        FieldSchema("psn_type", DataType.VARCHAR, max_length=32, description="人群标签：退休、在职、70岁以上、学生儿童"),
        FieldSchema("setl_type", DataType.VARCHAR, max_length=32, description="结算方式：按项目付费、DRG、单病种、床日定额"),
        FieldSchema("payment_ratio", DataType.VARCHAR, max_length=32, description="支付比例：医保基金支付比例"),
        FieldSchema("deductible_amount", DataType.VARCHAR, max_length=32, description="起付金额：起付标准金额"),
        FieldSchema("cap_amount", DataType.VARCHAR, max_length=64, description="封顶金额：最高支付限额金额"),
        FieldSchema("time_period", DataType.VARCHAR, max_length=32, description="时间周期：医保年度等"),
        FieldSchema("admission_order", DataType.VARCHAR, max_length=32, description="住院次数：第几次住院"),
        FieldSchema("amount_band", DataType.VARCHAR, max_length=64, description="金额分段"),
        FieldSchema("priority", DataType.VARCHAR, max_length=32, description="规则优先级"),
        FieldSchema("rule_type", DataType.VARCHAR, max_length=64, description="规则类型（动态规则类型）"),
        FieldSchema("rule_value", DataType.VARCHAR, max_length=256, description="规则值（动态规则值）"),
        # 额外字段（向量化相关）
        FieldSchema("embedding_text", DataType.VARCHAR, max_length=16384, description="拼接后用于向量化的文本"),
        FieldSchema("embedding", DataType.FLOAT_VECTOR, dim=dim, description="向量嵌入（768维，BAAI/bge-base-zh-v1.5）"),
    ]
    schema = CollectionSchema(fields, description="医保政策规则(数据模型1)", enable_dynamic_field=True)
    col = Collection(POLICY_RULES_COLLECTION, schema)
    _create_vector_index(col)
    return col


def drop_policy_rules_collection() -> None:
    """删除policy_rules集合"""
    if utility.has_collection(POLICY_RULES_COLLECTION):
        utility.drop_collection(POLICY_RULES_COLLECTION)


def _create_vector_index(col: Collection) -> None:
    """创建HNSW向量索引（COSINE距离，768维嵌入）"""
    index_params = {
        "index_type": "HNSW",
        "metric_type": "COSINE",
        "params": {"M": 16, "efConstruction": 200},
    }
    col.create_index(field_name="embedding", index_params=index_params)
