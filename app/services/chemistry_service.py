"""化学合成分析服务 — 基于 reactions.db 的查询与 LLM 分析。

入口函数 analyze_target：搜索反应数据库 + 可选的 DeepSeek LLM 分析。
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

from dotenv import load_dotenv
from openai import OpenAI
from sqlalchemy import or_
from sqlmodel import Session, select

from app.chemistry.models import Reaction, Scheme, Literature, ReactionCondition, ReactionEquation
from app.chemistry.scoring import (
    score_reaction,
    extract_temperature_celsius,
    has_workup,
    extract_time_hours,
    _parse_yield,
)
from app.database import chemistry_engine

load_dotenv()
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# LLM 客户端
# ---------------------------------------------------------------------------

_client: Optional[OpenAI] = None


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

        # When the user supplies a starting material, keep only records whose
        # reactant names or structures contain it. The match is intentionally
        # transparent substring matching; it is not a graph/path prediction.
        if starting_material:
            source_key = starting_material.casefold()
            reactant_fields = (
                "reactants_text", "reactants_zh", "reactants_en", "reactant_smiles",
            )
            reactions = [
                reaction for reaction in reactions
                if any(
                    source_key in (getattr(reaction, field, None) or "").casefold()
                    for field in reactant_fields
                )
            ]

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

            # 获取方程式（reaction_equations 表）
            eq = session.exec(
                select(ReactionEquation).where(
                    ReactionEquation.reaction_id == r.id
                )
            ).first()

            reaction_list.append({
                "id": r.id,
                "scheme_id": r.scheme_id,
                "cas_registry_id": r.cas_registry_id,
                "yield_": r.yield_,
                "steps": r.steps,
                "reactants_text": r.reactants_text,
                "products_text": r.products_text,
                "reactant_smiles": r.reactant_smiles,
                "product_smiles": r.product_smiles,
                "equation": eq.equation if eq else None,
                "equation_zh": eq.equation_zh if eq else None,
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
                conds = item.get("conditions_summary") or []

                # 提取各维度的实际值
                yield_val = _parse_yield(item.get("yield_"))
                steps_val = item.get("steps") or 1
                temp_vals = [
                    extract_temperature_celsius(c.get("temperature"))
                    for c in conds
                ]
                temp_vals = [v for v in temp_vals if v is not None]
                temp_val = max(temp_vals) if temp_vals else None
                time_vals = [extract_time_hours(c.get("time")) for c in conds]
                time_vals = [v for v in time_vals if v is not None]
                time_val = max(time_vals) if time_vals else None
                catalyst_val = any((c.get("catalysts") or "").strip() for c in conds)
                solvent_val = any((c.get("solvents") or "").strip() for c in conds)
                workup_val = any(has_workup(c.get("other")) for c in conds)

                # 合并所有条件的催化剂/溶剂名称（供展示与关键词匹配）
                catalyst_text = "; ".join(
                    (c.get("catalysts") or "").strip()
                    for c in conds
                    if (c.get("catalysts") or "").strip()
                )
                solvent_text = "; ".join(
                    (c.get("solvents") or "").strip()
                    for c in conds
                    if (c.get("solvents") or "").strip()
                )

                # 各条件满足判定（仅对激活的条件计数）
                matched = 0
                if min_yield is not None:
                    matched += int(yield_val >= min_yield)
                if max_steps is not None:
                    matched += int(steps_val <= max_steps)
                if max_temperature is not None:
                    matched += int(temp_val is not None and temp_val <= max_temperature)
                if max_time_hours is not None:
                    matched += int(time_val is not None and time_val <= max_time_hours)
                if catalyst_pref not in (None, "any"):
                    matched += int((catalyst_pref == "with") == catalyst_val)
                if workup_pref not in (None, "any"):
                    matched += int((workup_pref == "with") == workup_val)
                if solvent_pref not in (None, "any"):
                    matched += int((solvent_pref == "with") == solvent_val)
                if catalyst_name:
                    matched += int(catalyst_name.lower() in catalyst_text.lower())
                if solvent_name:
                    matched += int(solvent_name.lower() in solvent_text.lower())
                score = score_map.get(item["id"])

                ranked.append({
                    **item,
                    "yield_val": round(yield_val, 1),
                    "steps_val": steps_val,
                    "temp_val": round(temp_val, 1) if temp_val is not None else None,
                    "time_val": round(time_val, 2) if time_val is not None else None,
                    "catalyst_val": catalyst_val,
                    "workup_val": workup_val,
                    "solvent_val": solvent_val,
                    "catalyst_names": catalyst_text,
                    "solvent_names": solvent_text,
                    "matched_conditions": matched,
                    "exact": matched == active_conditions,
                    "score": score,
                    "_total": score["total"] if score else 0.0,
                })

            # 排序：先满足条件数，再总分
            ranked.sort(key=lambda x: (-x["matched_conditions"], -x["_total"]))
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
        if query and query.lower() in products.lower():
            upstream.append({
                "compound": reactants or "（未知原料）",
                "reaction": f"{reactants} → {products}" if reactants else f"→ {products}",
                "reaction_id": r["id"],
            })
        if query and query.lower() in reactants.lower():
            downstream.append({
                "compound": products or "（未知产物）",
                "reaction": f"{reactants} → {products}" if products else f"{reactants} →",
                "reaction_id": r["id"],
            })

    # LLM 分析（可选）
    answer = ""
    if reaction_list:
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
        "scored": scored[:10],
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
