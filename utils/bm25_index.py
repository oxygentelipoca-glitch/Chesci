"""BM25 sparse retrieval index for hybrid search.

Maintains an in-memory BM25 index over all document chunks in the Chroma
collection.  Chinese text is handled via character bigrams; Latin text uses
whole-word tokenization.
"""

from __future__ import annotations

import re
from typing import Any

from rank_bm25 import BM25Okapi


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------

_CJK_RANGE = re.compile(r"[\u4e00-\u9fff]")
_ALNUM_RANGE = re.compile(r"[a-zA-Z0-9]+")


def _tokenize(text: str) -> list[str]:
    """Tokenize a mixed Chinese/English text into a bag of tokens.

    * CJK characters → overlapping bigrams (better recall than single chars).
    * Latin alphanumeric runs → kept as whole tokens (lowercased).
    * Everything else (punctuation, whitespace) is dropped.
    """
    tokens: list[str] = []

    # 1) Latin tokens – keep as whole words
    for match in _ALNUM_RANGE.finditer(text.lower()):
        tokens.append(match.group())

    # 2) Chinese bigrams – build a CJK-only character string first
    cjk_chars = "".join(_CJK_RANGE.findall(text))
    # Two-char sliding window
    for i in range(len(cjk_chars) - 1):
        tokens.append(cjk_chars[i : i + 2])
    # Also keep single chars for coverage of short strings
    tokens.extend(cjk_chars)

    return tokens


# ---------------------------------------------------------------------------
# Index wrapper
# ---------------------------------------------------------------------------

class BM25Index:
    """Thin wrapper around ``rank_bm25.BM25Okapi`` with document storage."""

    def __init__(self) -> None:
        self._index: BM25Okapi | None = None
        self._docs: list[str] = []
        self._metas: list[dict[str, Any]] = []

    # -- build / rebuild ---------------------------------------------------

    def build(self, documents: list[str], metadatas: list[dict[str, Any]]) -> None:
        """Build (or rebuild) the index from scratch."""
        self._docs = list(documents)
        self._metas = list(metadatas)
        tokenized = [_tokenize(d) for d in self._docs]
        if tokenized:
            self._index = BM25Okapi(tokenized)
        else:
            self._index = None

    def build_from_chroma(self, collection) -> None:
        """Convenience: pull all docs from a Chroma collection and build."""
        result = collection.get(include=["documents", "metadatas"])
        ids = result.get("ids", [])
        if not ids:
            self.build([], [])
            return
        self.build(
            documents=result.get("documents") or [],
            metadatas=result.get("metadatas") or [],
        )

    # -- search ------------------------------------------------------------

    def search(
        self, query: str, top_k: int = 20
    ) -> list[tuple[str, dict[str, Any], float]]:
        """Return top-k (doc_text, metadata, bm25_score)."""
        if self._index is None or not self._docs:
            return []

        qtokens = _tokenize(query)
        scores = self._index.get_scores(qtokens)

        # Keep only candidates with a positive score
        indexed = [
            (i, s)
            for i, s in enumerate(scores)
            if s > 0
        ]
        indexed.sort(key=lambda x: x[1], reverse=True)
        top = indexed[:top_k]

        return [
            (self._docs[i], dict(self._metas[i]), float(scores[i]))
            for i, _ in top
        ]

    # -- helpers -----------------------------------------------------------

    @property
    def is_empty(self) -> bool:
        return self._index is None or len(self._docs) == 0

    @property
    def doc_count(self) -> int:
        return len(self._docs)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_bm25_index = BM25Index()


def get_bm25_index() -> BM25Index:
    return _bm25_index


def refresh_bm25_index(collection) -> None:
    """Rebuild the global BM25 index from a Chroma collection."""
    _bm25_index.build_from_chroma(collection)
