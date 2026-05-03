from typing import Protocol


class VectorSearchPort(Protocol):
    def search(self, query: str, top_k: int = 5) -> list[dict]:
        raise NotImplementedError