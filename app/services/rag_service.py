"""RAG service: hybrid retrieval + reranker + LLM answer generation.

Pipeline
--------
1. **Hybrid retrieval** – dense (BGE embeddings) + sparse (BM25), fused via
   Reciprocal Rank Fusion (RRF).
2. **Reranking** – Cross-Encoder model re-ranks the fused candidate set.
3. **Multi-turn** – accepts optional conversation history so the LLM can
   resolve pronouns and follow-up references.
"""

from __future__ import annotations

import os
import re
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI
from sentence_transformers import CrossEncoder
from utils.rag_resources import get_collection, get_embedding_model

from utils.bm25_index import get_bm25_index, refresh_bm25_index

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

load_dotenv()

RERANKER_MODEL = os.getenv("RERANKER_MODEL", "BAAI/bge-reranker-base")
MAX_DENSE_DISTANCE = float(os.getenv("RAG_MAX_DENSE_DISTANCE", "1.05"))
MIN_BM25_SCORE = float(os.getenv("RAG_MIN_BM25_SCORE", "8.0"))
DEFAULT_DENSE_WEIGHT = float(os.getenv("RAG_DENSE_WEIGHT", "1.0"))
DEFAULT_SPARSE_WEIGHT = float(os.getenv("RAG_SPARSE_WEIGHT", "1.0"))

_PRECISION_QUERY = re.compile(r"\d|多少钱|多少|几[点天月年]|日期|时间|编号|电话|价格|折扣|有效期|能不能|是否|有没有|哪一年")
_SEMANTIC_QUERY = re.compile(r"为什么|如何|怎么|区别|流程|作用|影响|介绍|解释|原理|建议")

# ---------------------------------------------------------------------------
# BM25 index (lazy init)
# ---------------------------------------------------------------------------

_bm25_ready = False


def _ensure_bm25() -> None:
    """Build the global BM25 index from Chroma on first use."""
    global _bm25_ready
    if not _bm25_ready:
        refresh_bm25_index(get_collection())
        _bm25_ready = True


def rebuild_bm25() -> None:
    """Force-rebuild the BM25 index (call after document changes)."""
    global _bm25_ready
    refresh_bm25_index(get_collection())
    _bm25_ready = True


# ---------------------------------------------------------------------------
# Reranker (lazy init)
# ---------------------------------------------------------------------------

_reranker: CrossEncoder | None | bool = None
_reranker_error: str | None = None


def _get_reranker() -> CrossEncoder | None:
    """Lazy-load the Cross-Encoder reranker.

    Returns None if the model cannot be loaded (e.g. network unavailable),
    in which case callers should fall back to fusion-only ranking.
    """
    global _reranker, _reranker_error
    if _reranker is None:
        try:
            # Do not block a user query attempting a network download.  Set
            # RERANKER_MODEL to a local model path or cache the default model.
            _reranker = CrossEncoder(RERANKER_MODEL, local_files_only=True)
            _reranker_error = None
        except Exception as exc:
            import logging
            _reranker_error = str(exc)
            logging.warning("Reranker model unavailable (%s), falling back to fusion-only", exc)
            _reranker = False  # sentinel
    return _reranker if _reranker is not False else None


def retrieval_status() -> dict[str, Any]:
    """Expose safe operational status for the UI and health checks."""
    reranker = _get_reranker()
    return {
        "reranker": {
            "model": RERANKER_MODEL,
            "available": reranker is not None,
            "mode": "cross-encoder" if reranker is not None else "fusion-only",
            "detail": _reranker_error if reranker is None else None,
        },
        "thresholds": {
            "max_dense_distance": MAX_DENSE_DISTANCE,
            "min_bm25_score": MIN_BM25_SCORE,
        },
        "weights": {
            "dense": DEFAULT_DENSE_WEIGHT,
            "sparse": DEFAULT_SPARSE_WEIGHT,
        },
    }


# ---------------------------------------------------------------------------
# Noise filter (ported from original)
# ---------------------------------------------------------------------------

def _is_noisy_chunk(text: str) -> bool:
    """Return True for chunks that are too short or have low information density."""
    if not text:
        return True
    cleaned = text.strip()
    if len(cleaned) < 20:
        return True
    content_chars = re.findall(r"[\u4e00-\u9fffA-Za-z0-9]", cleaned)
    if not content_chars:
        return True
    density = len(content_chars) / max(len(cleaned), 1)
    return density < 0.35


# ---------------------------------------------------------------------------
# Reciprocal Rank Fusion
# ---------------------------------------------------------------------------

def _rrf_fusion(
    dense: list[tuple[str, dict[str, Any], float]],
    sparse: list[tuple[str, dict[str, Any], float]],
    k: int = 60,
    dense_weight: float = DEFAULT_DENSE_WEIGHT,
    sparse_weight: float = DEFAULT_SPARSE_WEIGHT,
) -> list[tuple[str, dict[str, Any], float, list[str]]]:
    """Combine dense and sparse ranked lists with Reciprocal Rank Fusion.

    Parameters
    ----------
    dense : list of (doc, metadata, distance)
        Dense (vector) results, ordered by ascending distance.
    sparse : list of (doc, metadata, bm25_score)
        BM25 results, ordered by descending score.
    k : int
        RRF constant (default 60, standard).

    Returns
    -------
    list of (doc, metadata, rrf_score) sorted by score descending.
    """
    score_map: dict[str, float] = {}
    doc_map: dict[str, str] = {}
    meta_map: dict[str, dict[str, Any]] = {}
    channel_map: dict[str, list[str]] = {}

    # Dense list (rank 0 = best, i.e. smallest distance)
    for rank, (doc, meta, _dist) in enumerate(dense):
        key = " ".join(doc.split())
        score_map[key] = score_map.get(key, 0.0) + dense_weight / (k + rank + 1)
        doc_map[key] = doc
        meta_map[key] = meta
        channel_map.setdefault(key, []).append("dense")

    # Sparse list (rank 0 = best, i.e. highest BM25 score)
    for rank, (doc, meta, _score) in enumerate(sparse):
        key = " ".join(doc.split())
        score_map[key] = score_map.get(key, 0.0) + sparse_weight / (k + rank + 1)
        doc_map[key] = doc
        meta_map[key] = meta
        channel_map.setdefault(key, []).append("bm25")

    ranked = sorted(score_map.items(), key=lambda x: x[1], reverse=True)
    return [(doc_map[k], meta_map[k], score_map[k], channel_map[k]) for k, _ in ranked]


# ---------------------------------------------------------------------------
# Rerank step
# ---------------------------------------------------------------------------

def _rerank(
    question: str,
    candidates: list[tuple[str, dict[str, Any], float, list[str]]],
    top_k: int = 4,
) -> list[tuple[str, dict[str, Any], float]]:
    """Re-rank candidates with a Cross-Encoder and return the top-k.

    Falls back to the original (fusion) order when the reranker is unavailable.
    """
    if len(candidates) <= top_k:
        return candidates

    reranker = _get_reranker()
    if reranker is None:
        return candidates[:top_k]

    pairs = [[question, doc] for doc, _meta, _score, _channels in candidates]
    scores = reranker.predict(pairs)

    indexed = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
    return [candidates[i] for i, _ in indexed[:top_k]]


def _effective_weights(
    question: str,
    dense_weight: float,
    sparse_weight: float,
    adaptive: bool,
) -> tuple[str, float, float]:
    """Choose a retrieval bias while preserving caller-configured base weights."""
    if not adaptive:
        return "manual", dense_weight, sparse_weight
    if _PRECISION_QUERY.search(question):
        return "precision", dense_weight * 0.65, sparse_weight * 1.35
    if _SEMANTIC_QUERY.search(question):
        return "semantic", dense_weight * 1.35, sparse_weight * 0.65
    return "balanced", dense_weight, sparse_weight


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------

def _make_where(
    base_user_id: str,
    stored_filenames: list[str] | None,
) -> dict[str, Any]:
    """Build a Chroma ``where`` clause combining user_id and optional file filter."""
    if not stored_filenames:
        return {"user_id": base_user_id}
    return {
        "$and": [
            {"user_id": base_user_id},
            {"stored_filename": {"$in": stored_filenames}},
        ]
    }


def search_knowledge(
    question: str,
    user_id: int | None = None,
    top_k: int = 10,
    final_k: int = 6,
    stored_filenames: list[str] | None = None,
    dense_weight: float = DEFAULT_DENSE_WEIGHT,
    sparse_weight: float = DEFAULT_SPARSE_WEIGHT,
    adaptive: bool = True,
    include_debug: bool = False,
) -> dict[str, list]:
    """Hybrid search: dense + BM25 → RRF fusion → reranker → top-k.

    Parameters
    ----------
    stored_filenames : list[str] or None
        When provided, only chunks belonging to these stored filenames are
        considered.  This enables "search within specific file(s)" queries.

    Returns ``{"documents": [...], "metadatas": [...]}``.
    """
    _ensure_bm25()
    query_type, effective_dense_weight, effective_sparse_weight = _effective_weights(
        question, dense_weight, sparse_weight, adaptive
    )

    # ---- 1. Dense (vector) retrieval ------------------------------------
    vector = get_embedding_model().encode(question, normalize_embeddings=True).tolist()
    dense_candidates: list[tuple[str, dict[str, Any], float]] = []

    if user_id is not None:
        r = get_collection().query(
            query_embeddings=[vector],
            n_results=top_k,
            where=_make_where(str(user_id), stored_filenames),
            include=["documents", "metadatas", "distances"],
        )
        _collect_dense(r, dense_candidates)

    r = get_collection().query(
        query_embeddings=[vector],
        n_results=top_k,
        where=_make_where("system", stored_filenames),
        include=["documents", "metadatas", "distances"],
    )
    _collect_dense(r, dense_candidates)

    # Filter noisy chunks
    dense_candidates = [
        (d, m, dist) for d, m, dist in dense_candidates if not _is_noisy_chunk(d)
    ]

    # ---- 2. Sparse (BM25) retrieval -------------------------------------
    bm25 = get_bm25_index()
    sparse_candidates = bm25.search(question, top_k=max(top_k, 40))

    # Enforce the same user/file scope for sparse retrieval as for Chroma.
    allowed_user_ids = {"system"}
    if user_id is not None:
        allowed_user_ids.add(str(user_id))
    sparse_candidates = [
        (d, m, s)
        for d, m, s in sparse_candidates
        if m.get("user_id") in allowed_user_ids
        and (not stored_filenames or m.get("stored_filename") in stored_filenames)
    ]

    best_dense_distance = min((score for _doc, _meta, score in dense_candidates), default=None)
    best_bm25_score = max((score for _doc, _meta, score in sparse_candidates), default=0.0)

    # ---- 3. Fusion -------------------------------------------------------
    fused = _rrf_fusion(
        dense_candidates,
        sparse_candidates,
        dense_weight=effective_dense_weight,
        sparse_weight=effective_sparse_weight,
    )

    # ---- 4. Rerank -------------------------------------------------------
    reranked = _rerank(question, fused, top_k=final_k)

    has_sufficient_context = bool(reranked) and (
        (best_dense_distance is not None and best_dense_distance <= MAX_DENSE_DISTANCE)
        or best_bm25_score >= MIN_BM25_SCORE
    )
    documents = [item[0] for item in reranked] if has_sufficient_context else []
    metadatas = [item[1] for item in reranked] if has_sufficient_context else []
    scores = [round(float(item[2]), 6) for item in reranked] if has_sufficient_context else []
    debug = {
        "query_type": query_type,
        "adaptive": adaptive,
        "weights": {
            "dense": round(effective_dense_weight, 3),
            "bm25": round(effective_sparse_weight, 3),
        },
        "candidates": {
            "dense": len(dense_candidates),
            "bm25": len(sparse_candidates),
            "fused": len(fused),
        },
        "hits": [
            {
                "filename": metadata.get("filename", "未知文件"),
                "section": metadata.get("section_title", "文档摘要"),
                "channels": channels,
                "score": round(float(score), 6),
            }
            for _doc, metadata, score, channels in reranked
        ],
    } if include_debug else None

    return {
        "documents": documents,
        "metadatas": metadatas,
        "scores": scores,
        "has_sufficient_context": has_sufficient_context,
        "best_dense_distance": best_dense_distance,
        "best_bm25_score": best_bm25_score,
        "debug": debug,
    }


def _collect_dense(
    result: dict,
    out: list[tuple[str, dict[str, Any], float]],
) -> None:
    """Append (doc, metadata, distance) tuples from a Chroma query result."""
    docs0 = result.get("documents", [[]])[0]
    metas0 = result.get("metadatas", [[]])[0]
    dists0 = result.get("distances", [[]])[0]

    for i in range(len(docs0)):
        meta = metas0[i] if i < len(metas0) else {}
        dist = dists0[i] if i < len(dists0) else 1.0
        out.append((docs0[i], meta, float(dist)))


# ---------------------------------------------------------------------------
# Answer generation
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "你是企业知识库问答助手。"
    "你的目标是基于给定资料，准确、简洁地回答用户问题。"
    "只使用资料中的信息，不要编造、推测或扩展到资料之外。"
    # ---- 回答结构 ----
    "每条回答必须包含「结论 + 一句简短依据」。先说结论，再用「根据…」或一句话点明出处。"
    "例如问「浓缩咖啡加一份多少钱」，应回答「6 元，根据出品规则加一份浓缩咖啡的费用为 6 元」"
    "——而不是只回答「6 元」。"
    "如果用户问了多个小问，每个小问都按「结论 + 依据」分别回答。"
    # ---- 风格约束 ----
    "对名称、时间、数量、是否判断类问题，答案本身要短，但必须附上来源依据。"
    "单问控制在 1-3 句话内；如果是多问，每个小问 1-2 句。不要重复题干。"
    # ---- 边界处理 ----
    "如果用户问的是「怎么分类」，只有在资料中明确出现分类名称时才按类别回答；"
    "如果资料没有给出明确分类，就直接说明「资料中没有明确提到分类」。"
    "如果用户只是打招呼，简短回应并自然问候。"
    "如果资料不足以支持结论，明确说明「资料中没有明确提到」或「我不确定」，不要硬猜。"
    # ---- 禁止事项 ----
    "不要输出分析过程、不要编造来源、不要把答案写成泛泛总结。"
    "不要使用「可能、大概、应该」等模糊词，除非资料本身就用了这类表述。"
    "除非用户明确要求详细解释，否则不要分点作答。"
)


def ask_question(
    question: str,
    user_id: int | None = None,
    history: list[dict[str, str]] | None = None,
    stored_filenames: list[str] | None = None,
    dense_weight: float = DEFAULT_DENSE_WEIGHT,
    sparse_weight: float = DEFAULT_SPARSE_WEIGHT,
    adaptive: bool = True,
    include_debug: bool = False,
) -> dict[str, Any]:
    """Run the full RAG pipeline and return ``{"answer": ..., "sources": ...}``.

    Parameters
    ----------
    history : list[dict] or None
        Previous conversation turns as ``[{"role": "user", "content": ...},
        {"role": "assistant", "content": ...}, ...]``.
        Up to the last 6 messages (3 turns) are included in the LLM prompt so
        the model can resolve follow-up references.
    stored_filenames : list[str] or None
        When provided, limits retrieval to chunks from these files only.
    """
    result = search_knowledge(
        question,
        user_id=user_id,
        stored_filenames=stored_filenames,
        dense_weight=dense_weight,
        sparse_weight=sparse_weight,
        adaptive=adaptive,
        include_debug=include_debug,
    )
    docs = result["documents"]
    metadatas = result["metadatas"]

    if not result["has_sufficient_context"]:
        return {
            "answer": "资料中没有明确提到这个问题。",
            "sources": [],
            "citations": [],
            "retrieval": {
                "has_sufficient_context": False,
                "best_dense_distance": result["best_dense_distance"],
                "best_bm25_score": result["best_bm25_score"],
            },
            "debug": result["debug"],
        }

    context = "\n".join(docs)

    # Build messages array
    messages: list[dict[str, str]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
    ]

    # Include recent conversation history for multi-turn context
    if history:
        for msg in history[-6:]:
            role = msg.get("role", "user")
            if role in ("user", "assistant"):
                messages.append({"role": role, "content": msg.get("content", "")})

    messages.append(
        {
            "role": "user",
            "content": (
                f"资料：\n{context}\n\n"
                f"问题：\n{question}\n\n"
                "请用中文直接作答，答案尽量简短。"
            ),
        }
    )

    client = OpenAI(api_key=os.getenv("DEEPSEEK_API_KEY"), base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"))
    response = client.chat.completions.create(
        model="deepseek-chat",
        temperature=0.1,
        max_tokens=1024,
        messages=messages,
    )

    answer = response.choices[0].message.content

    # Deduplicate source filenames and expose short, human-verifiable excerpts.
    sources = sorted(
        {item["filename"] for item in metadatas if item.get("filename")}
    )
    citations = []
    seen = set()
    for doc, metadata, score in zip(docs, metadatas, result["scores"]):
        key = (metadata.get("stored_filename"), metadata.get("chunk_index"))
        if key in seen:
            continue
        seen.add(key)
        citations.append(
            {
                "filename": metadata.get("filename", "未知文件"),
                "section": metadata.get("section_title", "文档摘要"),
                "chunk": metadata.get("chunk_index", 0) + 1,
                "preview": " ".join(doc.split())[:180],
                "score": score,
            }
        )

    return {
        "answer": answer,
        "sources": sources,
        "citations": citations,
        "retrieval": {
            "has_sufficient_context": True,
            "best_dense_distance": result["best_dense_distance"],
            "best_bm25_score": result["best_bm25_score"],
        },
        "debug": result["debug"],
    }
