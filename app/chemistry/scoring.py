"""合成路线评分引擎 — 基于 reactions.db 新模型。

对化学反应进行多维度量化评估：
- 收率评分：解析 yield_ 字符串
- 步骤数评分：越少越好
- 条件温和度：温度和时间评估
- 安全性：危险试剂检查
"""

from __future__ import annotations

from typing import Optional

from sqlmodel import Session, select

from app.chemistry.models import Reaction, ReactionCondition
from app.database import chemistry_engine
from app.chemistry.constraints import peak_temperature, yield_range

# ---------------------------------------------------------------------------
# 危险试剂关键词
# ---------------------------------------------------------------------------

HAZARDOUS_REAGENTS = [
    "cyanide", "氰化", "azide", "叠氮", "phosgene", "光气",
    "mercury", "汞", "arsenic", "砷", "chromium", "铬",
    "diazomethane", "重氮甲烷", "dimethyl sulfate", "硫酸二甲酯",
    "hydrofluoric", "氢氟酸", "perchloric", "高氯酸",
    "sodium hydride", "氢化钠", "lithium aluminum hydride", "氢化铝锂",
    "n-butyllithium", "正丁基锂", "tert-butyllithium", "叔丁基锂",
    "dichloromethane", "carbon tetrachloride", "四氯化碳",
    "hexamethylphosphoramide", "hmpa",
]

# ---------------------------------------------------------------------------
# 收率解析
# ---------------------------------------------------------------------------

def _parse_yield(yield_str: Optional[str]) -> float:
    """解析收率字符串，返回 0-100 的数值。

    - "94%" → 94.0
    - "71-94%" → 82.5（取平均值）
    - None → 50.0（中性）
    """
    bounds = yield_range(yield_str)
    return sum(bounds) / 2 if bounds else 50.0


# ---------------------------------------------------------------------------
# 温度评估
# ---------------------------------------------------------------------------

def _score_temperature(temperature: Optional[str]) -> float:
    """评估温度温和度，返回 0-100。

    - rt/室温 → 100
    - reflux/回流 → 60
    - 0-50°C → 90
    - 50-100°C → 70
    - 100-150°C → 50
    - >150°C → 30
    - None → 70（中性）
    """
    if not temperature:
        return 70.0

    t = temperature.lower().strip()

    if t in {"rt", "r.t.", "室温", "常温", "room temperature", "ambient"}:
        return 100.0
    if any(kw in t for kw in ["reflux", "回流"]):
        return 60.0
    if any(kw in t for kw in ["ice", "冰", "cold", "低温", "冷冻"]):
        return 70.0
    peak = peak_temperature(t)
    if peak is not None:
        if peak <= 0:
            return 70.0
        if peak <= 50:
            return 90.0
        if peak <= 100:
            return 70.0
        if peak <= 150:
            return 50.0
        return 30.0

    return 70.0


# ---------------------------------------------------------------------------
# 安全性评估
# ---------------------------------------------------------------------------

def _score_safety(reagents: Optional[str]) -> float:
    """评估安全性，返回 0-100。

    检查是否包含危险试剂，每个危险试剂扣 20 分。
    """
    if not reagents:
        return 80.0
    text = reagents.lower()
    hazard_count = sum(1 for kw in HAZARDOUS_REAGENTS if kw.lower() in text)
    return max(0.0, 80.0 - hazard_count * 20.0)


# ---------------------------------------------------------------------------
# 主评分函数
# ---------------------------------------------------------------------------

def score_reaction(reaction_id: int) -> dict:
    """对单个反应进行多维度评分。

    Returns
    -------
    dict
        {"reaction_id": int, "yield_score": float, "step_score": float,
         "temp_score": float, "safety_score": float, "total": float}
    """
    with Session(chemistry_engine) as session:
        reaction = session.get(Reaction, reaction_id)
        if not reaction:
            return {"error": f"Reaction {reaction_id} not found"}

        # 获取条件
        conditions = session.exec(
            select(ReactionCondition).where(
                ReactionCondition.reaction_id == reaction_id
            )
        ).all()

        # 1. 收率评分
        yield_val = _parse_yield(reaction.yield_)

        # 2. 步骤数评分（1步=100, 每多一步-15）
        steps = reaction.steps or 1
        step_score = max(0.0, 100.0 - (steps - 1) * 15.0)

        # 3. 温度评分（取所有条件中最严格的）
        temp_scores = [_score_temperature(c.temperature) for c in conditions]
        temp_score = min(temp_scores) if temp_scores else 70.0

        # 4. 安全性评分
        all_reagents = " ".join(
            (c.reagents or "") + " " + (c.catalysts or "") + " " + (c.solvents or "")
            for c in conditions
        )
        safety_score = _score_safety(all_reagents)

        # 加权总分
        dimensions = [
            ("收率", 35, yield_val,
             f"记录 {reaction.yield_}；范围取中点" if yield_range(reaction.yield_) else "无可解析收率，暂按 50 分"),
            ("步骤", 15, step_score,
             f"{steps} 步；每多一步扣 15 分" if reaction.steps else "步骤未记录，暂按一步计 100 分"),
            ("温度", 20, temp_score,
             "各条件取最低分。数值温度 ≤0 / ≤50 / ≤100 / ≤150 / >150 °C 依次计 70 / 90 / 70 / 50 / 30 分；室温 100，回流 60，低温描述、缺失或未识别 70。记录：" +
             ("；".join(c.temperature or "未记录" for c in conditions) or "未记录")),
            ("试剂风险", 30, safety_score,
             "仅筛查试剂、催化剂和溶剂关键词，每次命中扣 20 分；" +
             ("命中：" + "、".join(k for k in HAZARDOUS_REAGENTS if k in all_reagents.lower())
              if safety_score < 80 else ("未命中，按基准 80 分" if all_reagents.strip() else "无试剂记录，按基准 80 分"))),
        ]
        total = sum(weight * value / 100 for _, weight, value, _ in dimensions)


    return {
        "reaction_id": reaction_id,
        "cas_registry_id": reaction.cas_registry_id,
        "yield_raw": reaction.yield_,
        "dimensions": [{"label": label, "weight": weight, "score": round(value, 1), "basis": basis}
                       for label, weight, value, basis in dimensions],
        "yield_score": round(yield_val, 1),
        "step_score": round(step_score, 1),
        "temp_score": round(temp_score, 1),
        "safety_score": round(safety_score, 1),
        "total": round(total, 1),
    }


def score_reactions_batch(
    reaction_ids: Optional[list[int]] = None,
    limit: int = 50,
) -> list[dict]:
    """批量评分并排序。

    Parameters
    ----------
    reaction_ids : list[int] or None
        指定要评分的反应 ID 列表，None 则评分所有。
    limit : int
        返回数量上限。

    Returns
    -------
    list[dict]
        按总分降序排列的评分结果。
    """
    with Session(chemistry_engine) as session:
        if reaction_ids:
            reactions = session.exec(
                select(Reaction).where(Reaction.id.in_(reaction_ids)).limit(limit)
            ).all()
        else:
            reactions = session.exec(
                select(Reaction).limit(limit)
            ).all()

    results = []
    for r in reactions:
        score = score_reaction(r.id)
        if "error" not in score:
            results.append(score)

    results.sort(key=lambda x: x["total"], reverse=True)
    return results


def format_scored(results: list[dict]) -> str:
    """格式化评分结果为文本。"""
    if not results:
        return "（无评分数据）"

    lines = [f"## 反应评分结果（共 {len(results)} 条）\n"]
    for i, r in enumerate(results[:10], 1):
        lines.append(
            f"### #{i} {r.get('cas_registry_id', '未知')} — "
            f"{r['total']:.1f} 分\n"
            f"- 收率: {r['yield_score']:.0f}/100 | "
            f"步骤: {r['step_score']:.0f}/100 | "
            f"温度: {r['temp_score']:.0f}/100 | "
            f"安全: {r['safety_score']:.0f}/100"
        )

    return "\n".join(lines)
