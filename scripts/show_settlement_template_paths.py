"""打印结算单模板的字段映射（库.表.字段），供人工核对；可选连库校验列是否存在。

用法：
  python scripts/show_settlement_template_paths.py                # 只打印映射
  python scripts/show_settlement_template_paths.py --check        # 连 bjybdb 校验列是否存在
  python scripts/show_settlement_template_paths.py --template employee_outpatient
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.adapters.data_supply.record_query_mappings import DEFAULT_RECORD_QUERY_MAPPING  # noqa: E402
from src.adapters.data_supply.settlement_template_bindings import resolve_template_paths  # noqa: E402
from src.config.settlement_templates import _templates, get_settlement_template  # noqa: E402


def _columns_exist() -> dict[str, bool]:
    """连库核实 库.表.字段 是否存在（INFORMATION_SCHEMA.COLUMNS）。"""
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / '.env')
    from src.runtime.discovery.semantic_source import get_semantic_data_source

    cursor = get_semantic_data_source().connect_datasource('bjybdb').cursor()
    cursor.execute("SELECT TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS")
    known = {(schema.lower(), table.lower(), column.lower()) for schema, table, column in cursor.fetchall()}
    return {f'{schema}.{table}.{column}': True for schema, table, column in known}


def main() -> int:
    parser = argparse.ArgumentParser(description='打印结算单模板字段映射（库.表.字段）')
    parser.add_argument('--template', help='只看某个模板（如 employee_outpatient）')
    parser.add_argument('--check', action='store_true', help='连 bjybdb 校验列是否存在')
    args = parser.parse_args()

    known = _columns_exist() if args.check else {}
    mapping = DEFAULT_RECORD_QUERY_MAPPING
    missing: list[str] = []
    for template_id in _templates():
        if args.template and template_id != args.template:
            continue
        template = get_settlement_template(template_id)
        paths = resolve_template_paths(template, mapping)
        print(f'\n== {template.template_id} v{template.version} | {template.title} | 库={template.source_database}')
        print(f'{"字段键":<24}{"中文名":<18}{"读取方式":<14}库.表.字段')
        for field in template.fields:
            path = ' + '.join(paths[field.key]) or '（未映射）'
            if field.operation == 'context' and paths[field.key]:
                path = '（上下文·仅按人定位）' + path
            print(f'{field.key:<24}{field.label:<18}{field.operation:<14}{path}')
            if args.check:
                for item in paths[field.key]:
                    tail = item.split('.', 1)[1].lower()
                    if tail not in known:
                        missing.append(f'{template.template_id}.{field.key}: {item}')
    if args.check:
        print('\n列校验：' + ('全部存在' if not missing else f'{len(missing)} 处不存在'))
        for item in missing:
            print('  缺失', item)
    return 1 if missing else 0


if __name__ == '__main__':
    raise SystemExit(main())
