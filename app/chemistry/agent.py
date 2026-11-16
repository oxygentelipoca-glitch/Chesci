"""AI 实验方案生成模块。

基于化合物信息、反应路线和文献数据，调用 LLM 生成结构化的化学实验方案。

输出格式
--------
生成的实验方案包含以下章节：

1. 目标产物 — 名称、CAS、分子式、分子量
2. 反应类型 — 反应名称和分类
3. 反应物与摩尔比例 — 主反应物、试剂及其用量
4. 催化剂 — 名称、用量
5. 溶剂 — 名称、用量
6. 温度 — 反应温度和控温方式
7. 时间 — 反应时间和监控方法
8. 后处理 — 淬灭、萃取、干燥、纯化步骤
9. 注意事项 — 安全提醒和操作要点
10. 参考文献 — 引用来源
"""

from __future__ import annotations

import logging
import os
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# LLM 客户端（独立实例，不依赖 chemistry_service）
# ---------------------------------------------------------------------------

_client: OpenAI | None = None


def _get_llm() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=os.getenv("DEEPSEEK_API_KEY", "sk-placeholder"),
            base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        )
    return _client


# ---------------------------------------------------------------------------
# System Prompt
# ---------------------------------------------------------------------------

EXPERIMENT_SYSTEM_PROMPT = """你是一位资深的有机合成化学家，擅长撰写标准化的化学实验方案。

## 任务

根据提供的化合物信息、反应路线和文献证据，生成一份供专业人员审阅的实验方案草案。

## 输出格式

请严格按照以下 Markdown 结构输出：

### 实验方案：{目标产物}

#### 1. 目标产物
| 项目 | 内容 |
|------|------|
| 化合物名称 | ... |
| CAS 号 | ... |
| 分子式 | ... |
| 分子量 | ... |

#### 2. 反应类型
- 反应名称：...
- 反应分类：...

#### 3. 反应物与摩尔比例
| 反应物 | 分子量 | 用量 | 摩尔数 | 摩尔比 |
|--------|--------|------|--------|--------|
| ... | ... | ... | ... | ... |

#### 4. 催化剂
- 名称：...
- 用量：...

#### 5. 溶剂
- 名称：...
- 用量：...

#### 6. 反应条件
- 温度：...
- 时间：...
- 气氛：...（如氮气保护）

#### 7. 实验步骤
1. ...
2. ...
3. ...

#### 8. 后处理
- 淬灭：...
- 萃取：...
- 干燥：...
- 纯化：...

#### 9. 注意事项
- 安全提醒：...
- 操作要点：...

#### 10. 参考文献
- [1] ...

## 规则

- 只把提供资料中明确出现的信息作为事实；资料不足时标注「资料未提供，需核实」
- 不要猜测投料量、摩尔比、具体后处理步骤或实验条件；缺少依据时明确留空/待核实
- 安全提醒仅基于已提供的试剂和资料；不确定时提示查阅对应安全数据表
- 将证据支持的步骤与模型整理性文字区分开，并在相关内容附近列出来源
- 输出是研究草案，必须由具备资质的人员结合原始文献、实验室规范和风险评估审核
- 如果提供了多条路线，默认选择评分最高的路线生成方案
"""


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def generate_experiment_plan(
    compound: dict,
    route: dict | None = None,
    literature_context: str = "",
    extra_instructions: str = "",
) -> dict[str, Any]:
    """生成结构化实验方案。

    Parameters
    ----------
    compound : dict
        化合物信息（来自 parser 或 chemistry_service）。
    route : dict or None
        选定的合成路线（含 name, equation, catalyst, solvent, temperature,
        time, yield 等字段）。为 None 时基于全部可用数据生成。
    literature_context : str
        RAG 检索到的文献上下文文本。
    extra_instructions : str
        用户额外指令（如「放大到 100g 规模」「注重绿色化学」）。

    Returns
    -------
    dict
        ``{"plan": str, "compound": dict, "route": dict}``
    """
    # 构建上下文
    parts = [
        f"## 目标化合物",
        f"名称: {compound.get('name', '未知')}",
        f"CAS: {compound.get('cas', '未知')}",
        f"分子式: {compound.get('molecular_formula', '未知')}",
        f"分子量: {compound.get('molecular_weight', '未知')}",
        f"分类: {compound.get('compound_class', '未知')}",
        f"描述: {compound.get('description', '无')}",
    ]

    if route:
        parts.append(f"\n## 选定的合成路线")
        parts.append(f"路线名称: {route.get('name', '未命名')}")
        parts.append(f"反应类型: {route.get('type', '未知')}")
        parts.append(f"反应方程式: {route.get('equation', '未知')}")
        parts.append(f"催化剂: {route.get('catalyst', '需实验确定')}")
        parts.append(f"溶剂: {route.get('solvent', '需实验确定')}")
        parts.append(f"温度: {route.get('temperature', '需实验确定')}")
        parts.append(f"时间: {route.get('time', '需实验确定')}")
        parts.append(f"收率: {route.get('yield', '未知')}%")

        # 评分信息
        if any(k in route for k in ('difficulty', 'safety', 'eco', 'cost')):
            parts.append(
                f"评分: 难度={route.get('difficulty', '?')}/10 "
                f"安全={route.get('safety', '?')}/10 "
                f"环保={route.get('eco', '?')}/10 "
                f"成本={route.get('cost', '?')}/10"
            )

    if literature_context:
        parts.append(f"\n## 参考文献资料\n{literature_context}")

    if extra_instructions:
        parts.append(f"\n## 用户特别要求\n{extra_instructions}")

    context = "\n".join(parts)
    target_name = compound.get("name", "目标化合物")

    # 调用 LLM
    error = None
    try:
        llm = _get_llm()
        response = llm.chat.completions.create(
            model=os.getenv("LLM_MODEL", "deepseek-chat"),
            temperature=0.2,
            max_tokens=3000,
            messages=[
                {"role": "system", "content": EXPERIMENT_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"{context}\n\n"
                        f"请为 {target_name} 生成一份完整的实验方案。"
                    ),
                },
            ],
        )
        plan = response.choices[0].message.content or ""
    except Exception as exc:
        logger.error("实验方案生成失败: %s", exc)
        plan = ""
        error = "模型服务暂不可用，请检查服务配置后重试。"

    return {
        "plan": plan,
        "error": error,
        "compound": compound,
        "route": route,
    }


# ---------------------------------------------------------------------------
# 批量方案生成
# ---------------------------------------------------------------------------

def generate_plans_for_routes(
    compound: dict,
    routes: list[dict],
    literature_context: str = "",
    top_n: int = 2,
) -> list[dict[str, Any]]:
    """为排名前 N 的路线各生成一份实验方案。

    Parameters
    ----------
    compound : dict
        目标化合物信息。
    routes : list[dict]
        路线列表（通常已按评分排序）。
    literature_context : str
        文献上下文。
    top_n : int
        为前 N 条路线生成方案。

    Returns
    -------
    list[dict]
        每份方案包含 ``plan``, ``compound``, ``route``。
    """
    plans = []
    for route in routes[:top_n]:
        logger.info("生成方案: %s → %s", compound.get("name"), route.get("name"))
        plan = generate_experiment_plan(
            compound=compound,
            route=route,
            literature_context=literature_context,
        )
        plans.append(plan)
    return plans
