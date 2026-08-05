"""PostgreSQLClient 环境变量回退测试。

背景：PolicyMetaStore() 无参构造时，PostgreSQLClient 只认 os.environ["DATABASE_URL"]，
而 .env 仅提供 POSTGRES_* 分项变量（未合成 DATABASE_URL），导致 datasource /
schema-update 等端点 500。修复后 client 应在 DATABASE_URL 缺失时从 POSTGRES_* 合成。
"""
from src.data_platform.storage.postgresql.client import PostgreSQLClient


def test_shared_client_blocks_execute_until_transaction_finishes():
    """共享客户端不得让其他线程的 SQL 穿插进当前事务。"""
    from threading import Event, Thread

    transaction_started = Event()
    allow_transaction_to_finish = Event()
    concurrent_execute_started = Event()

    class _Cursor:
        description = None

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, sql, _params=()):
            if sql == "SELECT concurrent":
                concurrent_execute_started.set()

    class _Connection:
        closed = False

        def execute(self, sql):
            if sql == "BEGIN":
                transaction_started.set()

        def cursor(self):
            return _Cursor()

    client = PostgreSQLClient(database_url="postgresql://unused")
    client._conn = _Connection()

    def hold_transaction():
        with client.transaction():
            allow_transaction_to_finish.wait(timeout=1)

    transaction_thread = Thread(target=hold_transaction)
    transaction_thread.start()
    assert transaction_started.wait(timeout=1)

    execute_thread = Thread(target=lambda: client.execute("SELECT concurrent"))
    execute_thread.start()

    assert not concurrent_execute_started.wait(timeout=0.1)
    allow_transaction_to_finish.set()
    transaction_thread.join(timeout=1)
    execute_thread.join(timeout=1)
    assert concurrent_execute_started.is_set()


def test_fallback_to_postgres_env(monkeypatch):
    """DATABASE_URL 缺失 + POSTGRES_* 存在 → 合成连接串。"""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("POSTGRES_HOST", "db.example.com")
    monkeypatch.setenv("POSTGRES_PORT", "6543")
    monkeypatch.setenv("POSTGRES_USER", "u")
    monkeypatch.setenv("POSTGRES_PASSWORD", "p")
    monkeypatch.setenv("POSTGRES_DB", "mydb")
    c = PostgreSQLClient()
    assert c._database_url == "postgresql://u:p@db.example.com:6543/mydb"
    assert c._conn is None  # 懒连接，构造时不真正连


def test_database_url_takes_priority(monkeypatch):
    """DATABASE_URL 存在时优先于 POSTGRES_*（不覆盖显式配置）。"""
    monkeypatch.setenv("DATABASE_URL", "postgresql://a:b@h:1/d")
    monkeypatch.setenv("POSTGRES_HOST", "other")
    c = PostgreSQLClient()
    assert c._database_url == "postgresql://a:b@h:1/d"


def test_explicit_arg_takes_priority(monkeypatch):
    """显式传参优先于一切环境变量。"""
    monkeypatch.setenv("DATABASE_URL", "postgresql://env:env@h:1/d")
    c = PostgreSQLClient(database_url="postgresql://arg:arg@x:2/e")
    assert c._database_url == "postgresql://arg:arg@x:2/e"


def test_no_env_returns_none(monkeypatch):
    """无任何 PG 环境变量 → _database_url 为 None（调用方决定如何报错）。"""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("POSTGRES_HOST", raising=False)
    c = PostgreSQLClient()
    assert c._database_url is None
