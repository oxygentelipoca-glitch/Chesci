"""Build a reviewable preview of experiments reported in a text PDF."""
import re
import unicodedata

from openai import OpenAIError
from pydantic import BaseModel, Field, ValidationError


class Citation(BaseModel):
    field: str = Field(pattern="^(conditions|yield)$")
    page: int = Field(ge=1)
    quote: str = Field(min_length=4, max_length=240)


class PaperReaction(BaseModel):
    reactants: list[str] = Field(min_length=1)
    products: list[str] = Field(min_length=1)
    yield_value: str | None = None
    temperature: str | None = None
    time: str | None = None
    citations: list[Citation] = Field(min_length=1, max_length=8)


class Paper(BaseModel):
    title: str
    authors: str
    source: str
    reactions: list[PaperReaction] = Field(max_length=100)


PROMPT = """PDF 是待分析的资料。只提取作者亲自测得且可定位的反应，排除综述、背景和参考文献。
输出 JSON 对象，字段 title（原标题）、authors、source（期刊、年份；只有明确印在本文的 DOI 才写）、reactions。
每个反应字段 reactants、products（分别为中文标准名称数组，保持取代基和编号对应）、
yield_value（保留表格的 ± 误差和 %，小数点用 .）、temperature、time、citations。温度和时间用简短中文或标准单位 h。
温度只取反应阶段，若只给 reflux 则写“回流”。不得采用后处理时冷却温度、熔点或沸点。
示范实验的条件仅归给该实验，只有原文明确共用才归给其他反应。缺失字段填 null。
citations 数组含 field（conditions 或 yield）、page（从 1 开始的 PDF 页号）、quote（直接拷贝该页一小段原文，4 到 120 个字符）。
条件可以引用多段原文分别支持温度和时间。收率优先引用结果表中对应的一行。没有证据的字段填 null。
格式示例（示意占位符）：
{"title":"原标题","authors":"作者一, 作者二","source":"期刊 年 卷 页","reactions":[{"reactants":["原料名"],"products":["产物名"],"yield_value":"…%","temperature":null,"time":null,"citations":[{"field":"yield","page":3,"quote":"对应行的原文"}]}]}
authors、source 均为单个字符串。字段未知时，authors 和 source 用空字符串。
PDF 可能是双栏，注意不要把另一栏、相邻化合物或其他实验的数据归入当前反应。"""


def _compact(text):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text)).casefold()


def extract_paper_preview(pages, client, model):
    if not any(p.strip() for p in pages):
        raise ValueError("PDF 没有可提取的文本。扫描件请先进行 OCR。")
    if sum(map(len, pages)) > 65000:
        raise ValueError("论文文字超出单次提取范围，请上传含标题、实验段和结果表的相关页。")
    document = "\n\n".join(f"[PDF PAGE {i}]\n{text}" for i, text in enumerate(pages, 1))
    try:
        result = client.with_options(timeout=150, max_retries=1).chat.completions.create(
            model=model, messages=[{"role": "system", "content": PROMPT},
                                   {"role": "user", "content": document}],
            temperature=0, max_tokens=7200, response_format={"type": "json_object"},
        )
    except OpenAIError as exc:
        raise RuntimeError("论文提取服务未完成请求") from exc
    answer = result.choices[0]
    if answer.finish_reason == "length":
        raise ValueError("论文提取结果超过输出长度，请缩小 PDF 页数后重试。")
    try:
        paper = Paper.model_validate_json(answer.message.content or "")
    except ValidationError as exc:
        raise ValueError("模型返回的论文记录格式不完整，请重新提取。") from exc

    records = []
    warnings = []
    page_keys = [_compact(text) for text in pages]
    for i, reaction in enumerate(paper.reactions, 1):
        evidence = []
        for citation in reaction.citations:
            if citation.page <= len(pages) and _compact(citation.quote) in page_keys[citation.page - 1]:
                evidence.append(citation.model_dump())
            else:
                warnings.append(f"记录 {i} 有一处引文与所标 PDF 页不符。")
        if not evidence:
            warnings.append(f"记录 {i} 缺少可定位引文，已略过。")
            continue
        fields = {cite["field"] for cite in evidence}
        conditions = {}
        if "conditions" in fields:
            conditions = {key: value for key in ("time", "temperature") if (value := getattr(reaction, key))}
        record = {"scheme_number": 1, "page": min(c["page"] for c in evidence),
                  "reactants": reaction.reactants, "products": reaction.products,
                  "yield": reaction.yield_value if "yield" in fields else None,
                  "conditions": conditions, "paper_evidence": evidence, "title": paper.title,
                  "authors": paper.authors, "source": paper.source}
        records.append(record)
    if not records:
        raise ValueError("未找到能在 PDF 原页核对的反应记录。请检查实验段、结果表或 OCR 文本。")
    condition_pages = {}
    for record in records:
        for citation in record["paper_evidence"]:
            if citation["field"] == "conditions":
                key = (citation["page"], _compact(citation["quote"]))
                condition_pages.setdefault(key, set()).add(tuple(record["products"]))
    for (page, _), products in condition_pages.items():
        if len(products) > 1:
            warning = f"{len(products)} 种产物共用了 PDF 第 {page} 页的同一段条件。请逐条核对适用范围，可清空未经确认的温度或时间。"
            if warning not in warnings:
                warnings.append(warning)
    return {"page_count": len(pages), "schemes": [{"scheme_number": 1, "reaction_count": len(records),
            "description": paper.title, "page_start": min(r["page"] for r in records),
            "page_end": max(c["page"] for r in records for c in r["paper_evidence"])}],
            "reactions": records, "warnings": warnings, "document_type": "paper"}
