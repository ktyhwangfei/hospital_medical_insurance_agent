"""P5.4 schema-update task 管理 API 测试（设计文档 §7.3/§7.4）。

用内存假 store 替换 PolicyMetaStore，隔离 PG。
publish 第一版只创建 task（status=pending）；真实执行触发（evolve：查受影响 doc +
LLM 提取）推迟到配置 MODEL_API_KEY + 实现 doc 查询后。
"""
import pytest

BASE = "/api/v1/medical-insurance-ai-agent/policy-pipeline/schema-update"


class _FakeMetaStore:
    """PolicyMetaStore 内存替身（仅 task CRUD）。"""

    def __init__(self):
        self.tasks: dict[str, dict] = {}
        self._seq = 0

    def create_task(self, metric_code, change_type, strategy, golden_score=None, schema_version=1):
        self._seq += 1
        task_id = f"task_{self._seq}"
        task = {
            "task_id": task_id, "metric_code": metric_code, "change_type": change_type,
            "strategy": strategy, "status": "pending", "progress": 0, "total": 0,
            "processed": 0, "golden_score": {}, "schema_version": schema_version,
            "error": None, "created_at": "2026-07-24T00:00:00Z", "finished_at": "",
        }
        self.tasks[task_id] = task
        return task

    def get_task(self, task_id):
        return self.tasks.get(task_id)

    def list_tasks(self, status="", metric_code="", limit=50):
        rows = list(self.tasks.values())
        if status:
            rows = [r for r in rows if r["status"] == status]
        if metric_code:
            rows = [r for r in rows if r["metric_code"] == metric_code]
        return rows


@pytest.fixture
def client(monkeypatch):
    import src.runtime.api.policy_pipeline_routes as m
    fake = _FakeMetaStore()
    monkeypatch.setattr(m, "_get_meta_store", lambda: fake)
    from fastapi.testclient import TestClient
    from src.runtime.api.app import create_app
    c = TestClient(create_app())
    yield c, fake


def test_publish_creates_pending_task(client):
    c, fake = client
    r = c.post(f"{BASE}/publish", json={
        "metric_code": "zcgz.payment_ratio", "strategy": "incremental",
    })
    assert r.status_code == 200
    data = r.json()
    assert data["task_id"]
    assert data["status"] == "pending"
    assert len(fake.tasks) == 1
    assert fake.tasks[data["task_id"]]["strategy"] == "incremental"


def test_get_task(client):
    c, _ = client
    created = c.post(f"{BASE}/publish", json={
        "metric_code": "zcgz.x", "strategy": "soft_delete",
    }).json()
    r = c.get(f"{BASE}/tasks/{created['task_id']}")
    assert r.status_code == 200
    assert r.json()["metric_code"] == "zcgz.x"
    assert r.json()["strategy"] == "soft_delete"


def test_get_task_404(client):
    c, _ = client
    assert c.get(f"{BASE}/tasks/no_such").status_code == 404


def test_list_tasks_filter_by_metric(client):
    c, _ = client
    c.post(f"{BASE}/publish", json={"metric_code": "zcgz.a", "strategy": "incremental"})
    c.post(f"{BASE}/publish", json={"metric_code": "zcgz.b", "strategy": "full"})
    r = c.get(f"{BASE}/tasks?metric_code=zcgz.a")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["metric_code"] == "zcgz.a"


def test_publish_validates_strategy(client):
    c, _ = client
    # 缺 strategy 应 422
    r = c.post(f"{BASE}/publish", json={"metric_code": "zcgz.x"})
    assert r.status_code == 422
