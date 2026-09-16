"""
政策知识管理 API — Milvus policy_rules 查询与管理

端点:
  GET  /policy-knowledge/rules           — 分页查询
  GET  /policy-knowledge/rules/{id}      — 单条详情
  PUT  /policy-knowledge/rules/{id}      — 更新规则
  DELETE /policy-knowledge/rules/{id}    — 删除规则
  POST /policy-knowledge/rules/query     — 表达式查询
  GET  /policy-knowledge/stats           — 集合统计
  GET  /policy-knowledge/knowledge-map   — 知识体系全景（集合盘点 + 规则维度投影）
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query

from src.shared.schemas.responses import error_detail

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/medical-insurance-ai-agent/policy-knowledge", tags=["policy-knowledge"])


def _get_collection():
    """延迟导入 pymilvus，仅在请求时连接。"""
    try:
        from pymilvus import Collection, connections
        from src.config.production import MILVUS_HOST, MILVUS_PORT
        from src.knowledge_extension.rule_explanation.release_resolver import (
            resolve_rules_collection,
        )
    except ImportError:
        raise HTTPException(status_code=503, detail=error_detail("MILVUS_UNAVAILABLE", "pymilvus 未安装", {}))
    try:
        connections.connect(host=MILVUS_HOST, port=str(MILVUS_PORT), timeout=5)
        # Issue #33 P0-1：经统一 resolver 跟随 active release
        return Collection(resolve_rules_collection(MILVUS_HOST, str(MILVUS_PORT)))
    except Exception as e:
        raise HTTPException(status_code=503, detail=error_detail("MILVUS_UNAVAILABLE", f"Milvus 连接失败: {e}", {}))


def _row_to_dict(row: dict) -> dict:
    """将 Milvus 查询结果转为纯字符串 dict。

    policy_rules_v2 的 detail 字段（payment_ratio 等）是 FieldTrace dict，
    先解包为裸 value，再统一转字符串。
    """
    from src.runtime.policy_qa.policy_rules_search import unpack_detail
    unpack_detail(row)
    return {k: str(v) if v is not None else "" for k, v in row.items()}


@router.get("/rules")
def list_rules(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str = Query(""),
    rule_type: str = Query(""),
    insu_type: str = Query(""),
    med_type: str = Query(""),
    hosp_lv: str = Query(""),
    psn_type: str = Query(""),
    setl_type: str = Query(""),
    admission_order: str = Query(""),
    amount_band: str = Query(""),
    priority: str = Query(""),
):
    """分页查询政策规则，支持关键词和维度过滤。"""
    col = _get_collection()
    col.load()

    expr_parts = []
    if keyword.strip():
        kw = keyword.strip().replace("'", "\\'")
        expr_parts.append(f'source_text like "%{kw}%"')
    filter_map = {
        "rule_type": rule_type, "insu_type": insu_type, "med_type": med_type,
        "hosp_lv": hosp_lv, "psn_type": psn_type, "setl_type": setl_type,
        "admission_order": admission_order, "amount_band": amount_band, "priority": priority,
    }
    for field, val in filter_map.items():
        if val.strip():
            expr_parts.append(f'{field} == "{val.strip()}"')

    expr = " and ".join(expr_parts) if expr_parts else None
    offset = (page - 1) * page_size

    try:
        results = col.query(expr=expr, output_fields=["*"], limit=page_size, offset=offset) if expr else col.query(expr="", output_fields=["*"], limit=page_size, offset=offset, consistency_level="Eventually")
    except Exception as e:
        raise HTTPException(status_code=500, detail=error_detail("QUERY_ERROR", str(e), {}))

    items = [_row_to_dict(r) for r in results]

    # 获取总数
    try:
        total_results = col.query(expr=expr, output_fields=["rule_id"], limit=10000) if expr else col.query(expr="", output_fields=["rule_id"], limit=10000, consistency_level="Eventually")
        total = len(total_results)
    except Exception:
        total = len(items)

    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/rules/{rule_id}")
def get_rule(rule_id: str):
    """获取单条规则详情。"""
    col = _get_collection()
    col.load()
    try:
        results = col.query(expr=f'rule_id == "{rule_id}"', output_fields=["*"], limit=1)
    except Exception as e:
        raise HTTPException(status_code=500, detail=error_detail("QUERY_ERROR", str(e), {}))
    if not results:
        raise HTTPException(status_code=404, detail=error_detail("RULE_NOT_FOUND", "规则不存在", {"rule_id": rule_id}))
    return _row_to_dict(results[0])


@router.put("/rules/{rule_id}")
def update_rule(rule_id: str, body: dict):
    """更新规则字段。"""
    col = _get_collection()
    col.load()
    try:
        existing = col.query(expr=f'rule_id == "{rule_id}"', output_fields=["rule_id"], limit=1)
    except Exception as e:
        raise HTTPException(status_code=500, detail=error_detail("QUERY_ERROR", str(e), {}))
    if not existing:
        raise HTTPException(status_code=404, detail=error_detail("RULE_NOT_FOUND", "规则不存在", {"rule_id": rule_id}))

    # Milvus 不支持直接 upsert 标量字段，这里使用 delete + insert 方式
    # 先获取全部字段，再合并更新
    full = _row_to_dict(existing[0])
    full.update(body)
    full["rule_id"] = rule_id
    try:
        col.delete(f'rule_id == "{rule_id}"')
        col.insert([full])
        col.flush()
    except Exception as e:
        raise HTTPException(status_code=500, detail=error_detail("UPDATE_ERROR", str(e), {"rule_id": rule_id}))
    return {"updated": True, "rule_id": rule_id}


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: str):
    """删除规则。"""
    col = _get_collection()
    col.load()
    try:
        col.delete(f'rule_id == "{rule_id}"')
        col.flush()
    except Exception as e:
        raise HTTPException(status_code=500, detail=error_detail("DELETE_ERROR", str(e), {"rule_id": rule_id}))
    return {"deleted": True, "rule_id": rule_id}


@router.post("/rules/query")
def query_rules(body: dict):
    """高级表达式查询。"""
    col = _get_collection()
    col.load()
    expr = body.get("expr", "")
    limit = body.get("limit", 20)
    offset = body.get("offset", 0)
    try:
        results = col.query(expr=expr, output_fields=["*"], limit=limit, offset=offset) if expr else []
    except Exception as e:
        raise HTTPException(status_code=400, detail=error_detail("QUERY_ERROR", f"表达式错误: {e}", {}))
    items = [_row_to_dict(r) for r in results]
    return {"items": items, "total": len(items)}


@router.get("/stats")
def get_stats():
    """获取 policy_rules 集合统计信息。"""
    try:
        col = _get_collection()
        col.load()
        num = col.num_entities
    except Exception:
        num = 0

    distributions: dict[str, dict[str, int]] = {}
    if num > 0:
        for field in ["rule_type", "insu_type", "med_type", "hosp_lv", "psn_type", "setl_type", "admission_order", "amount_band", "priority"]:
            try:
                results = col.query(expr="", output_fields=[field], limit=10000, consistency_level="Eventually")
                dist: dict[str, int] = {}
                for r in results:
                    v = str(r.get(field, ""))
                    if v:
                        dist[v] = dist.get(v, 0) + 1
                distributions[field] = dict(sorted(dist.items(), key=lambda x: -x[1]))
            except Exception:
                distributions[field] = {}

    return {
        "collection": "policy_rules_v2",
        "available": num > 0,
        "total": num,
        "distributions": distributions,
    }


# ── 知识体系全景（迭代 22）─────────────────────────────────────────

# 规则投影字段：树形聚合用维度 + 叶子卡片用详情（FieldTrace 经 _row_to_dict 解包）
KNOWLEDGE_MAP_RULE_FIELDS = (
    "rule_id", "doc_id", "rule_type", "insu_type", "med_type", "hosp_lv",
    "psn_type", "setl_type", "region", "effective_date", "expiry_date",
    "publish_status", "policy_version", "amount_band", "amount_band_min",
    "amount_band_max", "admission_order", "priority", "payment_ratio",
    "personal_payment_ratio", "deductible_amount", "cap_amount",
    "rule_value", "source_text",
)


def _resolve_knowledge_map_sources() -> dict:
    """建立 MilvusClient 并解析当前读路径集合（测试用 monkeypatch 替换点）。"""
    from pymilvus import MilvusClient

    from src.config.production import MILVUS_HOST, MILVUS_PORT
    from src.knowledge_extension.rule_explanation.release_resolver import (
        get_active_release,
        resolve_facts_collection,
        resolve_rules_collection,
    )

    host, port = MILVUS_HOST, str(MILVUS_PORT)
    active = get_active_release()
    return {
        "client": MilvusClient(uri=f"http://{host}:{port}"),
        "rules_collection": resolve_rules_collection(host, port),
        "facts_collection": resolve_facts_collection(host, port),
        "release_id": str(getattr(active, "release_id", "") or ""),
    }


@router.get("/knowledge-map")
def get_knowledge_map():
    """知识体系全景：Milvus 政策集合盘点 + active 规则集合全量维度投影。

    供 /policy-knowledge/knowledge-map 页面消费：
    - collections: 所有 policy_rules_* / policy_facts_* 集合（名称/类型/行数/是否读路径目标）
    - rules: 当前读路径规则集合的维度投影，前端按维度路线聚合成树
    - facts_by_doc: 当前读路径 facts 集合按 doc_id 的条数分布（查询失败降级为空）
    """
    try:
        sources = _resolve_knowledge_map_sources()
    except ImportError:
        raise HTTPException(status_code=503, detail=error_detail("MILVUS_UNAVAILABLE", "pymilvus 未安装", {}))
    except Exception as e:
        raise HTTPException(status_code=503, detail=error_detail("MILVUS_UNAVAILABLE", f"Milvus 连接失败: {e}", {}))

    client = sources["client"]
    rules_name = sources["rules_collection"]
    facts_name = sources["facts_collection"]

    try:
        names = list(client.list_collections() or [])
    except Exception as e:
        raise HTTPException(status_code=503, detail=error_detail("MILVUS_UNAVAILABLE", f"Milvus 集合列举失败: {e}", {}))

    collections = []
    for name in sorted(names):
        if name.startswith("policy_rules"):
            kind = "rules"
        elif name.startswith("policy_facts"):
            kind = "facts"
        else:
            continue
        try:
            row_count = int(client.get_collection_stats(name).get("row_count", 0))
        except Exception:
            row_count = 0
        collections.append({
            "name": name,
            "kind": kind,
            "row_count": row_count,
            "active": name == (rules_name if kind == "rules" else facts_name),
        })

    try:
        rows = client.query(
            collection_name=rules_name, filter="",
            output_fields=list(KNOWLEDGE_MAP_RULE_FIELDS), limit=10000,
        ) or []
    except Exception as e:
        raise HTTPException(status_code=500, detail=error_detail("QUERY_ERROR", str(e), {}))
    rules = [_row_to_dict(r) for r in rows]

    # 向量化事实按文档分布：属于展示增强，失败降级为空不阻塞整页
    facts_by_doc: list[dict] = []
    try:
        facts_rows = client.query(
            collection_name=facts_name, filter="", output_fields=["doc_id"], limit=10000,
        ) or []
        dist: dict[str, int] = {}
        for r in facts_rows:
            doc = str(r.get("doc_id", "") or "")
            dist[doc] = dist.get(doc, 0) + 1
        facts_by_doc = sorted(
            ({"doc_id": k, "count": v} for k, v in dist.items()),
            key=lambda x: -x["count"],
        )
    except Exception as e:
        logger.warning("knowledge-map facts distribution unavailable: %s", e)

    return {
        "active_release_id": sources["release_id"],
        "rules_collection": rules_name,
        "facts_collection": facts_name,
        "collections": collections,
        "rules": rules,
        "facts_by_doc": facts_by_doc,
    }
