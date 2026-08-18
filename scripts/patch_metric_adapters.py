"""一次性脚本：为所有有 source_field 但缺 source_adapter_port 的指标补全 adapter。

目的：让 selector 返回的 runtime_resolvable 指标数从 11 提升到覆盖全部有字段映射的指标。
设计依据：这些指标都属于医保结算相关对象，统一走 InsuranceInterfacePort 适配器（与已可解析指标一致）。

⚠️ 连接运行中后端的 PostgreSQL（不使用内存存储），变更直接生效。
用法：在项目根目录运行
    .venv/Scripts/python.exe scripts/patch_metric_adapters.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.semantic_layer.registry import get_semantic_registry  # noqa: E402

ADAPTER = "InsuranceInterfacePort"


def main() -> None:
    reg = get_semantic_registry()
    store = reg._store  # noqa: SLF001
    patched = 0
    skipped = 0
    for obj in reg.list_objects():
        for m in reg.list_metrics(obj.object_code):
            # 有 source_field 但缺 adapter → 补全
            if m.source_field and not m.source_adapter_port:
                m.source_adapter_port = ADAPTER
                store.save_metric(m)
                patched += 1
                print(f"  ✓ {m.metric_code}  ← {ADAPTER}")
            else:
                skipped += 1
    print(f"补全 adapter 完成：patched={patched}, skipped={skipped}")


if __name__ == "__main__":
    main()
