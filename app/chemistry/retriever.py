"""化学文献 RAG 检索器。

封装现有的 Hybrid RAG 管道，针对化学领域做查询优化：
- 根据化合物信息（名称、CAS、SMILES）构造精确检索查询
- 调用 ``app.services.rag_service`` 的混合检索能力
- 返回去重、格式化后的文献片段
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def build_search_query(compound_name: str, intent: str = "synthesis") -> str:
    """根据化合物名称和检索意图构造优化查询。

    Parameters
    ----------
    compound_name : str
        目标化合物名称。
    intent : str
        检索意图：``synthesis``（合成路线）、``property``（性质）、
        ``reaction``（反应条件）、``general``（通用）。

    Returns
    -------
    str
        优化后的检索查询字符串。
    """
    templates = {
        "synthesis": f"{compound_name} 合成 路线 方法 反应条件 收率",
        "property": f"{compound_name} 物理性质 化学性质 稳定性 溶解度",
        "reaction": f"{compound_name} 反应 催化剂 溶剂 温度 机理",
        "general": f"{compound_name} 研究 应用 综述",
    }
    return templates.get(intent, templates["general"])


def search_literature(
    compound_name: str,
    question: str = "",
    intent: str = "synthesis",
    user_id: int | None = None,
    top_k: int = 6,
    include_debug: bool = False,
) -> dict[str, Any]:
    """检索与目标化合物相关的文献片段。

    Parameters
    ----------
    compound_name : str
        目标化合物名称。
    question : str
        用户原始问题（为空时自动构造查询）。
    intent : str
        检索意图类型。
    user_id : int | None
        用户 ID 用于权限过滤。
    top_k : int
        返回的最大片段数。
    include_debug : bool
        是否包含调试信息。

    Returns
    -------
    dict
        ``{"documents": [...], "metadatas": [...], "scores": [...], ...}``
    """
    # 构造查询
    if question.strip():
        query = f"{compound_name} {question}"
    else:
        query = build_search_query(compound_name, intent)

    logger.info("化学文献检索: compound=%s, query=%s", compound_name, query[:80])

    # 调用现有 RAG 管道
    from app.services.rag_service import search_knowledge

    result = search_knowledge(
        query,
        user_id=user_id,
        top_k=top_k,
        final_k=top_k,
        adaptive=True,
        include_debug=include_debug,
    )

    return result


def format_context(documents: list[str], metadatas: list[dict]) -> str:
    """将检索结果格式化为 LLM 可用的上下文字符串。

    Parameters
    ----------
    documents : list[str]
        文档片段文本列表。
    metadatas : list[dict]
        对应的元数据列表。

    Returns
    -------
    str
        格式化的上下文文本。
    """
    if not documents:
        return "（未检索到相关文献资料）"

    parts = []
    for i, (doc, meta) in enumerate(zip(documents, metadatas), 1):
        source = meta.get("filename", "未知来源")
        section = meta.get("section_title", "")
        parts.append(
            f"[文献片段 {i}] 来源: {source}"
            + (f" | 章节: {section}" if section else "")
            + f"\n{doc.strip()}"
        )
    return "\n\n".join(parts)


def format_sources(metadatas: list[dict]) -> list[dict]:
    """从元数据提取来源引用列表。

    Returns
    -------
    list[dict]
        每个元素包含 ``filename``, ``section``。
    """
    seen = set()
    sources = []
    for meta in metadatas:
        key = (meta.get("filename", ""), meta.get("section_title", ""))
        if key not in seen:
            seen.add(key)
            sources.append({
                "filename": meta.get("filename", ""),
                "section": meta.get("section_title", ""),
            })
    return sources
