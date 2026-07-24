from __future__ import annotations

import hashlib
import os
from typing import Iterable


class EmbeddingProvider:
    def encode(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError

    @property
    def dim(self) -> int:
        raise NotImplementedError


class SentenceTransformerEmbeddingProvider(EmbeddingProvider):
    def __init__(self, model_path: str | None = None):
        from sentence_transformers import SentenceTransformer

        self.model_path = model_path or self._resolve_model_path()
        self.model = SentenceTransformer(self.model_path)
        self._dim = self.model.get_sentence_embedding_dimension()

    @staticmethod
    def _resolve_model_path() -> str:
        """解析模型路径：环境变量 EMBEDDING_MODEL_PATH > 项目本地 models/ > HuggingFace 在线。"""
        env = os.getenv("EMBEDDING_MODEL_PATH")
        if env:
            return env
        # 探测项目根下的本地模型（CWD-based，生产部署 CWD 通常为项目根）
        local = os.path.join(os.getcwd(), "models", "bge-base-zh-v1.5")
        if os.path.isdir(local):
            return local
        return "BAAI/bge-base-zh-v1.5"  # fallback：从 HuggingFace 拉取

    @property
    def dim(self) -> int:
        return int(self._dim)

    def encode(self, texts: list[str]) -> list[list[float]]:
        vectors = self.model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return [v.tolist() for v in vectors]


class HashEmbeddingProvider(EmbeddingProvider):
    """
    仅用于本地流程测试，不能用于生产语义检索。
    当还没有安装/下载 embedding 模型时，可先用它打通 Milvus 入库和过滤检索。
    """
    def __init__(self, dim: int = 384):
        self._dim = dim

    @property
    def dim(self) -> int:
        return self._dim

    def encode(self, texts: list[str]) -> list[list[float]]:
        return [self._hash_text(t) for t in texts]

    def _hash_text(self, text: str) -> list[float]:
        buf = bytearray()
        counter = 0
        while len(buf) < self._dim * 4:
            h = hashlib.sha256(f"{counter}:{text}".encode("utf-8")).digest()
            buf.extend(h)
            counter += 1
        vals = []
        for i in range(self._dim):
            n = int.from_bytes(buf[i * 4:(i + 1) * 4], "little", signed=False)
            vals.append((n % 2000000) / 1000000.0 - 1.0)
        norm = sum(x * x for x in vals) ** 0.5 or 1.0
        return [x / norm for x in vals]


def get_embedding_provider(kind: str = "sentence_transformer") -> EmbeddingProvider:
    if kind == "hash":
        return HashEmbeddingProvider()
    return SentenceTransformerEmbeddingProvider()
