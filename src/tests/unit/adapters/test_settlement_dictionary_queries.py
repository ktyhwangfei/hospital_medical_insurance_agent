from src.adapters.data_supply import settlement_dictionary_queries as queries
from src.adapters.base.models import AdapterCallStatus


def test_reads_view_domains_even_when_missing_from_classification_table(monkeypatch):
    def fetch(conn, sql, params):
        assert 'fund' in params and 'yllbss' in params
        assert 'yb_zdfl' not in sql
        return [{'flid':'fund','bm':'93','mc':'无业居民'}, {'flid':'yllbss','bm':'17','mc':'门诊挂号'}]
    monkeypatch.setattr(queries, '_fetch_all', fetch)
    result = queries.load_settlement_dictionaries(object())
    assert result.status == AdapterCallStatus.SUCCESS
    assert result.data['domains']['fund']['93'] == '无业居民'


def test_conflicts_removed_and_errors_do_not_expose_sql(monkeypatch):
    monkeypatch.setattr(queries,'_fetch_all',lambda *a:[{'flid':'fund','bm':'93','mc':'A'},{'flid':'fund','bm':'93','mc':'B'}])
    assert '93' not in queries.load_settlement_dictionaries(object()).data['domains']['fund']
    def fail(*a): raise RuntimeError('secret SQL')
    monkeypatch.setattr(queries,'_fetch_all',fail)
    result=queries.load_settlement_dictionaries(object())
    assert result.status == AdapterCallStatus.FAILED
    assert 'secret' not in result.message
