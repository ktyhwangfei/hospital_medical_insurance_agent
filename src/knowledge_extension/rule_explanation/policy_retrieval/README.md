# 医保政策 Milvus 混合高级检索代码

## 1. 安装依赖

```bash
pip install pymilvus pandas openpyxl pydantic sentence-transformers
```

如果只是先打通 Milvus 入库和标量过滤，不想加载 embedding 模型，可使用 `--embedding-kind hash`。

## 2. 启动 Milvus

确保 Milvus 已在本机启动，默认地址：

```text
127.0.0.1:19530
```

## 3. 从 Excel 入库

```bash
python -m src.knowledge_extension.rule_explanation.policy_retrieval_code.policy_retrieval.milvus_ingest --nodes-excel ./raw/policy_nodes.xlsx --facts-excel ./raw/policy_facts.xlsx --host localhost --port 19530 --embedding-kind sentence_transformer --drop-existing
```

本地快速打通流程：

```bash
python -m policy_retrieval.milvus_ingest \
  --nodes-excel ./raw/policy_nodes.xlsx \
  --facts-excel ./raw/policy_facts.xlsx \
  --embedding-kind hash \
  --drop-existing
```

## 4. Demo 检索

```bash
python demo_search.py
```

目标验证：

- 查询“三级医院首次住院起付线是多少”，应召回三级首次住院 1300 元 fact。
- 查询“为什么起付线是1950”，应召回三级首次住院起付线和第二次及以后住院 50% 公式 fact。

## 5. 设计要点

- `policy_nodes`：语义节点检索，用于普通政策问答。
- `policy_facts`：结构化事实检索，用于金额、比例、公式、解释链。
- 入库时会将 `value_map` 自动展开为明细 fact，例如 `primary/secondary/tertiary` 展开为可过滤的 `hospital_level`。
- Milvus 检索不是纯向量检索，支持标量过滤：`fact_type / service_type / population / hospital_level / admission_order / amount / ratio / derived`。
