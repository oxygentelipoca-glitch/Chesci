"""合成路线评分引擎 — 基于 reactions.db 新模型。

对化学反应进行多维度量化评估：
- 收率评分：解析 yield_ 字符串
- 步骤数评分：越少越好
- 条件温和度：温度和时间评估
- 安全性：危险试剂检查
"""

from __future__ import annotations

import re
from typing import Optional

from sqlmodel import Session, select

from app.chemistry.models import Reaction, ReactionCondition
from app.database import chemistry_engine

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
    if not yield_str:
        return 50.0
    # 提取所有数字
    nums = re.findall(r"(\d+\.?\d*)", yield_str)
    if not nums:
        return 50.0
    values = [float(n) for n in nums if 0 < float(n) <= 100]
    if not values:
        return 50.0
    return sum(values) / len(values)


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

    if any(kw in t for kw in ["rt", "室温", "常温", "room temp", "ambient"]):
        return 100.0
    if any(kw in t for kw in ["reflux", "回流"]):
        return 60.0
    if any(kw in t for kw in ["ice", "冰", "0°c", "0 ℃", "cold", "低温", "冷冻"]):
        return 70.0  # 低温可控但需要特殊设备

    # 提取温度数值
    nums = re.findall(r"(\d+\.?\d*)", t)
    values = [float(n) for n in nums if float(n) < 1000]
    if values:
        avg_temp = sum(values) / len(values)
        if avg_temp <= 50:
            return 90.0
        if avg_temp <= 100:
            return 70.0
        if avg_temp <= 150:
            return 50.0
        return 30.0

    return 70.0


def extract_temperature_celsius(temperature: Optional[str]) -> Optional[float]:
    """从温度文本提取摄氏温度数值（用于筛选比较）。

    - "85 °C" → 85.0
    - "85 °C → rt" → 85.0（取最高值，最严格条件）
    - "rt" / "室温" → 25.0
    - "reflux" / 无法解析 → None（无法量化）
    """
    if not temperature:
        return None
    t = temperature.lower().strip()
    nums = [float(n) for n in re.findall(r"(\d+\.?\d*)", t) if float(n) < 1000]
    if nums:
        return max(nums)
    if any(kw in t for kw in ["rt", "室温", "常温", "room temp", "ambient"]):
        return 25.0
    return None


# 后处理操作关键词（other 字段描述）
_WORKUP_KEYWORDS = [
    "neutralized", "acidified", "cooled", "washed", "filtered",
    "extracted", "dried", "quenched", "recrystallized", "crystallized",
    "concentrated", "evaporated", "purified", "distilled",
]


def has_workup(other_text: Optional[str]) -> bool:
    """判断条件描述（other 字段）是否包含后处理操作。

    - "neutralized, cooled" → True
    - "pH 3" → True（pH 调整属于后处理）
    - "heated" → False（加热属于反应条件，不算后处理）
    """
    if not other_text:
        return False
    t = other_text.lower()
    if re.search(r"\bph\b", t):
        return True
    return any(kw in t for kw in _WORKUP_KEYWORDS)


def extract_time_hours(time_text: Optional[str]) -> Optional[float]:
    """从时间文本提取小时数（多段取最大值）。

    - "2 h" → 2.0
    - "15 min" → 0.25
    - "8 h; 2 h" → 8.0（取最长）
    - "3 - 4 h" → 4.0
    - 无法解析 → None
    """
    if not time_text:
        return None
    t = time_text.lower().strip()
    values: list[float] = []
    pattern = re.compile(r"(\d+\.?\d*)\s*(h|hr|hrs|hour|hours|min|minute|minutes|d|day|days)")
    for m in pattern.finditer(t):
        val = float(m.group(1))
        unit = m.group(2)
        if unit.startswith("h"):
            values.append(val)
        elif unit.startswith("m"):
            values.append(val / 60.0)
        elif unit.startswith("d"):
            values.append(val * 24.0)
    return max(values) if values else None


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
        total = (
            yield_val * 0.35 +
            step_score * 0.15 +
            temp_score * 0.20 +
            safety_score * 0.30
        )

    return {
        "reaction_id": reaction_id,
        "cas_registry_id": reaction.cas_registry_id,
        "yield_raw": reaction.yield_,
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
