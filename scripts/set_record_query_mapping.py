"""各院区记录查询映射登记脚本（#69 产品化多院扩展点）。

用法：
  # 查看某数据源当前生效映射（含默认合并结果）
  uv run python scripts/set_record_query_mapping.py <datasource_id> --show

  # 登记覆盖映射（JSON 文件；只需提供与默认不同的表名/列名/方言）
  uv run python scripts/set_record_query_mapping.py <datasource_id> --file mapping.json

  # 清除覆盖（回退默认映射）
  uv run python scripts/set_record_query_mapping.py <datasource_id> --reset

mapping.json 示例（只写差异项）：
  {
    "dialect": "mssql",
    "inpatient_fee_table": "his.dbo.ZY_FEE_DETAIL",
    "columns": {"fee_item_code": "ITEM_DM", "fee_nation_code": "GB_CODE"}
  }
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.adapters.data_supply.record_query_mappings import (  # noqa: E402
    DEFAULT_RECORD_QUERY_MAPPING,
    RecordQueryMapping,
)
from src.data_platform.storage.postgresql.policy_meta_store import PolicyMetaStore  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="登记各院区记录查询映射")
    parser.add_argument("datasource_id", help="数据源 ID（policy_datasource.id）")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--show", action="store_true", help="查看当前生效映射")
    group.add_argument("--file", type=str, help="覆盖映射 JSON 文件路径")
    group.add_argument("--reset", action="store_true", help="清除覆盖，回退默认映射")
    parser.add_argument("--updated-by", default="onboarding")
    args = parser.parse_args()

    store = PolicyMetaStore()
    if args.show:
        override = store.get_record_query_mapping(args.datasource_id)
        effective = RecordQueryMapping(**(override or {}))
        print(json.dumps(effective.model_dump(), ensure_ascii=False, indent=2, default=str))
        print(f"（{'覆盖' if override else '默认'}映射，生效列数 {len(effective.resolved_columns())}）")
        return 0
    if args.reset:
        store._client.execute(  # noqa: SLF001 — 脚本属组合根
            "DELETE FROM record_query_mappings WHERE datasource_id = %s",
            (args.datasource_id,),
        )
        print(f"已清除 {args.datasource_id} 的覆盖映射，回退默认（{DEFAULT_RECORD_QUERY_MAPPING.dialect}）")
        return 0
    payload = json.loads(Path(args.file).read_text(encoding="utf-8"))
    mapping = RecordQueryMapping(**payload)  # 构造即校验（表名非空/列名合法）
    store.set_record_query_mapping(
        args.datasource_id, mapping.model_dump(exclude={"columns"}) | {"columns": mapping.columns},
        updated_by=args.updated_by,
    )
    print(f"已登记 {args.datasource_id} 覆盖映射：表 {len([t for t in payload if t.endswith('_table')])} 项，列覆盖 {len(mapping.columns)} 项")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
