"""只读核对当前 PostgreSQL 是否满足本 Skill 的政策与语义基线。"""
from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

import yaml

from src.config.production import DATABASE_URL
from src.data_platform.storage.postgresql.client import PostgreSQLClient


ROOT = Path(__file__).parents[1]


def main() -> int:
    baseline = yaml.safe_load(
        (ROOT / "references/policy_knowledge_baseline.yaml").read_text(encoding="utf-8")
    )
    client = PostgreSQLClient(DATABASE_URL)
    errors: list[str] = []
    try:
        expected_docs = {item["source_url"]: item for item in baseline["documents"]}
        with redirect_stdout(StringIO()):
            rows = client.execute(
                "SELECT doc_id, source_url, content_hash FROM policy_documents "
                "WHERE source_url = ANY(%s)",
                (list(expected_docs),),
            )
        actual_docs = {item["source_url"]: item for item in rows}
        for source_url, expected in expected_docs.items():
            actual = actual_docs.get(source_url)
            if actual is None:
                errors.append(f"缺少政策文档 {source_url}")
            elif actual["content_hash"] != expected["content_hash"]:
                errors.append(f"政策文档哈希不匹配 {source_url}")

        semantic = baseline["semantic_release"]
        version_rows = client.execute(
            "SELECT version, metrics FROM semantic_object_versions "
            "WHERE object_code=%s ORDER BY version::int DESC LIMIT 1",
            (semantic["object_code"],),
        )
        if not version_rows:
            errors.append(f"缺少语义发布 {semantic['object_code']}")
        else:
            manifest = yaml.safe_load(
                (ROOT / "skill_manifest.yaml").read_text(encoding="utf-8")
            )
            expected_metrics = {
                f"mzjyxx.{code}" for code in manifest["needed_objects"][0]["metrics"]
            }
            actual_metrics = {
                item["metric_code"] for item in version_rows[0]["metrics"]
            }
            if int(version_rows[0]["version"]) < int(semantic["version"]):
                errors.append("语义发布版本低于基线")
            if len(actual_metrics) < semantic["published_metric_count"]:
                errors.append("语义发布指标数量低于基线")
            if expected_metrics - actual_metrics:
                errors.append("语义发布未覆盖 Skill 声明的全部指标")

        assets = semantic["published_assets"]
        expected_metric_assets = {
            item["metric_code"] for item in assets if item["type"] == "metric"
        }
        metric_rows = client.execute(
            "SELECT metric_code FROM semantic_metrics "
            "WHERE status='published' AND metric_code = ANY(%s)",
            (list(expected_metric_assets),),
        )
        if expected_metric_assets - {item["metric_code"] for item in metric_rows}:
            errors.append("缺少基线要求的已发布语义指标")
        expected_values: dict[str, set[str]] = {}
        for item in assets:
            if item["type"] == "value":
                expected_values.setdefault(item["domain_code"], set()).add(item["value"])
        domain_rows = client.execute(
            "SELECT domain_code, standard_values FROM semantic_value_domains "
            "WHERE domain_code = ANY(%s)",
            (list(expected_values),),
        )
        actual_values = {
            item["domain_code"]: set(item["standard_values"])
            for item in domain_rows
        }
        if any(values - actual_values.get(code, set()) for code, values in expected_values.items()):
            errors.append("缺少基线要求的语义标准值")

        active = client.execute(
            "SELECT a.release_id, r.status FROM policy_active_release a "
            "JOIN policy_knowledge_releases r ON r.release_id=a.release_id "
            "WHERE a.singleton_id=TRUE"
        )
        if not active or active[0]["status"] != "active":
            errors.append("当前没有已激活知识发布")
        else:
            quality = client.execute(
                "SELECT status FROM policy_quality_runs WHERE release_id=%s "
                "ORDER BY run_sequence DESC LIMIT 1",
                (active[0]["release_id"],),
            )
            if not quality or quality[0]["status"] != "passed":
                errors.append("当前激活知识发布缺少通过的最新质量运行")
    finally:
        client.close()

    if errors:
        print("\n".join(f"- {item}" for item in errors))
        return 1
    print("政策文档、语义版本、活跃发布和质量运行均匹配基线。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
