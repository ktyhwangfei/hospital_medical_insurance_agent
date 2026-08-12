from __future__ import annotations

from contextlib import contextmanager
from threading import Event, Thread
from types import SimpleNamespace

from src.data_platform.storage.postgresql.policy_meta_store import PolicyMetaStore
from src.data_platform.storage.postgresql.semantic_alignment_store import (
    PostgresSemanticAlignmentStore,
)


class _FakeClient:
    @contextmanager
    def transaction(self):
        yield


def test_registry_client_swap_is_serialized_across_coordinators() -> None:
    original_client = object()
    registry_store = SimpleNamespace(_client=original_client)
    policy_client = _FakeClient()
    alignment_client = _FakeClient()

    policy_store = PolicyMetaStore.__new__(PolicyMetaStore)
    policy_store._client = policy_client
    alignment_store = PostgresSemanticAlignmentStore.__new__(
        PostgresSemanticAlignmentStore
    )
    alignment_store._client = alignment_client

    policy_entered = Event()
    release_policy = Event()
    alignment_attempted = Event()
    alignment_entered = Event()
    observed_clients: list[object] = []

    def policy_transaction() -> None:
        with policy_store.registry_transaction(registry_store):
            observed_clients.append(registry_store._client)
            policy_entered.set()
            assert release_policy.wait(2)

    def alignment_transaction() -> None:
        assert policy_entered.wait(2)
        alignment_attempted.set()
        with alignment_store.registry_transaction(registry_store):
            observed_clients.append(registry_store._client)
            alignment_entered.set()

    first = Thread(target=policy_transaction)
    second = Thread(target=alignment_transaction)
    first.start()
    second.start()
    assert alignment_attempted.wait(2)
    alignment_was_blocked = not alignment_entered.wait(0.1)
    client_during_policy = registry_store._client

    release_policy.set()
    first.join(2)
    second.join(2)

    assert not first.is_alive()
    assert not second.is_alive()
    assert alignment_was_blocked
    assert client_during_policy is policy_client
    assert observed_clients == [policy_client, alignment_client]
    assert registry_store._client is original_client
