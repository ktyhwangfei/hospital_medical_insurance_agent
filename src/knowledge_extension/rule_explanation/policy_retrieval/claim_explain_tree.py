from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from pprint import pprint

from .contextual_policy_qa import ContextualPolicyQA
from .sqlserver_business_data_client import SqlServerBusinessDataClient
from .claim_explain_tree import ClaimExplainTreeBuilder


def main():
    BASE_DIR = Path(__file__).resolve().parent

    settlement_id = "1671213"
    fsrq = "2025-06-29 00:00:00.000"

    client = SqlServerBusinessDataClient(
        sql_config_path=BASE_DIR / "config" / "business_sql.yaml",
    )

    # 1. 构建费用解释树
    tree_builder = ClaimExplainTreeBuilder(
        business_client=client,
    )

    tree_result = tree_builder.build_tree(
        settlement_id=settlement_id,
        fsrq=fsrq,
    )

    print("\n" + "=" * 80)
    print("费用解释树:")
    pprint(asdict(tree_result), width=160)

    # 2. 基于业务上下文继续做政策问答
    qa = ContextualPolicyQA(
        business_client=client,
        embedding_kind="sentence_transformer",
    )

    result = qa.answer(
        "封顶线是多少？",
        settlement_id=settlement_id,
    )

    print("\n" + "=" * 80)
    print("重写问题:", result.rewritten_question)
    print("回答:")
    print(result.answer)


if __name__ == "__main__":
    main()