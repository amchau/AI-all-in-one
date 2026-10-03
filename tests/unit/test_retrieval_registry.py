from datetime import date

from rag.retrieval.registry import PostgresSourceRegistry


class FakeConnection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    def __enter__(self) -> "FakeConnection":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, query: str, params: tuple[str, ...]) -> "FakeResult":
        self.calls.append((query, params))
        return FakeResult()


class FakeResult:
    def fetchall(self) -> list[tuple[object, ...]]:
        return [
            (
                "POL-HOME-002-v2",
                "Home Policy",
                "policy",
                "home",
                "HOME-002",
                date(2025, 1, 1),
                "2.0",
                "internal",
            )
        ]


def test_registry_reads_only_source_metadata_scoped_to_requested_policy(monkeypatch) -> None:
    connection = FakeConnection()
    monkeypatch.setattr(
        "rag.retrieval.registry.psycopg.connect",
        lambda *args, **kwargs: connection,
    )

    documents = PostgresSourceRegistry(
        "postgresql://rag_query:secret@db/platform"
    ).list_for_policy("HOME-002")

    assert len(documents) == 1
    assert documents[0].doc_id == "POL-HOME-002-v2"
    assert documents[0].title == "Home Policy"
    assert connection.calls[0][1] == ("HOME-002",)
    normalized_query = " ".join(connection.calls[0][0].lower().split())
    assert normalized_query.startswith("select id, title, doc_type, product, policy_id")
    assert "effective_date, version, acl" in normalized_query
    assert "where policy_id = %s or policy_id is null" in normalized_query
