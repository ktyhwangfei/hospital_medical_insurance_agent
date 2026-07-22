from __future__ import annotations

from pprint import pprint

from pathlib  import Path

from .contextual_policy_qa import ContextualPolicyQA
from .sqlserver_business_data_client import SqlServerBusinessDataClient


def main():
    BASE_DIR = Path(__file__).resolve().parent
    
    client = SqlServerBusinessDataClient(
        sql_config_path=BASE_DIR/ "config" / "business_sql.yaml",
    )

    qa = ContextualPolicyQA(
        business_client=client,
        embedding_kind="sentence_transformer",
    )

    result = qa.answer(
        # "起付线为什么是1950？",
        "封顶线是多少？",
        settlement_id="1671213",
    )

    print("重写问题:", result.rewritten_question)
    print("回答:")
    print(result.answer)


if __name__ == "__main__":
    main()
