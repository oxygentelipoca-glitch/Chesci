"""化学数据库 API 路由 — 基于 reactions.db 的 Scheme/Reaction 数据模型。

端点
----
- Scheme 查询：GET /schemes, GET /schemes/{scheme_id}
- Reaction 查询：GET /reactions, GET /reactions/{reaction_id}
- Reaction 子资源：GET /reactions/{reaction_id}/conditions, GET /reactions/{reaction_id}/literature
- 知识图谱：GET /graph
- 全文搜索：GET /search
- 统计概览：GET /stats
- 提取日志：GET /extraction-logs, GET /extraction-logs/{log_id}
- 兼容接口：POST /analyze
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlmodel import Session, select

from app.core.auth import get_current_user, get_optional_current_user
from app.core.response import api_error, api_success
from app.database import engine, get_chemistry_session
from app.models import SearchHistory
from app.chemistry.models import (
    Scheme,
    Reaction,
    ReactionCondition,
    Literature,
    ExtractionLog,
)
from app.chemistry.reaction_parser import (
    get_graph_data,
    get_stats,
    list_schemes,
    get_scheme_detail,
    list_reactions,
    get_reaction_detail,
    search_reactions,
    list_extraction_logs,
)
from app.services.chemistry_service import analyze_target
from app.chemistry.agent import generate_experiment_plan

router = APIRouter(prefix="/api/chemistry", tags=["Chemistry"])


# ═══════════════════════════════════════════════════════════════════════════
# 1. Scheme 查询
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/schemes")
def list_schemes_endpoint(
    skip: int = Query(default=0, ge=0, description="跳过记录数"),
    limit: int = Query(default=20, ge=1, le=100, description="返回记录数"),
    q: str = Query(default="", description="搜索 scheme_number（部分匹配）"),
    session: Session = Depends(get_chemistry_session),
):
    """分页列出所有 Scheme，支持按 scheme_number 搜索。"""
    result = list_schemes(skip, limit, q or None)
    return api_success("方案列表", result)


@router.get("/schemes/{scheme_id}")
def get_scheme(
    scheme_id: int,
    session: Session = Depends(get_chemistry_session),
):
    """Scheme 详情，包含其下所有 Reaction（含 conditions 和 literature 摘要）。"""
    detail = get_scheme_detail(scheme_id)
    if detail is None:
        return api_error("方案不存在", status_code=404)
    return api_success("方案详情", detail)


# ═══════════════════════════════════════════════════════════════════════════
# 2. Reaction 查询
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/reactions")
def list_reactions_endpoint(
    skip: int = Query(default=0, ge=0, description="跳过记录数"),
    limit: int = Query(default=20, ge=1, le=100, description="返回记录数"),
    scheme_id: Optional[int] = Query(default=None, description="按 Scheme ID 过滤"),
    cas_registry_id: Optional[str] = Query(default=None, description="按 CAS Registry ID 过滤"),
    q: str = Query(default="", description="搜索反应物/产物文本"),
    session: Session = Depends(get_chemistry_session),
):
    """分页列出所有 Reaction，支持按 Scheme、CAS Registry ID 和文本搜索过滤。"""
    result = list_reactions(
        skip=skip,
        limit=limit,
        scheme_id=scheme_id,
        cas_registry_id=cas_registry_id or None,
        q=q or None,
    )
    return api_success("反应列表", result)


@router.get("/reactions/{reaction_id}")
def get_reaction(
    reaction_id: int,
    session: Session = Depends(get_chemistry_session),
):
    """Reaction 详情，包含完整 conditions 列表和 literature。"""
    detail = get_reaction_detail(reaction_id)
    if detail is None:
        return api_error("反应不存在", status_code=404)
    return api_success("反应详情", detail)


@router.get("/reactions/{reaction_id}/conditions")
def get_reaction_conditions(
    reaction_id: int,
    session: Session = Depends(get_chemistry_session),
):
    """获取指定 Reaction 的全部反应条件。"""
    reaction = session.get(Reaction, reaction_id)
    if not reaction:
        return api_error("反应不存在", status_code=404)

    conditions = session.exec(
        select(ReactionCondition)
        .where(ReactionCondition.reaction_id == reaction_id)
        .order_by(ReactionCondition.step_number)
    ).all()

    items = [
        {
            "id": c.id,
            "step_number": c.step_number,
            "reagents": c.reagents,
            "catalysts": c.catalysts,
            "solvents": c.solvents,
            "temperature": c.temperature,
            "time": c.time,
            "other": c.other,
            "raw_text": c.raw_text,
        }
        for c in conditions
    ]

    return api_success("反应条件列表", {
        "reaction_id": reaction_id,
        "total": len(items),
        "conditions": items,
    })


@router.get("/reactions/{reaction_id}/literature")
def get_reaction_literature(
    reaction_id: int,
    session: Session = Depends(get_chemistry_session),
):
    """获取指定 Reaction 的关联文献。"""
    reaction = session.get(Reaction, reaction_id)
    if not reaction:
        return api_error("反应不存在", status_code=404)

    lit = session.exec(
        select(Literature).where(Literature.reaction_id == reaction_id)
    ).first()

    if not lit:
        return api_error("该反应没有关联文献", status_code=404)

    return api_success("文献详情", {
        "id": lit.id,
        "reaction_id": lit.reaction_id,
        "title": lit.title,
        "authors": lit.authors,
        "journal": lit.journal,
        "year": lit.year,
        "volume": lit.volume,
        "pages": lit.pages,
        "doi": lit.doi,
        "raw_text": lit.raw_text,
    })


# ═══════════════════════════════════════════════════════════════════════════
# 3. 知识图谱
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/graph")
def graph(
    session: Session = Depends(get_chemistry_session),
):
    """获取知识图谱可视化数据 — 化合物节点 + 反应边。"""
    data = get_graph_data()
    return api_success("图谱数据", data)


# ═══════════════════════════════════════════════════════════════════════════
# 4. 全文搜索
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/search")
def search(
    q: str = Query(default="", description="搜索关键词"),
    type: str = Query(default="all", description="搜索类型: all, cas, literature"),
    session: Session = Depends(get_chemistry_session),
):
    """全文搜索：按 cas_registry_id、文献标题、反应物/产物文本搜索。"""
    if not q.strip():
        return api_error("请提供搜索关键词 q", status_code=400)

    result = search_reactions(q.strip(), type)
    return api_success("搜索结果", result)


# ═══════════════════════════════════════════════════════════════════════════
# 5. 统计概览
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/stats")
def stats(
    session: Session = Depends(get_chemistry_session),
):
    """统计概览：总 Scheme 数、总 Reaction 数、总 Literature 数、有 SMILES 的反应数。"""
    result = get_stats()
    return api_success("统计完成", result)


# ═══════════════════════════════════════════════════════════════════════════
# 6. 提取日志
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/extraction-logs")
def extraction_logs_list(
    skip: int = Query(default=0, ge=0, description="跳过记录数"),
    limit: int = Query(default=20, ge=1, le=100, description="返回记录数"),
    status: str = Query(default="", description="按状态过滤: success, failed, partial"),
    session: Session = Depends(get_chemistry_session),
):
    """分页列出提取日志，支持按状态过滤。"""
    result = list_extraction_logs(skip, limit, status or None)
    return api_success("提取日志列表", result)


@router.get("/extraction-logs/{log_id}")
def get_extraction_log(
    log_id: int,
    session: Session = Depends(get_chemistry_session),
):
    """单个提取日志详情（含 raw_response）。"""
    log = session.get(ExtractionLog, log_id)
    if not log:
        return api_error("提取日志不存在", status_code=404)

    return api_success("提取日志详情", {
        "id": log.id,
        "batch_number": log.batch_number,
        "page_start": log.page_start,
        "page_end": log.page_end,
        "status": log.status,
        "schemes_found": log.schemes_found,
        "reactions_found": log.reactions_found,
        "error_message": log.error_message,
        "raw_response": log.raw_response,
        "model_used": log.model_used,
        "tokens_used": log.tokens_used,
        "duration_seconds": log.duration_seconds,
        "created_at": log.created_at.isoformat() if log.created_at else None,
    })


# ═══════════════════════════════════════════════════════════════════════════
# 7. 兼容接口：POST /analyze
# ═══════════════════════════════════════════════════════════════════════════

class AnalyzeRequest(BaseModel):
    """分析请求体。"""
    query: str = Field(..., min_length=1, max_length=500, description="目标化合物名称或 CAS 号")
    starting_material: Optional[str] = Field(
        default=None, max_length=200, description="可选起始原料；按反应物字段进行文本匹配",
    )
    min_yield: Optional[float] = Field(
        default=None, ge=0, le=100,
        description="筛选条件：最低收率（%）",
    )
    max_steps: Optional[int] = Field(
        default=None, ge=1, le=20,
        description="筛选条件：最大步骤数",
    )
    max_temperature: Optional[float] = Field(
        default=None, ge=-100, le=1000,
        description="筛选条件：最高反应温度（°C）",
    )
    max_time_hours: Optional[float] = Field(
        default=None, ge=0, le=1000,
        description="筛选条件：最长反应时间（小时）",
    )
    catalyst: Optional[str] = Field(
        default=None, pattern="^(any|with|without)$",
        description="筛选条件：是否使用催化剂（any=不限, with=使用, without=不使用）",
    )
    workup: Optional[str] = Field(
        default=None, pattern="^(any|with|without)$",
        description="筛选条件：是否有后处理（any=不限, with=有, without=无）",
    )
    solvent: Optional[str] = Field(
        default=None, pattern="^(any|with|without)$",
        description="筛选条件：是否使用溶剂（any=不限, with=使用, without=不使用）",
    )
    catalyst_name: Optional[str] = Field(
        default=None, max_length=200,
        description="筛选条件：催化剂名称关键词（如 Piperidine，大小写不敏感）",
    )
    solvent_name: Optional[str] = Field(
        default=None, max_length=200,
        description="筛选条件：溶剂名称关键词（如 Water，大小写不敏感）",
    )
    top_n: Optional[int] = Field(
        default=None, ge=1, le=20,
        description="返回最接近匹配的前几项（默认 5）",
    )


@router.post("/analyze")
def analyze(
    request: AnalyzeRequest,
    session: Session = Depends(get_chemistry_session),
    current_user: Optional[dict] = Depends(get_optional_current_user),
):
    """完整分析接口：基于 reactions.db 的 Scheme/Reaction 数据模型。

    搜索匹配的 Reaction（CAS Registry ID / 反应物 / 产物文本），
    返回关联 Scheme、Literature、多维度评分、上下游推导和 LLM 分析报告。
    提供 min_yield/max_steps/max_temperature 筛选条件时，额外返回按条件
    满足度与总分排序的 filter_matches 前几项。
    """
    query = request.query.strip()

    has_value_filters = any(
        v is not None
        for v in (
            request.min_yield, request.max_steps,
            request.max_temperature, request.max_time_hours,
        )
    )
    has_pref_filters = any(
        p not in (None, "any")
        for p in (request.catalyst, request.workup, request.solvent)
    )
    has_name_filters = any(
        (v or "").strip()
        for v in (request.catalyst_name, request.solvent_name)
    )

    filters = None
    if has_value_filters or has_pref_filters or has_name_filters:
        filters = {
            "min_yield": request.min_yield,
            "max_steps": request.max_steps,
            "max_temperature": request.max_temperature,
            "max_time_hours": request.max_time_hours,
            "catalyst": request.catalyst,
            "workup": request.workup,
            "solvent": request.solvent,
            "catalyst_name": request.catalyst_name,
            "solvent_name": request.solvent_name,
            "top_n": request.top_n,
        }

    result = analyze_target(
        query,
        filters=filters,
        starting_material=request.starting_material,
    )

    # 记录搜索历史（仅登录用户）
    user_id = (current_user or {}).get("uid")
    if isinstance(user_id, int):
        with Session(engine) as main_session:
            main_session.add(SearchHistory(
                user_id=user_id,
                query=query,
                filters_json=json.dumps(filters, ensure_ascii=False) if filters else None,
                result_count=len(result.get("reactions") or []),
            ))
            main_session.commit()

    return api_success("分析完成", result)


class ExperimentPlanRequest(BaseModel):
    """输入已选路线和证据，生成需要人工复核的方案草案。"""
    compound: dict = Field(..., description="目标化合物信息")
    route: Optional[dict] = Field(default=None, description="选中的反应路线")
    literature_context: str = Field(default="", max_length=12000)
    extra_instructions: str = Field(default="", max_length=2000)


@router.post("/experiment-plan")
def create_experiment_plan(
    request: ExperimentPlanRequest,
    current_user: Optional[dict] = Depends(get_optional_current_user),
):
    """生成实验方案草案；结果必须由具备资质的人员审核后使用。"""
    result = generate_experiment_plan(
        compound=request.compound,
        route=request.route,
        literature_context=request.literature_context,
        extra_instructions=request.extra_instructions,
    )
    result["review_notice"] = "AI 生成内容仅为研究草案；请核对原始文献、实验室规范和安全要求后再决定是否采用。"
    return api_success("实验方案草案已生成", result)


# ═══════════════════════════════════════════════════════════════════════════
# 8. 搜索历史（按用户隔离）
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/search-history")
def search_history_list(
    skip: int = Query(default=0, ge=0, description="跳过记录数"),
    limit: int = Query(default=20, ge=1, le=100, description="返回记录数"),
    current_user: dict = Depends(get_current_user),
):
    """当前用户的搜索历史（倒序分页）。"""
    user_id = current_user.get("uid")
    if not isinstance(user_id, int):
        return api_error("认证信息无效", status_code=401)

    with Session(engine) as session:
        total = session.exec(
            select(func.count()).select_from(SearchHistory).where(
                SearchHistory.user_id == user_id
            )
        ).one()
        items = session.exec(
            select(SearchHistory)
            .where(SearchHistory.user_id == user_id)
            .order_by(SearchHistory.id.desc())
            .offset(skip)
            .limit(limit)
        ).all()
        result = [{
            "id": h.id,
            "query": h.query,
            "filters": json.loads(h.filters_json) if h.filters_json else None,
            "result_count": h.result_count,
            "created_at": h.created_at.isoformat() if h.created_at else None,
        } for h in items]

    return api_success("搜索历史", {"total": total, "skip": skip, "limit": limit, "items": result})


@router.delete("/search-history/{history_id}")
def delete_search_history_item(
    history_id: int,
    current_user: dict = Depends(get_current_user),
):
    """删除当前用户的一条搜索历史。"""
    user_id = current_user.get("uid")
    if not isinstance(user_id, int):
        return api_error("认证信息无效", status_code=401)

    with Session(engine) as session:
        item = session.get(SearchHistory, history_id)
        if item is None or item.user_id != user_id:
            return api_error("记录不存在", status_code=404)
        session.delete(item)
        session.commit()

    return api_success("已删除", {"id": history_id})


@router.delete("/search-history")
def clear_search_history(
    current_user: dict = Depends(get_current_user),
):
    """清空当前用户的全部搜索历史。"""
    user_id = current_user.get("uid")
    if not isinstance(user_id, int):
        return api_error("认证信息无效", status_code=401)

    with Session(engine) as session:
        items = session.exec(
            select(SearchHistory).where(SearchHistory.user_id == user_id)
        ).all()
        deleted = len(items)
        for item in items:
            session.delete(item)
        session.commit()

    return api_success("已清空", {"deleted": deleted})


# ═══════════════════════════════════════════════════════════════════════════
# 9. 在线文献检索（代理 OpenAlex / Crossref 开放 API）
# ═══════════════════════════════════════════════════════════════════════════

_ONLINE_TIMEOUT_SECONDS = 15


def _fetch_json(url: str) -> Optional[dict]:
    """GET 外部 API 并解析 JSON；网络/解析失败返回 None。"""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ChemRoute/1.0"})
        with urllib.request.urlopen(req, timeout=_ONLINE_TIMEOUT_SECONDS) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def _rebuild_abstract(inverted_index: Optional[dict]) -> Optional[str]:
    """OpenAlex 摘要为倒排索引（词 → 位置列表），重建为文本。"""
    if not inverted_index:
        return None
    positions: dict[int, str] = {}
    for word, idx_list in inverted_index.items():
        for pos in idx_list:
            positions[pos] = word
    return " ".join(positions[i] for i in sorted(positions)) or None


def _search_openalex(query: str, limit: int) -> Optional[list[dict]]:
    """调用 OpenAlex 检索文献；返回统一结构列表，服务不可用时返回 None。"""
    url = (
        "https://api.openalex.org/works"
        f"?search={urllib.parse.quote(query)}"
        f"&per-page={limit}"
        "&select=id,doi,title,display_name,publication_year,authorships,"
        "primary_location,cited_by_count,abstract_inverted_index"
    )
    data = _fetch_json(url)
    if data is None:
        return None

    items = []
    for w in data.get("results") or []:
        authors = ", ".join(
            (a.get("author") or {}).get("display_name") or ""
            for a in (w.get("authorships") or [])
            if (a.get("author") or {}).get("display_name")
        ) or None
        source_info = (w.get("primary_location") or {}).get("source") or {}
        doi = (w.get("doi") or "").replace("https://doi.org/", "") or None
        items.append({
            "title": w.get("title") or w.get("display_name"),
            "authors": authors,
            "journal": source_info.get("display_name"),
            "year": w.get("publication_year"),
            "doi": doi,
            "abstract": _rebuild_abstract(w.get("abstract_inverted_index")),
            "cited_by": w.get("cited_by_count"),
            "source": "openalex",
        })
    return items


def _search_crossref(query: str, limit: int) -> Optional[list[dict]]:
    """调用 Crossref 检索文献；返回统一结构列表，服务不可用时返回 None。"""
    url = (
        "https://api.crossref.org/works"
        f"?query={urllib.parse.quote(query)}"
        f"&rows={min(limit, 50)}"
        "&select=DOI,title,author,container-title,issued,published-print"
    )
    data = _fetch_json(url)
    if data is None:
        return None

    items = []
    for w in (data.get("message") or {}).get("items") or []:
        titles = w.get("title") or []
        authors_list = []
        for a in w.get("author") or []:
            name = " ".join(x for x in [a.get("given"), a.get("family")] if x)
            if name:
                authors_list.append(name)
        issued = w.get("issued") or w.get("published-print") or {}
        date_parts = issued.get("date-parts") or [[None]]
        year = date_parts[0][0] if date_parts and date_parts[0] else None
        journal = (w.get("container-title") or [None])[0]
        items.append({
            "title": titles[0] if titles else None,
            "authors": ", ".join(authors_list) or None,
            "journal": journal,
            "year": int(year) if isinstance(year, int) else None,
            "doi": w.get("DOI"),
            "abstract": None,
            "cited_by": None,
            "source": "crossref",
        })
    return items


@router.get("/literature-online")
def literature_online(
    q: str = Query(..., min_length=1, max_length=200, description="检索关键词"),
    source: str = Query(default="openalex", description="文献源: openalex / crossref"),
    limit: int = Query(default=20, ge=1, le=50, description="返回条数"),
):
    """在线文献检索：代理 OpenAlex / Crossref 开放 API。

    返回统一结构：标题、作者、期刊、年份、DOI、摘要、被引数。
    """
    query = q.strip()
    if not query:
        return api_error("请提供检索关键词 q", status_code=400)

    items = (
        _search_crossref(query, limit)
        if source == "crossref"
        else _search_openalex(query, limit)
    )
    if items is None:
        return api_error("在线文献服务不可用，请稍后重试", status_code=502)

    return api_success("在线检索结果", {
        "total": len(items),
        "items": items,
        "source": source,
    })
