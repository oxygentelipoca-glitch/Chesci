"""化学合成分析服务 — 基于 reactions.db 的查询与 LLM 分析。

入口函数 analyze_target：搜索反应数据库 + 可选的 DeepSeek LLM 分析。
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Optional

from dotenv import load_dotenv
from openai import OpenAI
from sqlalchemy import or_
from sqlmodel import Session, select

from app.chemistry.models import Reaction, Scheme, Literature, ReactionCondition, ReactionEquation
from app.chemistry.constraints import evaluate_constraints
from app.chemistry.scoring import score_reaction
from app.database import chemistry_engine

load_dotenv()
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# LLM 客户端
# ---------------------------------------------------------------------------

_client: Optional[OpenAI] = None


def _source_details(raw):
    """Keep old records with free-form extraction text readable."""
    if not raw or not any(key in raw for key in ('"source_refs"', '"paper_evidence"')):
        return {"source_refs": []}
    try:
        record = json.loads(raw)
    except (ValueError, TypeError):
        return {"source_refs": []}
    if not isinstance(record, dict):
        return {"source_refs": []}
    links = record.get("source_refs") or []
    refs = [{"label": ref["label"], "url": ref["url"]} for ref in links
            if isinstance(ref, dict) and isinstance(ref.get("label"), str)
            and isinstance(ref.get("url"), str) and ref["url"].startswith("https://")] if isinstance(links, list) else []
    evidence = record.get("paper_evidence")
    return {"source_refs": refs, "paper_evidence": evidence if isinstance(evidence, list) else [],
            "source_file": record.get("source_file")}


def _equation_sides(equation: Optional[str]) -> tuple[str, str]:
    """Return reactant and product sides, excluding the condition block."""
    if not equation or ">>" not in equation:
        return "", ""
    left, right = equation.split(">>", 1)
    left = re.sub(r"\s*\(\[.*$", "", left, flags=re.DOTALL).strip()
    right = re.sub(r"\s*\(\[.*$", "", right, flags=re.DOTALL).strip()
    return left, right


def _contains_value(haystack: Optional[str], needle: str) -> bool:
    return bool(haystack and needle.casefold() in haystack.casefold())


def _get_llm() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=os.getenv("DEEPSEEK_API_KEY", ""),
            base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        )
    return _client


# ---------------------------------------------------------------------------
# System Prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """你是一个专业的有机化学合成分析助手。

你的任务是根据提供的化合物信息和反应数据库查询结果，分析目标化合物的合成路线。

## 输出格式

请严格按以下结构输出（用 Markdown）：

### 1. 化合物信息
- 目标化合物名称 / CAS Registry ID
- 匹配到的反应数量、Scheme 数量

### 2. 相关反应
对每条重要反应列出：
- 反应方程式（如提供）
- 反应物 / 产物结构式 SMILES（如提供，务必展示）
- 反应条件（催化剂、溶剂、温度、时间）
- 收率
- 文献出处（用 [n] 编号引用"参考文献"章节）

### 3. 合成路线分析
- 路线可行性评估
- 条件优劣势对比
- 改进建议

### 4. 评分与推荐
- 按综合评分从高到低排序，给出推荐结论
- 说明各维度的得分依据（收率 / 步骤 / 温度 / 安全）

### 5. 参考文献
- 列出报告中引用的文献编号 [n]，每条包含：标题、作者、期刊、年份

## 规则
- 回答基于提供的资料，资料不足时明确说明
- 化学术语保持专业准确
- 不要编造未在资料中出现的数据
- 文献引用必须使用提供的编号列表，禁止虚构文献
"""


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def analyze_target(
    query: str,
    user_id: Optional[int] = None,
    filters: Optional[dict] = None,
    starting_material: Optional[str] = None,
) -> dict[str, Any]:
    """搜索并分析目标化合物。

    在 reactions.db 中搜索匹配的 cas_registry_id 或反应物/产物文本，
    返回关联的 Scheme、Literature 和评分信息。

    Parameters
    ----------
    query : str
        搜索关键词（CAS Registry ID、化合物名称等）。
    user_id : int or None
        用户 ID（保留兼容）。
    filters : dict or None
        可选筛选条件：{"min_yield": float, "max_steps": int,
        "max_temperature": float, "top_n": int}。提供后返回
        filter_matches（按条件满足度与总分排序的前几项）。

    Returns
    -------
    dict
        {"success": bool, "query": str, "reactions": [...], "schemes": [...],
         "answer": str, "scored": [...], "filter_matches": {...} or None}
    """
    starting_material = (starting_material or "").strip()

    with Session(chemistry_engine) as session:
        # 方程式表匹配（equation / equation_zh）
        eq_matched_ids = session.exec(
            select(ReactionEquation.reaction_id).where(
                or_(
                    ReactionEquation.equation.contains(query),
                    ReactionEquation.equation_zh.contains(query),
                )
            )
        ).all()

        # 搜索匹配的 Reaction（CAS / 文本 / 中英文名 / 方程式表）
        reactions = session.exec(
            select(Reaction).where(
                or_(
                    Reaction.cas_registry_id.contains(query),
                    Reaction.reactants_text.contains(query),
                    Reaction.products_text.contains(query),
                    Reaction.reactants_zh.contains(query),
                    Reaction.products_zh.contains(query),
                    Reaction.reactants_en.contains(query),
                    Reaction.products_en.contains(query),
                    Reaction.reactant_smiles == query,
                    Reaction.product_smiles == query,
                    Reaction.id.in_(eq_matched_ids),
                )
            ).limit(30)
        ).all()

        if not reactions:
            # 尝试模糊搜索
            reactions = session.exec(
                select(Reaction).where(
                    Reaction.cas_registry_id.contains(query)
                ).limit(10)
            ).all()

        equation_by_reaction = {}
        reaction_ids = [reaction.id for reaction in reactions if reaction.id is not None]
        if reaction_ids:
            equation_rows = session.exec(
                select(ReactionEquation).where(
                    ReactionEquation.reaction_id.in_(reaction_ids)
                )
            ).all()
            equation_by_reaction = {eq.reaction_id: eq for eq in equation_rows}

        # When the user supplies a starting material, keep only records whose
        # reactant names or structures contain it. Equation sides are used as
        # a fallback because imported SciFinder records often have names only
        # in reaction_equations, not in the Reaction text columns.
        if starting_material:
            reactant_fields = (
                "reactants_text", "reactants_zh", "reactants_en", "reactant_smiles",
            )
            filtered_reactions = []
            for reaction in reactions:
                field_match = any(
                    _contains_value(getattr(reaction, field, None), starting_material)
                    for field in reactant_fields
                )
                equation = equation_by_reaction.get(reaction.id)
                equation_match = False
                if equation:
                    for equation_text in (equation.equation_zh, equation.equation):
                        reactant_side, _ = _equation_sides(equation_text)
                        if _contains_value(reactant_side, starting_material):
                            equation_match = True
                            break
                if field_match or equation_match:
                    filtered_reactions.append(reaction)
            reactions = filtered_reactions

        # 构建结果
        reaction_list = []
        scheme_map: dict[int, dict] = {}
        literature_sources: list[dict] = []
        literature_seen: set[str] = set()

        for r in reactions:
            scheme = session.get(Scheme, r.scheme_id) if r.scheme_id else None
            if scheme and scheme.id not in scheme_map:
                scheme_map[scheme.id] = {
                    "id": scheme.id,
                    "scheme_number": scheme.scheme_number,
                    "reaction_count": scheme.reaction_count,
                    "overall_yield": scheme.overall_yield,
                    "page_start": scheme.page_start,
                    "page_end": scheme.page_end,
                }

            # 获取文献
            lit = session.exec(
                select(Literature).where(Literature.reaction_id == r.id)
            ).first()

            if lit:
                lit_key = (lit.title or "").strip() + "|" + str(lit.year or "")
                if lit_key not in literature_seen:
                    literature_seen.add(lit_key)
                    literature_sources.append({
                        "title": lit.title,
                        "authors": lit.authors,
                        "journal": lit.journal,
                        "year": lit.year,
                        "volume": lit.volume,
                        "pages": lit.pages,
                        "doi": lit.doi,
                    })

            # 获取条件摘要
            conditions = session.exec(
                select(ReactionCondition).where(
                    ReactionCondition.reaction_id == r.id
                )
            ).all()

            # 方程式是许多导入记录中唯一保存名称和结构的字段。
            eq = equation_by_reaction.get(r.id)
            equation_zh = eq.equation_zh if eq else None
            equation = eq.equation if eq else None
            reactants_zh, products_zh = _equation_sides(equation_zh)
            reactants_smiles, products_smiles = _equation_sides(equation)

            reaction_list.append({
                "id": r.id,
                "scheme_id": r.scheme_id,
                "scheme_number": scheme.scheme_number if scheme else None,
                "source_page": r.page,
                **_source_details(r.raw_json),
                "literature_doi": lit.doi if lit else None,
                "cas_registry_id": r.cas_registry_id,
                "yield_": r.yield_,
                "steps": r.steps,
                "reactants_text": r.reactants_text or r.reactants_zh or r.reactants_en or reactants_zh or reactants_smiles or None,
                "products_text": r.products_text or r.products_zh or r.products_en or products_zh or products_smiles or None,
                "reactant_smiles": r.reactant_smiles,
                "product_smiles": r.product_smiles,
                "equation": equation,
                "equation_zh": equation_zh,
                "conditions_summary": [{
                    "step": c.step_number,
                    "reagents": c.reagents,
                    "catalysts": c.catalysts,
                    "solvents": c.solvents,
                    "temperature": c.temperature,
                    "time": c.time,
                    "other": c.other,
                } for c in conditions],
                "literature_title": lit.title if lit else None,
                "literature_journal": lit.journal if lit else None,
                "literature_year": lit.year if lit else None,
            })

    # 评分（按总分降序）
    scored = []
    if reaction_list:
        for r in reaction_list:
            try:
                s = score_reaction(r["id"])
                if "error" not in s:
                    scored.append(s)
            except Exception as exc:
                logger.debug("评分失败 reaction %d: %s", r["id"], exc)
        scored.sort(key=lambda x: x.get("total", 0.0), reverse=True)

    # 筛选条件匹配（可选）：按条件满足度 + 总分排序，取前 top_n 项
    filter_matches = None
    if filters and reaction_list:
        min_yield = filters.get("min_yield")
        max_steps = filters.get("max_steps")
        max_temperature = filters.get("max_temperature")
        max_time_hours = filters.get("max_time_hours")
        catalyst_pref = filters.get("catalyst")      # any / with / without
        workup_pref = filters.get("workup")          # any / with / without
        solvent_pref = filters.get("solvent")        # any / with / without
        catalyst_name = (filters.get("catalyst_name") or "").strip()
        solvent_name = (filters.get("solvent_name") or "").strip()
        top_n = filters.get("top_n") or 5

        active_conditions = sum(
            1 for v in (min_yield, max_steps, max_temperature, max_time_hours) if v is not None
        ) + sum(
            1 for p in (catalyst_pref, workup_pref, solvent_pref) if p not in (None, "any")
        ) + (1 if catalyst_name else 0) + (1 if solvent_name else 0)

        if active_conditions > 0:
            score_map = {s["reaction_id"]: s for s in scored}
            ranked: list[dict] = []

            for item in reaction_list:
                score = score_map.get(item["id"])
                ranked.append({
                    **item,
                    **evaluate_constraints(item, filters),
                    "score": score,
                    "_total": score["total"] if score else 0.0,
                })

            # 排序：先满足条件数，再总分
            ranked.sort(key=lambda x: (-x["matched_conditions"], -x["_total"], x["id"]))
            top_items = ranked[:top_n]
            for it in top_items:
                it.pop("_total", None)

            filter_matches = {
                "filters": {
                    "min_yield": min_yield,
                    "max_steps": max_steps,
                    "max_temperature": max_temperature,
                    "max_time_hours": max_time_hours,
                    "catalyst": catalyst_pref,
                    "workup": workup_pref,
                    "solvent": solvent_pref,
                    "catalyst_name": catalyst_name or None,
                    "solvent_name": solvent_name or None,
                    "top_n": top_n,
                },
                "total_exact": sum(1 for x in ranked if x["exact"]),
                "total_ranked": len(ranked),
                "items": top_items,
            }

    # 上下游推导：目标化合物作为产物 → 上游反应物；作为反应物 → 下游产物
    upstream: list[dict] = []
    downstream: list[dict] = []
    for r in reaction_list:
        products = r.get("products_text") or ""
        reactants = r.get("reactants_text") or ""
        product_matches = any(
            _contains_value(value, query)
            for value in (products, r.get("product_smiles"))
        )
        reactant_matches = any(
            _contains_value(value, query)
            for value in (reactants, r.get("reactant_smiles"))
        )
        if query and product_matches:
            upstream.append({
                "compound": reactants or "（未知原料）",
                "reaction": f"{reactants} → {products}" if reactants else f"→ {products}",
                "reaction_id": r["id"],
            })
        if query and reactant_matches:
            downstream.append({
                "compound": products or "（未知产物）",
                "reaction": f"{reactants} → {products}" if products else f"{reactants} →",
                "reaction_id": r["id"],
            })

    # LLM 分析（可选）
    answer = ""
    if reaction_list and not (os.getenv("DEEPSEEK_API_KEY") or "").strip():
        answer = "未配置模型密钥；已完成本地路线评分，可比较条件并导出记录草案。"
    elif reaction_list:
        try:
            answer = _generate_llm_response(query, reaction_list, scored, literature_sources)
        except Exception as exc:
            logger.warning("LLM 分析失败: %s", exc)
            answer = f"（AI 分析暂时不可用: {exc}）"

    return {
        "success": True,
        "query": query,
        "starting_material": starting_material or None,
        "compound": {
            "name": query,
            "query": query,
            "match_count": len(reaction_list),
        },
        "reactions": reaction_list,
        "schemes": list(scheme_map.values()),
        "literature": {
            "sources": literature_sources[:10],
            "total": len(literature_sources),
        },
        "upstream": upstream,
        "downstream": downstream,
        "scored": scored,
        "filter_matches": filter_matches,
        "answer": answer,
    }


def _generate_llm_response(
    query: str,
    reactions: list[dict],
    scored: list[dict],
    literature: Optional[list[dict]] = None,
) -> str:
    """调用 DeepSeek LLM 生成分析报告。"""
    llm = _get_llm()

    # 文献编号映射：标题 → 编号
    lit_index: dict[str, int] = {}
    if literature:
        for i, lit in enumerate(literature, 1):
            key = (lit.get("title") or "").strip()
            if key:
                lit_index[key] = i

    # 构建上下文
    context_parts = [f"## 搜索词: {query}", f"## 匹配反应数: {len(reactions)}"]

    for i, r in enumerate(reactions[:5], 1):
        lit_title = (r.get("literature_title") or "").strip()
        lit_ref = f"[{lit_index[lit_title]}]" if lit_title in lit_index else "无"
        context_parts.append(
            f"\n### 反应 {i}: {r.get('cas_registry_id', '未知')}\n"
            f"- 反应方程式: {r.get('equation_zh') or r.get('equation') or '未提供'}\n"
            f"- 反应物 SMILES: {r.get('reactant_smiles') or '未提供'}\n"
            f"- 产物 SMILES: {r.get('product_smiles') or '未提供'}\n"
            f"- 反应物: {r.get('reactants_text') or '未提供'}\n"
            f"- 产物: {r.get('products_text') or '未提供'}\n"
            f"- 收率: {r.get('yield_', '未知')}\n"
            f"- 步骤数: {r.get('steps', '未知')}\n"
            f"- 文献: {lit_ref}\n"
        )

        for cond in r.get("conditions_summary", []):
            parts = []
            if cond.get("catalysts"):
                parts.append(f"催化剂: {cond['catalysts']}")
            if cond.get("solvents"):
                parts.append(f"溶剂: {cond['solvents']}")
            if cond.get("temperature"):
                parts.append(f"温度: {cond['temperature']}")
            if cond.get("time"):
                parts.append(f"时间: {cond['time']}")
            if parts:
                context_parts.append(f"  条件 [{cond.get('step', '?')}]: {'; '.join(parts)}")

    if scored:
        context_parts.append("\n## 评分排名")
        for i, s in enumerate(scored[:5], 1):
            context_parts.append(
                f"  #{i} {s.get('cas_registry_id', '?')}: "
                f"总分={s['total']}/100 (收率={s['yield_score']}, "
                f"步骤={s['step_score']}, 温度={s['temp_score']}, "
                f"安全={s['safety_score']})"
            )

    if literature:
        context_parts.append("\n## 参考文献列表")
        for i, lit in enumerate(literature, 1):
            meta_parts = []
            for key in ("journal", "year", "volume", "pages"):
                v = lit.get(key)
                if v:
                    meta_parts.append(str(v))
            meta_str = f" ({', '.join(meta_parts)})" if meta_parts else ""
            authors = lit.get("authors")
            author_str = f" | {authors}" if authors else ""
            context_parts.append(
                f"  [{i}] {lit.get('title') or '无标题'}{author_str}{meta_str}"
            )

    context = "\n".join(context_parts)

    try:
        response = llm.chat.completions.create(
            model=os.getenv("LLM_MODEL", "deepseek-chat"),
            temperature=0.2,
            max_tokens=4096,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"{context}\n\n请分析上述化合物的合成路线，并在报告中按 [n] 编号引用参考文献。",
                },
            ],
        )
        return response.choices[0].message.content
    except Exception:
        return "（AI 分析生成失败，请查看下方数据库结果）"
