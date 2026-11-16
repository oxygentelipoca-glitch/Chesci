#!/usr/bin/env python3
"""SciFinder PDF 反应数据提取 — 基于 DeepSeek LLM。

与旧版正则脚本不同，本脚本将 SciFinder PDF 文本直接发送给 DeepSeek 大模型，
利用 LLM 的语义理解能力提取结构化反应数据，解决正则对扭曲文本脆弱的问题。

用法
----
    # 基本用法：提取并输出 JSON
    python scripts/extract_scifinder_llm.py documents/Reaction_20260811_1355.pdf

    # 限制处理数量（快速测试）
    python scripts/extract_scifinder_llm.py documents/Reaction_20260811_1355.pdf --max-schemes 5

    # 提取并导入数据库
    python scripts/extract_scifinder_llm.py documents/Reaction_20260811_1355.pdf --import-db

    # 指定输出文件
    python scripts/extract_scifinder_llm.py documents/Reaction_20260811_1355.pdf -o result.json

环境变量
--------
    DEEPSEEK_API_KEY     DeepSeek API 密钥（必需）
    DEEPSEEK_BASE_URL    API 地址（默认 https://api.deepseek.com）
    LLM_MODEL            模型名称（默认 deepseek-chat）

依赖
----
    pip install pdfplumber openai python-dotenv
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# 环境与日志
# ---------------------------------------------------------------------------

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("scifinder_llm")

# ---------------------------------------------------------------------------
# PDF 文本提取与清理
# ---------------------------------------------------------------------------


def extract_text_from_pdf(pdf_path: str) -> str:
    """用 pdfplumber 提取 PDF 全文。"""
    try:
        import pdfplumber
    except ImportError:
        logger.error("pdfplumber 未安装，请执行: pip install pdfplumber")
        sys.exit(1)

    with pdfplumber.open(pdf_path) as pdf:
        raw = ""
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                raw += text + "\n"
    return raw


def dedup_sci_finder_text(text: str) -> str:
    """修复 SciFinder PDF 的字符重复问题。

    SciFinder 导出的 PDF 中，字母常被重复一次：
        CAS → CCAASS, Yield → YYiieelldd, Scheme → SScchheemmee
    本函数将连续相同字符（非空白/标点）合并为一个。
    """
    # 需要保留重复的标点符号
    KEEP_DUP = set(" \n\t\r,;:.()[]{}<>!?\"'|=+-*/\\@#$%^&_~")

    result: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        result.append(ch)
        # 如果下一个字符相同且不属于保留集，跳过一个
        if i + 1 < n and text[i + 1] == ch and ch not in KEEP_DUP:
            i += 1  # skip duplicate
        i += 1
    return "".join(result)


def split_into_schemes(text: str) -> list[tuple[int, str]]:
    """按 Scheme N 分块，返回 [(编号, 文本块), ...]"""
    # 匹配 Scheme 后面跟数字
    blocks = re.split(r"(Scheme\s+\d+)", text)

    schemes: list[tuple[int, str]] = []
    for i in range(1, len(blocks) - 1, 2):
        header = blocks[i]
        body = blocks[i + 1] if i + 1 < len(blocks) else ""
        num_match = re.search(r"(\d+)", header)
        if num_match:
            num = int(num_match.group(1))
            schemes.append((num, body))

    return schemes


# ---------------------------------------------------------------------------
# DeepSeek API 客户端
# ---------------------------------------------------------------------------


def _get_client():
    """懒加载 DeepSeek 客户端。"""
    from openai import OpenAI

    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        logger.error("未设置 DEEPSEEK_API_KEY 环境变量")
        sys.exit(1)

    return OpenAI(
        api_key=api_key,
        base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
    )


# ---------------------------------------------------------------------------
# System Prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """你是一名专业的化学信息学数据库工程师。

你的任务是从 SciFinder 导出的反应 PDF 文本中提取结构化化学反应数据，将非结构化内容转换为标准 JSON。

## 解析原则

1. **不允许猜测。** PDF 中没有明确提供的信息，返回空字符串 "" 或空数组 []。禁止根据化学常识补全。
2. **保留原始信息。** 不要修改化学名称。例如 PDF 写 "Bismuth trichloride"，输出 "Bismuth trichloride"，不要改成 "BiCl3"。
3. **一个 Reaction 对应一个 JSON 对象。** 如果文本中存在多个 Reaction，必须分别输出多个 JSON。
4. **只返回 JSON，不输出任何解释文字、分析过程或 Markdown。**

## 需要提取字段

每个 reaction 输出以下 JSON 结构：

```json
{
    "reaction_id": "",
    "title": "",
    "authors": "",
    "source": "",
    "reactants": [],
    "products": [],
    "reaction_type": "",
    "yield": "",
    "conditions": {
        "reagents": [],
        "catalysts": [],
        "solvents": [],
        "temperature": "",
        "time": "",
        "pressure": "",
        "ph": "",
        "atmosphere": ""
    },
    "procedure": "",
    "workup": "",
    "purification": ""
}
```

### 字段定义

- **reaction_id**: SciFinder Reaction ID，如果不存在则为 ""
- **title**: 反应标题，通常位于 Reaction name 或文献标题附近
- **authors**: 作者
- **source**: 文献来源（Journal、Patent、Year、DOI）
- **reactants**: 反应物数组，例如 ["benzaldehyde", "malonic acid"]。不要加入 catalyst、solvent、reagent
- **products**: 生成物数组，例如 ["cinnamic acid"]
- **reaction_type**: 反应类型
- **yield**: 产率，保持原格式如 "85%"
- **conditions.reagents**: 参与反应的试剂
- **conditions.catalysts**: 催化剂
- **conditions.solvents**: 溶剂
- **conditions.temperature**: 温度，如 "80 °C"
- **conditions.time**: 时间，如 "3 h"
- **conditions.pressure**: 压力，如 "1 atm"
- **conditions.ph**: pH 值
- **conditions.atmosphere**: 气氛，如 "N2 atmosphere"
- **procedure**: 完整实验步骤（加料顺序、搅拌、加热、反应时间、后处理），不要总结
- **workup**: 后处理（萃取、洗涤、干燥、浓缩）
- **purification**: 纯化方法（柱层析、重结晶、蒸馏）

### PDF 解析注意事项

- SciFinder PDF 可能包含 Reaction Summary 页面、Experimental Details 页面和 Literature Reference 页面，需要将同一个 Reaction 的信息合并
- 不要把 Reaction Summary 和 Experimental Protocol 认为是两个反应
- 如果文本包含多个 Reaction，输出格式为 `{"reactions": [{...}, {...}]}`
- 如果只有一个 Reaction，也使用 `{"reactions": [{...}]}` 格式

### 质量检查

输出前确认：
1. reactant 和 product 不为空（如果是则设为 []）
2. condition 数据来自 PDF
3. 没有添加不存在的信息
4. 化学名称保持原样
5. JSON 格式合法
"""


# ---------------------------------------------------------------------------
# LLM 提取
# ---------------------------------------------------------------------------


def extract_scheme_with_llm(
    client,
    scheme_num: int,
    scheme_text: str,
    model: str,
    max_retries: int = 2,
) -> list[dict[str, Any]] | None:
    """调用 LLM 从单个 Scheme 文本中提取结构化反应数据（返回 reactions 列表）。"""
    # 预估反应数量（决定 token 分配和文本截断策略）
    rc_match = re.search(r"\((\d+)\s*Reactions?\)", scheme_text, re.I)
    reaction_count = int(rc_match.group(1)) if rc_match else 1

    # 动态调整文本长度和 token 配额
    # DeepSeek 输出上限 8192 tokens → 超大 Scheme 需分块
    CHUNK_THRESHOLD = 70  # 超过此数量分两次提取

    if reaction_count > CHUNK_THRESHOLD:
        # 分两半提取，避免超出 8192 token 输出限制
        mid = len(scheme_text) // 2
        # 尽量在行边界分割
        nl = scheme_text.rfind("\n", 0, mid)
        if nl > mid // 2:
            mid = nl
        half1 = scheme_text[:mid]
        half2 = scheme_text[mid:]

        logger.info(
            "  Scheme %d: %d reactions → 分块提取 (chunk1=%d, chunk2=%d chars)",
            scheme_num, reaction_count, len(half1), len(half2),
        )

        results1 = _call_llm(client, model, scheme_num, half1, 8000, "（第 1 部分）", max_retries)
        time.sleep(0.3)
        results2 = _call_llm(client, model, scheme_num, half2, 8000, "（第 2 部分）", max_retries)

        if results1 and results2:
            return results1 + results2
        elif results1:
            return results1
        else:
            return results2

    # 常规提取（不超阈值）
    if reaction_count > 30:
        MAX_TEXT_LEN = 20000
        max_tokens = 12000
        hint = f"此 Scheme 包含 {reaction_count} 个反应，请逐个列出。"
    elif reaction_count > 10:
        MAX_TEXT_LEN = 15000
        max_tokens = 10000
        hint = f"此 Scheme 包含 {reaction_count} 个反应，请逐个列出。"
    else:
        MAX_TEXT_LEN = 12000
        max_tokens = 8000
        hint = ""

    if len(scheme_text) > MAX_TEXT_LEN:
        scheme_text = scheme_text[:MAX_TEXT_LEN] + "\n...(truncated)"

    return _call_llm(
        client, model, scheme_num, scheme_text, max_tokens,
        hint, max_retries,
    )


def _call_llm(
    client,
    model: str,
    scheme_num: int,
    text: str,
    max_tokens: int,
    hint: str,
    max_retries: int = 2,
) -> list[dict[str, Any]] | None:
    """单次 LLM 调用，含重试。"""
    user_prompt = (
        f"请从以下 SciFinder Scheme {scheme_num} 的文本 {hint} 中提取所有化学反应数据，"
        f"以 {{\"reactions\": [...]}} JSON 格式返回。\n\n{text}"
    )

    for attempt in range(max_retries + 1):
        try:
            response = client.chat.completions.create(
                model=model,
                temperature=0.1,
                max_tokens=max_tokens,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content or ""
            return _parse_reactions_response(content, scheme_num)

        except Exception as exc:
            logger.warning(
                "Scheme %d API 调用失败 (attempt %d/%d): %s",
                scheme_num, attempt + 1, max_retries + 1, exc,
            )
            if attempt < max_retries:
                time.sleep(2 ** attempt)
            else:
                logger.error("Scheme %d 最终失败，跳过", scheme_num)
                return None


def _parse_reactions_response(content: str, scheme_num: int) -> list[dict[str, Any]] | None:
    """解析 LLM 返回的 {"reactions": [...]} JSON，提取 reactions 数组。"""
    parsed: dict[str, Any] | None = None

    # 尝试直接解析
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        pass

    # 尝试从 markdown 代码块中提取
    if parsed is None:
        json_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", content)
        if json_match:
            try:
                parsed = json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

    # 尝试找到第一个 { 到最后一个 }
    if parsed is None:
        brace_start = content.find("{")
        brace_end = content.rfind("}")
        if brace_start >= 0 and brace_end > brace_start:
            try:
                parsed = json.loads(content[brace_start : brace_end + 1])
            except json.JSONDecodeError:
                pass

    if parsed is None:
        logger.warning("Scheme %d: 无法解析 JSON 响应，前 200 字符: %s", scheme_num, content[:200])
        return None

    # 提取 reactions 数组
    reactions = parsed.get("reactions")
    if isinstance(reactions, list):
        # 为每个 reaction 打上 scheme_num 标记
        for r in reactions:
            r.setdefault("_scheme_num", scheme_num)
        return reactions

    # 兼容旧格式：单个 reaction 对象
    if isinstance(parsed, dict) and "reaction_id" in parsed:
        parsed.setdefault("_scheme_num", scheme_num)
        return [parsed]

    logger.warning("Scheme %d: JSON 中未找到 reactions 数组", scheme_num)
    return None


# ---------------------------------------------------------------------------
# 快速正则预提取（fallback + 辅助）
# ---------------------------------------------------------------------------


def quick_extract_overview(text: str) -> dict[str, Any]:
    """用正则快速提取 Scheme 概览信息，作为 LLM 的补充。"""
    overview: dict[str, Any] = {}

    # 反应数量
    m = re.search(r"\((\d+)\s*Reactions?\)", text, re.I)
    if m:
        overview["reaction_count"] = int(m.group(1))

    # 步骤数
    m = re.search(r"Steps?:?\s*(\d+)", text, re.I)
    if m:
        overview["steps"] = int(m.group(1))

    # 收率
    m = re.search(r"Yield[s]?:?\s*(\d+)\s*[-–—]\s*(\d+)\s*%", text, re.I)
    if m:
        overview["yield_min"] = int(m.group(1))
        overview["yield_max"] = int(m.group(2))
    else:
        m = re.search(r"Yield[s]?:?\s*(\d+)\s*%", text, re.I)
        if m:
            val = int(m.group(1))
            overview["yield_min"] = val
            overview["yield_max"] = val

    return overview


# ---------------------------------------------------------------------------
# 数据库导入
# ---------------------------------------------------------------------------


def import_to_database(
    reactions: list[dict[str, Any]],
    scheme_overviews: dict[int, dict[str, Any]],
    pdf_path: str,
) -> tuple[int, int]:
    """将提取结果导入 ChemRoute 数据库（Scheme + ReactionRecord 父子结构）。"""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from sqlmodel import Session
    from app.database import engine
    from app.chemistry.models import Scheme, ReactionRecord

    added_s = 0
    added_r = 0

    # 按 _scheme_num 分组
    groups: dict[int, list[dict[str, Any]]] = {}
    for r in reactions:
        sn = r.get("_scheme_num", 0)
        groups.setdefault(sn, []).append(r)

    with Session(engine) as session:
        for scheme_num, recs in sorted(groups.items()):
            overview = scheme_overviews.get(scheme_num, {})

            # 创建 Scheme（父级）
            scheme = Scheme(
                scheme_num=scheme_num,
                title=(recs[0].get("title", "") or f"Scheme {scheme_num}")[:500],
                reaction_count=overview.get("reaction_count", len(recs)),
                steps=overview.get("steps"),
                yield_min=float(overview["yield_min"]) if overview.get("yield_min") is not None else None,
                yield_max=float(overview["yield_max"]) if overview.get("yield_max") is not None else None,
                source="scifinder_llm",
                pdf_path=pdf_path,
            )
            session.add(scheme)
            session.flush()
            added_s += 1

            # 创建 ReactionRecord（子级）
            for r in recs:
                cond = r.get("conditions") or {}

                # 解析 yield
                yield_str = r.get("yield", "")
                yield_val = None
                if yield_str:
                    m = re.search(r"(\d+(?:\.\d+)?)", str(yield_str))
                    if m:
                        yield_val = float(m.group(1))

                rec = ReactionRecord(
                    scheme_id=scheme.id,
                    reaction_id=r.get("reaction_id") or None,
                    title=r.get("title") or None,
                    authors=r.get("authors") or None,
                    source=r.get("source") or None,
                    reaction_type=r.get("reaction_type") or None,
                    reactants=json.dumps(r.get("reactants") or []) if r.get("reactants") else None,
                    products=json.dumps(r.get("products") or []) if r.get("products") else None,
                    yield_text=yield_str or None,
                    yield_percent=yield_val,
                    conditions_json=json.dumps(cond) if cond else None,
                    catalysts=json.dumps(cond.get("catalysts") or []) if cond.get("catalysts") else None,
                    solvents=json.dumps(cond.get("solvents") or []) if cond.get("solvents") else None,
                    reagents=json.dumps(cond.get("reagents") or []) if cond.get("reagents") else None,
                    temperature=cond.get("temperature") or None,
                    time=cond.get("time") or None,
                    pressure=cond.get("pressure") or None,
                    ph=cond.get("ph") or None,
                    atmosphere=cond.get("atmosphere") or None,
                    procedure=r.get("procedure") or None,
                    workup=r.get("workup") or None,
                    purification=r.get("purification") or None,
                )
                session.add(rec)
                added_r += 1

        session.commit()

    return added_s, added_r


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="SciFinder PDF 反应数据提取（基于 DeepSeek LLM）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s documents/Reaction_20260811_1355.pdf
  %(prog)s documents/Reaction_20260811_1355.pdf --max-schemes 5 -o result.json
  %(prog)s documents/Reaction_20260811_1355.pdf --import-db
        """,
    )
    parser.add_argument("pdf_path", help="SciFinder 导出的 PDF 文件路径")
    parser.add_argument(
        "-o", "--output",
        default="scifinder_extracted.json",
        help="输出 JSON 文件路径（默认: scifinder_extracted.json）",
    )
    parser.add_argument(
        "--max-schemes",
        type=int,
        default=0,
        help="最多处理的 Scheme 数量，0=全部（默认: 0）",
    )
    parser.add_argument(
        "--scheme",
        type=int,
        default=0,
        help="只处理指定编号的 Scheme（默认: 0=全部）",
    )
    parser.add_argument(
        "--import-db",
        action="store_true",
        help="提取后导入 ChemRoute 数据库",
    )
    parser.add_argument(
        "--model",
        default=os.getenv("LLM_MODEL", "deepseek-chat"),
        help="DeepSeek 模型名称（默认: deepseek-chat）",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.5,
        help="API 调用间隔秒数（默认: 0.5）",
    )
    parser.add_argument(
        "--skip-dedup",
        action="store_true",
        help="跳过字符去重（如果 PDF 文本没有扭曲问题）",
    )
    args = parser.parse_args()

    # ---- 验证 PDF 文件 ----
    pdf_path = Path(args.pdf_path)
    if not pdf_path.exists():
        logger.error("文件不存在: %s", pdf_path)
        sys.exit(1)
    if not pdf_path.suffix.lower() == ".pdf":
        logger.error("不是 PDF 文件: %s", pdf_path)
        sys.exit(1)

    # ---- 提取文本 ----
    logger.info("正在提取 PDF 文本: %s", pdf_path)
    raw_text = extract_text_from_pdf(str(pdf_path))
    logger.info("原始文本长度: %d 字符", len(raw_text))

    # ---- 字符去重 ----
    if not args.skip_dedup:
        logger.info("正在修复 SciFinder 字符重复...")
        text = dedup_sci_finder_text(raw_text)
        logger.info("去重后文本长度: %d 字符（减少 %.0f%%）",
                     len(text), (1 - len(text) / len(raw_text)) * 100)
    else:
        text = raw_text

    # ---- 按 Scheme 分块 ----
    schemes = split_into_schemes(text)
    logger.info("检测到 %d 个 Scheme", len(schemes))

    if not schemes:
        logger.error("未检测到 Scheme，请确认 PDF 是否为 SciFinder Reaction 导出")
        sys.exit(1)

    # ---- 过滤 ----
    if args.scheme > 0:
        schemes = [(n, b) for n, b in schemes if n == args.scheme]
        if not schemes:
            logger.error("未找到 Scheme %d", args.scheme)
            sys.exit(1)
    if args.max_schemes > 0:
        schemes = schemes[: args.max_schemes]

    logger.info("将处理 %d 个 Scheme", len(schemes))

    # ---- 初始化 LLM 客户端 ----
    client = _get_client()
    model = args.model

    # ---- 逐 Scheme 调用 LLM ----
    all_reactions: list[dict[str, Any]] = []
    scheme_overviews: dict[int, dict[str, Any]] = {}
    failed_schemes = 0
    total_reactions = 0

    for idx, (scheme_num, block) in enumerate(schemes, 1):
        logger.info("[%d/%d] 处理 Scheme %d ...", idx, len(schemes), scheme_num)

        # 收集 Scheme 概览（正则，用作 Scheme 表的补充数据）
        overview = quick_extract_overview(block)
        scheme_overviews[scheme_num] = overview

        # LLM 提取 → 返回 reactions 列表
        reactions = extract_scheme_with_llm(client, scheme_num, block, model)

        if reactions is None or len(reactions) == 0:
            logger.warning("Scheme %d 未提取到 reaction，跳过", scheme_num)
            failed_schemes += 1
            continue

        all_reactions.extend(reactions)
        total_reactions += len(reactions)
        logger.info("  → 提取到 %d 个 reaction", len(reactions))

        # 控制 API 调用速率
        if idx < len(schemes):
            time.sleep(args.delay)

    # ---- 汇总输出 ----
    output: dict[str, Any] = {
        "source": "scifinder_llm",
        "pdf_path": str(pdf_path),
        "total_schemes": len(schemes),
        "failed_schemes": failed_schemes,
        "total_reactions": len(all_reactions),
        "model": model,
        "reactions": all_reactions,
    }

    # ---- 写入 JSON ----
    output_path = Path(args.output)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    logger.info("结果已写入: %s (%d reactions)", output_path, len(all_reactions))

    # ---- 统计 ----
    with_title = sum(1 for r in all_reactions if r.get("title"))
    with_yield = sum(1 for r in all_reactions if r.get("yield"))
    with_products = sum(1 for r in all_reactions if r.get("products"))
    with_procedure = sum(1 for r in all_reactions if r.get("procedure"))
    logger.info(
        "提取统计: %d reactions, 有标题=%d, 有产率=%d, 有产物=%d, 有步骤=%d, 失败Scheme=%d",
        len(all_reactions), with_title, with_yield, with_products, with_procedure, failed_schemes,
    )

    # ---- 可选：导入数据库 ----
    if args.import_db:
        logger.info("正在导入数据库...")
        try:
            s_count, r_count = import_to_database(all_reactions, scheme_overviews, str(pdf_path))
            logger.info("导入完成: %d Scheme + %d ReactionRecord", s_count, r_count)
        except Exception as exc:
            logger.error("数据库导入失败: %s", exc)
            sys.exit(1)


if __name__ == "__main__":
    main()
