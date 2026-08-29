from __future__ import annotations

import hashlib
import math
import re

from langchain_core.embeddings import Embeddings


class HashEmbeddings(Embeddings):
    """Deterministic local embeddings for demo semantic memory.

    This keeps sqlite-vec usable without requiring a second external API.
    Replace it with provider embeddings before production use.
    """

    def __init__(self, dimensions: int) -> None:
        self.dimensions = dimensions

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)

    def _embed(self, text: str) -> list[float]:
        tokens = re.findall(r"[\w]+", text.lower(), flags=re.UNICODE) or [text.lower()]
        vector = [0.0] * self.dimensions

        for token in tokens:
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            bucket = int.from_bytes(digest[:4], byteorder="little") % self.dimensions
            sign = 1.0 if digest[4] & 1 else -1.0
            weight = 1.0 + digest[5] / 2550.0
            vector[bucket] += sign * weight

        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]

