"""Pure-Python BM25 scorer with a smart tokenizer. Zero dependencies beyond stdlib.

The tokenizer handles camelCase, snake_case, and punctuation boundaries so that
code search queries like "authentication handler" find "AuthHandler", etc.
"""

from __future__ import annotations

import math
import re


def tokenize(text: str) -> list[str]:
    """Tokenize *text* for BM25 indexing/search.

    Applies, in order:
    1. camelCase boundary splitting
    2. Lowercasing
    3. Punctuation/whitespace/snake_case split
    4. Empty token filtering
    5. Minimum token length of 2

    Args:
        text: Raw string content (source code, query, etc.).

    Returns:
        A list of normalized tokens.
    """
    return _tokenize_impl(text)


def _tokenize_impl(text: str) -> list[str]:
    """Internal tokenizer implementation."""
    if not text:
        return []

    # Step 1: Insert boundaries for camelCase.
    result = []
    i = 0
    chars = list(text)
    while i < len(chars):
        ch = chars[i]
        if ch.isupper() and i > 0:
            prev = chars[i - 1]
            if prev.islower():
                result.append("\x00")
            elif prev.isupper() and i + 1 < len(chars) and chars[i + 1].islower():
                result.append("\x00")
        result.append(ch)
        i += 1

    text = "".join(result)

    # Step 2: Lowercase
    text = text.lower()

    # Step 3: Split on punctuation/whitespace/underscore
    tokens = re.split(r"[^a-zA-Z0-9]+", text)

    # Step 4: Filter
    return [t for t in tokens if len(t) >= 2]


class BM25Scorer:
    """BM25 scoring engine with an in-memory inverted index.

    Supports incremental add/remove of documents and fast top-k search.
    Supports ``to_dict()`` / ``from_dict()`` for disk serialization.
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self._k1 = k1
        self._b = b
        self._index: dict[str, dict[str, int]] = {}
        self._doc_lengths: dict[str, int] = {}
        self._N: int = 0
        self._avgdl: float = 0.0

    def to_dict(self) -> dict:
        return {
            "k1": self._k1,
            "b": self._b,
            "index": self._index,
            "doc_lengths": self._doc_lengths,
            "N": self._N,
            "avgdl": self._avgdl,
        }

    @classmethod
    def from_dict(cls, data: dict) -> BM25Scorer:
        scorer = cls(k1=data["k1"], b=data["b"])
        scorer._index = data["index"]
        scorer._doc_lengths = data["doc_lengths"]
        scorer._N = data["N"]
        scorer._avgdl = data["avgdl"]
        return scorer

    def add_document(self, doc_id: str, tokens: list[str]) -> None:
        if doc_id in self._doc_lengths:
            self.remove_document(doc_id)

        for token in tokens:
            self._index.setdefault(token, {}).setdefault(doc_id, 0)
            self._index[token][doc_id] += 1

        self._doc_lengths[doc_id] = len(tokens)
        self._N += 1
        self._avgdl = sum(self._doc_lengths.values()) / self._N if self._N > 0 else 0.0

    def remove_document(self, doc_id: str) -> None:
        if doc_id not in self._doc_lengths:
            return

        for term, docs in self._index.items():
            if doc_id in docs:
                del docs[doc_id]

        empty_terms = [t for t, d in self._index.items() if not d]
        for t in empty_terms:
            del self._index[t]

        del self._doc_lengths[doc_id]
        self._N -= 1
        self._avgdl = sum(self._doc_lengths.values()) / self._N if self._N > 0 else 0.0

    def _idf(self, term: str) -> float:
        df = len(self._index.get(term, {}))
        if df == 0 or self._N == 0:
            return 0.0
        return math.log((self._N - df + 0.5) / (df + 0.5) + 1.0)

    def score(self, query_tokens: list[str], doc_id: str) -> float:
        dl = self._doc_lengths.get(doc_id, 0)
        if dl == 0 or self._avgdl == 0:
            return 0.0

        total = 0.0
        for term in set(query_tokens):
            tf = self._index.get(term, {}).get(doc_id, 0)
            if tf == 0:
                continue
            idf = self._idf(term)
            numerator = tf * (self._k1 + 1)
            denominator = tf + self._k1 * (1 - self._b + self._b * (dl / self._avgdl))
            total += idf * numerator / denominator
        return total

    def search(self, query_tokens: list[str], top_k: int = 5) -> list[tuple[str, float]]:
        candidates: set[str] = set()
        for term in query_tokens:
            docs = self._index.get(term, {})
            candidates.update(docs.keys())

        scored: list[tuple[str, float]] = []
        for doc_id in candidates:
            s = self.score(query_tokens, doc_id)
            if s > 0:
                scored.append((doc_id, s))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    @property
    def doc_count(self) -> int:
        return self._N

    @property
    def term_count(self) -> int:
        return len(self._index)
