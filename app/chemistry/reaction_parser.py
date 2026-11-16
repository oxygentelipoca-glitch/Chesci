"""化学反应数据服务 — 基于 reactions.db 的数据查询与解析。

提供以下功能：
- 知识图谱数据构建（Scheme 节点 + 关联边）
- 反应详情、Scheme 详情查询
- 搜索和统计
- 提取日志查询
- 文本反应式解析（保留兼容）
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

from sqlalchemy import func, or_
from sqlmodel import Session, select

from app.chemistry.models import (
    Scheme, Reaction, ReactionCondition, Literature, ExtractionLog,
    ReactionEquation,
)
from app.database import chemistry_engine

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 正则模式（文本解析保留）
# ---------------------------------------------------------------------------

_REACTION_PATTERN = re.compile(r"^(.+?)\s*[→\->]+\s*([^(]+?)(?:\s*\((.+)\))?$")
_SPLIT_PLUS = re.compile(r"\s*\+\s*")
_COND_PATTERN = re.compile(
    r"(催化剂|溶剂|温度|时间|收率|类型|名称)\s*[：:=\s]+\s*([^,，;；]+)"
)
_COND_MAP = {
    "催化剂": "catalysts", "溶剂": "solvents", "温度": "temperature",
    "时间": "time", "收率": "yield", "类型": "reaction_type", "名称": "name",
}


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

# 纯元素 SMILES 碎片（如 CC、CCC、[K]、CCO）—— OCSR 识别噪声，图谱中过滤
_SIMPLE_SMILES_RE = re.compile(r"^(?:\[?[A-Z][a-z]?\]?\d*)+$")


def _split_csv(value: Optional[str]) -> list[str]:
    """将逗号分隔字符串拆分为列表。"""
    if not value:
        return []
    return [x.strip() for x in value.split(",") if x.strip()]


def _clamp(val: int, lo: int, hi: int) -> int:
    return max(lo, min(val, hi))


def _split_compound_names(text: Optional[str]) -> list[str]:
    """拆分方程式一侧的化合物名列表。

    中文名称用 ';' 分隔；SMILES 多组分用 '.' 连接。
    过滤 '?' 占位符、空白项，以及纯元素 SMILES 碎片（如 CC、[K]、CCC）。
    """
    result: list[str] = []
    for part in re.split(r"[;；]", text or ""):
        part = part.strip()
        if not part or part == "?":
            continue
        for sub in part.split("."):
            sub = sub.strip()
            if not sub or sub == "?":
                continue
            # 过滤无意义的纯元素 SMILES 碎片（OCSR 识别噪声）
            if sub.isascii() and _SIMPLE_SMILES_RE.match(sub):
                continue
            result.append(sub)
    return result


def _parse_equation_side(text: Optional[str]) -> tuple[list[str], list[str]]:
    """解析方程式文本 -> (反应物列表, 产物列表)。

    方程式格式：`反应物 (条件块) >> 产物`，条件块形如 `([1.1] ... | [1.2] ...)`。
    """
    if not text or ">>" not in text:
        return [], []
    left, right = text.split(">>", 1)
    # 去掉条件块（从 `([` 开始到行尾）
    left = re.sub(r"\s*\(\[.*$", "", left, flags=re.DOTALL).strip()
    right = re.sub(r"\s*\(\[.*$", "", right, flags=re.DOTALL).strip()
    return _split_compound_names(left), _split_compound_names(right)


# ---------------------------------------------------------------------------
# 统计
# ---------------------------------------------------------------------------

def get_stats() -> dict:
    """返回化学数据库统计概览。"""
    with Session(chemistry_engine) as session:
        scheme_count = session.exec(select(func.count()).select_from(Scheme)).one()
        reaction_count = session.exec(select(func.count()).select_from(Reaction)).one()
        lit_count = session.exec(select(func.count()).select_from(Literature)).one()
        smiles_count = session.exec(
            select(func.count()).where(
                or_(Reaction.reactant_smiles.isnot(None), Reaction.product_smiles.isnot(None))
            )
        ).one()
        log_count = session.exec(select(func.count()).select_from(ExtractionLog)).one()
        cond_count = session.exec(select(func.count()).select_from(ReactionCondition)).one()

    return {
        "schemes": scheme_count,
        "reactions": reaction_count,
        "literatures": lit_count,
        "reactions_with_smiles": smiles_count,
        "extraction_logs": log_count,
        "reaction_conditions": cond_count,
        "total": scheme_count + reaction_count,
    }


# ---------------------------------------------------------------------------
# Scheme 查询
# ---------------------------------------------------------------------------

def list_schemes(skip: int = 0, limit: int = 20, q: Optional[str] = None) -> dict:
    """分页列出 Scheme，支持按 scheme_number 搜索。"""
    skip = max(0, skip)
    limit = _clamp(limit, 1, 100)

    with Session(chemistry_engine) as session:
        stmt = select(Scheme)
        count_stmt = select(func.count()).select_from(Scheme)

        if q:
            from sqlalchemy import cast, String
            stmt = stmt.where(cast(Scheme.scheme_number, String).contains(q))
            count_stmt = count_stmt.where(cast(Scheme.scheme_number, String).contains(q))

        total = session.exec(count_stmt).one()
        schemes = session.exec(stmt.order_by(Scheme.scheme_number).offset(skip).limit(limit)).all()

        result = []
        for s in schemes:
            result.append({
                "id": s.id,
                "scheme_number": s.scheme_number,
                "reaction_count": s.reaction_count,
                "overall_yield": s.overall_yield,
                "overall_steps": s.overall_steps,
                "description": s.description,
                "page_start": s.page_start,
                "page_end": s.page_end,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            })

    return {"total": total, "skip": skip, "limit": limit, "items": result}


def get_scheme_detail(scheme_id: int) -> Optional[dict]:
    """获取 Scheme 详情，包含其下所有 Reaction（含 conditions 和 literature 摘要）。"""
    with Session(chemistry_engine) as session:
        scheme = session.get(Scheme, scheme_id)
        if not scheme:
            return None

        # 获取子 Reaction
        reactions = session.exec(
            select(Reaction).where(Reaction.scheme_id == scheme_id)
        ).all()

        reaction_list = []
        for r in reactions:
            conditions = session.exec(
                select(ReactionCondition).where(ReactionCondition.reaction_id == r.id)
            ).all()
            literature = session.exec(
                select(Literature).where(Literature.reaction_id == r.id)
            ).first()

            reaction_list.append({
                "id": r.id,
                "cas_registry_id": r.cas_registry_id,
                "yield_": r.yield_,
                "steps": r.steps,
                "reactants_text": r.reactants_text,
                "products_text": r.products_text,
                "page": r.page,
                "reactant_smiles": r.reactant_smiles,
                "product_smiles": r.product_smiles,
                "conditions": [{
                    "id": c.id,
                    "step_number": c.step_number,
                    "reagents": _split_csv(c.reagents),
                    "catalysts": _split_csv(c.catalysts),
                    "solvents": _split_csv(c.solvents),
                    "temperature": c.temperature,
                    "time": c.time,
                    "other": c.other,
                } for c in conditions],
                "literature": {
                    "title": literature.title,
                    "authors": literature.authors,
                    "journal": literature.journal,
                    "year": literature.year,
                } if literature else None,
            })

    return {
        "id": scheme.id,
        "scheme_number": scheme.scheme_number,
        "reaction_count": scheme.reaction_count,
        "overall_yield": scheme.overall_yield,
        "overall_steps": scheme.overall_steps,
        "description": scheme.description,
        "page_start": scheme.page_start,
        "page_end": scheme.page_end,
        "raw_json": scheme.raw_json,
        "reactions": reaction_list,
        "created_at": scheme.created_at.isoformat() if scheme.created_at else None,
    }


# ---------------------------------------------------------------------------
# Reaction 查询
# ---------------------------------------------------------------------------

def list_reactions(
    skip: int = 0,
    limit: int = 20,
    scheme_id: Optional[int] = None,
    cas_registry_id: Optional[str] = None,
    q: Optional[str] = None,
) -> dict:
    """分页列出 Reaction，支持过滤和搜索。"""
    skip = max(0, skip)
    limit = _clamp(limit, 1, 100)

    with Session(chemistry_engine) as session:
        stmt = select(Reaction)
        count_stmt = select(func.count()).select_from(Reaction)

        if scheme_id is not None:
            stmt = stmt.where(Reaction.scheme_id == scheme_id)
            count_stmt = count_stmt.where(Reaction.scheme_id == scheme_id)
        if cas_registry_id:
            stmt = stmt.where(Reaction.cas_registry_id == cas_registry_id)
            count_stmt = count_stmt.where(Reaction.cas_registry_id == cas_registry_id)
        if q:
            pattern = f"%{q}%"
            stmt = stmt.where(
                or_(
                    Reaction.cas_registry_id.contains(q),
                    Reaction.reactants_text.contains(q),
                    Reaction.products_text.contains(q),
                )
            )
            count_stmt = count_stmt.where(
                or_(
                    Reaction.cas_registry_id.contains(q),
                    Reaction.reactants_text.contains(q),
                    Reaction.products_text.contains(q),
                )
            )

        total = session.exec(count_stmt).one()
        reactions = session.exec(
            stmt.order_by(Reaction.id).offset(skip).limit(limit)
        ).all()

        result = []
        for r in reactions:
            # 获取关联 Scheme 摘要
            scheme = session.get(Scheme, r.scheme_id) if r.scheme_id else None
            literature = session.exec(
                select(Literature).where(Literature.reaction_id == r.id)
            ).first()

            result.append({
                "id": r.id,
                "scheme_id": r.scheme_id,
                "scheme_summary": {
                    "scheme_number": scheme.scheme_number,
                    "overall_yield": scheme.overall_yield,
                } if scheme else None,
                "cas_registry_id": r.cas_registry_id,
                "yield_": r.yield_,
                "steps": r.steps,
                "reactants_text": r.reactants_text,
                "products_text": r.products_text,
                "page": r.page,
                "reactant_smiles": r.reactant_smiles,
                "product_smiles": r.product_smiles,
                "literature_title": literature.title if literature else None,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            })

    return {"total": total, "skip": skip, "limit": limit, "items": result}


def get_reaction_detail(reaction_id: int) -> Optional[dict]:
    """获取 Reaction 详情（完整 conditions 列表 + literature + 方程式）。"""
    with Session(chemistry_engine) as session:
        r = session.get(Reaction, reaction_id)
        if not r:
            return None

        scheme = session.get(Scheme, r.scheme_id) if r.scheme_id else None
        conditions = session.exec(
            select(ReactionCondition).where(ReactionCondition.reaction_id == reaction_id)
        ).all()
        literature = session.exec(
            select(Literature).where(Literature.reaction_id == reaction_id)
        ).first()
        equation = session.exec(
            select(ReactionEquation).where(ReactionEquation.reaction_id == reaction_id)
        ).first()

    return {
        "id": r.id,
        "scheme_id": r.scheme_id,
        "scheme_summary": {
            "id": scheme.id,
            "scheme_number": scheme.scheme_number,
            "reaction_count": scheme.reaction_count,
            "overall_yield": scheme.overall_yield,
        } if scheme else None,
        "cas_registry_id": r.cas_registry_id,
        "yield_": r.yield_,
        "steps": r.steps,
        "reactants_text": r.reactants_text,
        "products_text": r.products_text,
        "page": r.page,
        "has_structure_image": r.has_structure_image,
        "reactant_smiles": r.reactant_smiles,
        "product_smiles": r.product_smiles,
        "ocsr_method": r.ocsr_method,
        "ocsr_confidence": r.ocsr_confidence,
        "notes": r.notes,
        "raw_json": r.raw_json,
        "conditions": [{
            "id": c.id,
            "step_number": c.step_number,
            "reagents": _split_csv(c.reagents),
            "catalysts": _split_csv(c.catalysts),
            "solvents": _split_csv(c.solvents),
            "temperature": c.temperature,
            "time": c.time,
            "other": c.other,
            "raw_text": c.raw_text,
        } for c in conditions],
        "literature": {
            "id": literature.id,
            "title": literature.title,
            "authors": literature.authors,
            "journal": literature.journal,
            "year": literature.year,
            "volume": literature.volume,
            "pages": literature.pages,
            "doi": literature.doi,
            "raw_text": literature.raw_text,
        } if literature else None,
        "equation": {
            "equation": equation.equation,
            "equation_zh": equation.equation_zh,
            "reactant_smiles": equation.reactant_smiles,
            "product_smiles": equation.product_smiles,
            "conditions_summary": equation.conditions_summary,
        } if equation else None,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


# ---------------------------------------------------------------------------
# 知识图谱数据
# ---------------------------------------------------------------------------

def get_graph_data() -> dict:
    """构建知识图谱数据：基于 reaction_equations 表的方程式。

    节点：从方程式解析的化合物（中文名优先，fallback SMILES/文本）。
    边：反应物→产物（主反应），催化剂→产物（催化关系）。

    方程式来源优先级：
    1. equation_zh（中文名称方程式，如「苯甲醛; 乙酸 (条件) >> 肉桂酸」）
    2. equation（SMILES 方程式）
    3. reactant_smiles / product_smiles
    4. reactions 表的 reactants_zh/products_zh 或 reactants_text/products_text
    """
    with Session(chemistry_engine) as session:
        equations = session.exec(select(ReactionEquation)).all()
        reactions_map = {r.id: r for r in session.exec(select(Reaction)).all()}
        schemes_map = {s.id: s for s in session.exec(select(Scheme)).all()}

        # 预加载所有 ReactionCondition，构建 reaction → conditions 映射
        cond_map: dict[int, list[ReactionCondition]] = {}
        for c in session.exec(select(ReactionCondition)).all():
            cond_map.setdefault(c.reaction_id, []).append(c)

        # 化合物索引：名称 → {category, count}
        compound_index: dict[str, dict] = {}
        links: list[dict] = []

        def _node_id(name: str) -> str:
            return f"node_{hash(name) & 0x7FFFFFFF}"

        def _register(name: str, category: str) -> None:
            """注册化合物节点；reactant/product 重叠时归为 both。"""
            info = compound_index.get(name)
            if info is None:
                info = {"category": category, "count": 0}
                compound_index[name] = info
            info["count"] += 1
            if {info["category"], category} == {"reactant", "product"}:
                info["category"] = "both"

        for eq in equations:
            reaction = reactions_map.get(eq.reaction_id)
            scheme = schemes_map.get(reaction.scheme_id) if reaction and reaction.scheme_id else None

            # 解析方程式化合物（中文方程式优先，逐级 fallback）
            reactants, products = _parse_equation_side(eq.equation_zh)
            if not (reactants or products):
                reactants, products = _parse_equation_side(eq.equation)
            if not (reactants or products) and reaction:
                # 中文/文本名称优先于 OCSR SMILES 碎片
                reactants = _split_compound_names(
                    reaction.reactants_zh or reaction.reactants_text or ""
                )
                products = _split_compound_names(
                    reaction.products_zh or reaction.products_text or ""
                )
            if not (reactants or products) and (eq.reactant_smiles or eq.product_smiles):
                reactants = _split_compound_names(eq.reactant_smiles or "")
                products = _split_compound_names(eq.product_smiles or "")

            # 注册反应物/产物节点
            for name in reactants:
                _register(name, "reactant")
            for name in products:
                _register(name, "product")

            # 从 conditions 提取催化剂/溶剂节点与催化边
            for cond in cond_map.get(eq.reaction_id, []):
                for cat in _split_csv(cond.catalysts):
                    if not cat:
                        continue
                    _register(cat, "catalyst")
                    for prod in products:
                        links.append({
                            "source": _node_id(cat),
                            "target": _node_id(prod),
                            "label": f"催化 → {reaction.yield_ or '?'}" if reaction else "催化",
                            "category": "catalysis",
                            "reaction_id": eq.reaction_id,
                        })
                for sol in _split_csv(cond.solvents):
                    if sol:
                        _register(sol, "solvent")

            # 反应物 → 产物 的主反应边
            for ra in reactants:
                for pr in products:
                    links.append({
                        "source": _node_id(ra),
                        "target": _node_id(pr),
                        "label": f"→ {reaction.yield_ or ''}" if reaction else "→",
                        "category": "reaction",
                        "reaction_id": eq.reaction_id,
                        "scheme_number": scheme.scheme_number if scheme else None,
                    })

        # 构建节点列表（按出现次数排序，取前 150 个避免图谱过大）
        nodes = []
        sorted_compounds = sorted(compound_index.items(), key=lambda x: x[1]["count"], reverse=True)
        color_map = {"reactant": "#7EB8C9", "product": "#065F46", "both": "#4A90A4", "catalyst": "#B8A07C", "solvent": "#8899AA"}
        for name, info in sorted_compounds[:150]:
            cat = info["category"]
            nodes.append({
                "id": _node_id(name),
                "name": name[:60],
                "category": cat,
                "symbolSize": min(16 + info["count"] * 2, 55),
                "color": color_map.get(cat, "#8899AA"),
                "reaction_count": info["count"],
            })

        # 仅保留两端节点都存在的边
        valid_node_ids = {n["id"] for n in nodes}
        links = [l for l in links if l["source"] in valid_node_ids and l["target"] in valid_node_ids]

    return {"nodes": nodes, "links": links}


# ---------------------------------------------------------------------------
# 搜索
# ---------------------------------------------------------------------------

def search_reactions(query: str, search_type: str = "all") -> dict:
    """全文搜索反应数据（结果含 reaction_equations 方程式信息）。"""
    if not query:
        return {"total": 0, "items": []}

    with Session(chemistry_engine) as session:
        results: list[dict] = []
        seen_ids = set()

        # 预加载方程式映射（reaction_id → ReactionEquation）
        eq_map: dict[int, ReactionEquation] = {
            eq.reaction_id: eq for eq in session.exec(select(ReactionEquation)).all()
        }

        def _enrich(item: dict, reaction_id: int) -> dict:
            """为搜索结果补充方程式信息。"""
            eq = eq_map.get(reaction_id)
            if eq:
                item["equation"] = eq.equation
                item["equation_zh"] = eq.equation_zh
                item["reactant_smiles"] = eq.reactant_smiles
                item["product_smiles"] = eq.product_smiles
            return item

        # 按 CAS 搜索
        if search_type in ("all", "cas"):
            cas_matches = session.exec(
                select(Reaction).where(Reaction.cas_registry_id.contains(query))
            ).all()
            for r in cas_matches:
                if r.id not in seen_ids:
                    seen_ids.add(r.id)
                    scheme = session.get(Scheme, r.scheme_id) if r.scheme_id else None
                    results.append(_enrich({
                        "id": r.id, "type": "reaction",
                        "cas_registry_id": r.cas_registry_id,
                        "reactants_text": r.reactants_text,
                        "products_text": r.products_text,
                        "yield_": r.yield_,
                        "scheme_number": scheme.scheme_number if scheme else None,
                        "match_field": "cas_registry_id",
                    }, r.id))

        # 按文献标题搜索
        if search_type in ("all", "literature"):
            lit_matches = session.exec(
                select(Reaction, Literature).join(Literature, Reaction.id == Literature.reaction_id)
                .where(or_(Literature.title.contains(query), Literature.authors.contains(query)))
            ).all()
            for r, lit in lit_matches:
                if r.id not in seen_ids:
                    seen_ids.add(r.id)
                    scheme = session.get(Scheme, r.scheme_id) if r.scheme_id else None
                    results.append(_enrich({
                        "id": r.id, "type": "reaction",
                        "cas_registry_id": r.cas_registry_id,
                        "reactants_text": r.reactants_text,
                        "products_text": r.products_text,
                        "yield_": r.yield_,
                        "literature_title": lit.title,
                        "scheme_number": scheme.scheme_number if scheme else None,
                        "match_field": "literature",
                    }, r.id))

        # 按反应物/产物文本搜索（含中英文名与方程式表）
        if search_type in ("all", "cas"):
            eq_matched_ids = session.exec(
                select(ReactionEquation.reaction_id).where(
                    or_(
                        ReactionEquation.equation.contains(query),
                        ReactionEquation.equation_zh.contains(query),
                    )
                )
            ).all()
            text_matches = session.exec(
                select(Reaction).where(
                    or_(
                        Reaction.reactants_text.contains(query),
                        Reaction.products_text.contains(query),
                        Reaction.reactants_zh.contains(query),
                        Reaction.products_zh.contains(query),
                        Reaction.reactants_en.contains(query),
                        Reaction.products_en.contains(query),
                        Reaction.id.in_(eq_matched_ids),
                    )
                )
            ).all()
            for r in text_matches:
                if r.id not in seen_ids:
                    seen_ids.add(r.id)
                    scheme = session.get(Scheme, r.scheme_id) if r.scheme_id else None
                    results.append(_enrich({
                        "id": r.id, "type": "reaction",
                        "cas_registry_id": r.cas_registry_id,
                        "reactants_text": r.reactants_text,
                        "products_text": r.products_text,
                        "yield_": r.yield_,
                        "scheme_number": scheme.scheme_number if scheme else None,
                        "match_field": "text",
                    }, r.id))

    return {"total": len(results), "items": results}


# ---------------------------------------------------------------------------
# 提取日志
# ---------------------------------------------------------------------------

def list_extraction_logs(skip: int = 0, limit: int = 20, status: Optional[str] = None) -> dict:
    """分页列出提取日志。"""
    skip = max(0, skip)
    limit = _clamp(limit, 1, 100)

    with Session(chemistry_engine) as session:
        stmt = select(ExtractionLog)
        count_stmt = select(func.count()).select_from(ExtractionLog)

        if status:
            stmt = stmt.where(ExtractionLog.status == status)
            count_stmt = count_stmt.where(ExtractionLog.status == status)

        total = session.exec(count_stmt).one()
        logs = session.exec(
            stmt.order_by(ExtractionLog.batch_number.desc()).offset(skip).limit(limit)
        ).all()

        result = []
        for log in logs:
            result.append({
                "id": log.id,
                "batch_number": log.batch_number,
                "page_start": log.page_start,
                "page_end": log.page_end,
                "status": log.status,
                "schemes_found": log.schemes_found,
                "reactions_found": log.reactions_found,
                "model_used": log.model_used,
                "tokens_used": log.tokens_used,
                "duration_seconds": log.duration_seconds,
                "error_message": log.error_message,
                "created_at": log.created_at.isoformat() if log.created_at else None,
            })

    return {"total": total, "skip": skip, "limit": limit, "items": result}


# ---------------------------------------------------------------------------
# 文本反应式解析（保留兼容）
# ---------------------------------------------------------------------------

def parse_reaction_text(text: str) -> dict:
    """解析单条反应式文本（不依赖数据库）。"""
    text = text.strip()
    m = _REACTION_PATTERN.match(text)
    if not m:
        return {"error": f"无法解析反应式: {text}", "raw": text}

    reactant_str = m.group(1).strip()
    product_str = m.group(2).strip()
    cond_str = m.group(3) or ""

    reactants = [r.strip() for r in _SPLIT_PLUS.split(reactant_str) if r.strip()]
    products = [p.strip() for p in _SPLIT_PLUS.split(product_str) if p.strip()]

    conditions = {}
    for cm in _COND_PATTERN.finditer(cond_str):
        key = cm.group(1)
        value = cm.group(2).strip()
        mapped_key = _COND_MAP.get(key, key)
        if mapped_key == "yield":
            try:
                conditions[mapped_key] = float(value.replace("%", ""))
            except ValueError:
                conditions[mapped_key] = value
        else:
            conditions[mapped_key] = value

    equation = f"{' + '.join(reactants)} → {' + '.join(products)}"

    return {
        "reactants": reactants,
        "products": products,
        "conditions": conditions,
        "equation": equation,
    }


def parse_batch_reactions(text: str) -> list[dict]:
    """批量解析反应式文本。"""
    results = []
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        result = parse_reaction_text(line)
        results.append(result)
    return results


def save_parsed_reactions(parsed: list[dict], user_id: Optional[int] = None) -> dict:
    """将解析结果保存到化学数据库。"""
    compounds_added = 0
    reactions_added = 0
    errors = []

    with Session(chemistry_engine) as session:
        for item in parsed:
            if "error" in item:
                errors.append(item["error"])
                continue

            try:
                cond = item.get("conditions", {})
                reaction = Reaction(
                    reactants_text=" + ".join(item.get("reactants", [])),
                    products_text=" + ".join(item.get("products", [])),
                    yield_=str(cond.get("yield", "")) if cond.get("yield") else None,
                    page=0,
                    has_structure_image=False,
                )
                session.add(reaction)
                session.flush()

                # 创建反应条件
                rc = ReactionCondition(
                    reaction_id=reaction.id,
                    step_number="1.1",
                    reagents=", ".join(item.get("reactants", [])),
                    catalysts=cond.get("catalysts", ""),
                    solvents=cond.get("solvents", ""),
                    temperature=cond.get("temperature", ""),
                    time=cond.get("time", ""),
                )
                session.add(rc)
                reactions_added += 1

            except Exception as exc:
                errors.append(str(exc))

        session.commit()

    return {
        "compounds_added": compounds_added,
        "reactions_added": reactions_added,
        "errors": errors,
    }
