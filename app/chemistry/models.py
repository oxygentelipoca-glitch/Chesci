"""化学领域 ORM 模型 — reactions.db 中的合成反应数据。

    reactions.db 由 SciFinder PDF 提取程序生成，包含5个核心表：
    - schemes：合成方案（Scheme），是反应的逻辑分组
    - reactions：单个反应记录，包含 CAS Registry ID、收率、SMILES 等
    - reaction_conditions：反应条件（试剂、催化剂、溶剂、温度、时间等）
    - literature：文献引用（标题、作者、期刊、年份等）
    - extraction_log：提取批次日志（LLM 调用记录）

    支持 SciFinder PDF 提取结果经人工校对后写入，并由本模块查询。
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


# ═══════════════════════════════════════════════════════════════════════════
# Scheme — 合成方案
# ═══════════════════════════════════════════════════════════════════════════

class Scheme(SQLModel, table=True):
    """合成方案（SciFinder PDF 中的每个 Scheme）。

    一个 Scheme 包含多个 Reaction，是反应的逻辑分组。
    raw_json 字段存储从 PDF 提取的完整结构化数据。
    """

    __tablename__ = "schemes"

    id: Optional[int] = Field(default=None, primary_key=True)

    scheme_number: int = Field(index=True, description="PDF 中的 Scheme 编号")
    reaction_count: int = Field(default=1, description="该 Scheme 包含的反应数量")
    overall_yield: Optional[str] = Field(default=None, description="整体收率范围（如 71-94%）")
    overall_steps: Optional[int] = Field(default=None, description="整体步骤数")
    description: Optional[str] = Field(default=None, description="Scheme 描述/注释")
    page_start: int = Field(description="起始页码")
    page_end: Optional[int] = Field(default=None, description="结束页码")

    raw_json: Optional[str] = Field(default=None, description="原始提取 JSON（完整数据）")

    created_at: datetime = Field(default_factory=datetime.utcnow)


# ═══════════════════════════════════════════════════════════════════════════
# Reaction — 反应记录
# ═══════════════════════════════════════════════════════════════════════════

class Reaction(SQLModel, table=True):
    """单个化学反应记录。

    属于某个 Scheme（1:N），通过 cas_registry_id 关联 SciFinder CAS Registry。
    reactant_smiles / product_smiles 为 OCSR（光学化学结构识别）结果。
    """

    __tablename__ = "reactions"

    id: Optional[int] = Field(default=None, primary_key=True)

    # ---- 父子关系 ----
    scheme_id: Optional[int] = Field(
        default=None,
        foreign_key="schemes.id",
        index=True,
        description="所属 Scheme ID",
    )

    # ---- 反应标识 ----
    cas_registry_id: Optional[str] = Field(
        default=None,
        index=True,
        max_length=100,
        description="SciFinder CAS Registry ID（如 31-333-CAS-20579053）",
    )

    # ---- 收率与步骤 ----
    yield_: Optional[str] = Field(
        default=None,
        max_length=50,
        description="收率原文（如 94%, 71-94%）",
    )
    steps: Optional[int] = Field(default=None, description="反应步骤数")

    # ---- 反应物/产物文本 ----
    reactants_text: Optional[str] = Field(
        default=None,
        description="反应物文本描述",
    )
    products_text: Optional[str] = Field(
        default=None,
        description="产物文本描述",
    )
    reactants_en: Optional[str] = Field(
        default=None,
        description="反应物英文名称",
    )
    reactants_zh: Optional[str] = Field(
        default=None,
        description="反应物中文名称",
    )
    products_en: Optional[str] = Field(
        default=None,
        description="产物英文名称",
    )
    products_zh: Optional[str] = Field(
        default=None,
        description="产物中文名称",
    )

    # ---- 页面信息 ----
    page: int = Field(description="PDF 页码")
    has_structure_image: bool = Field(default=False, description="是否包含结构式图片")

    # ---- OCSR 结构识别 ----
    reactant_smiles: Optional[str] = Field(
        default=None,
        description="反应物 SMILES（OCSR 识别）",
    )
    product_smiles: Optional[str] = Field(
        default=None,
        description="产物 SMILES（OCSR 识别）",
    )
    ocsr_method: Optional[str] = Field(
        default=None,
        max_length=100,
        description="OCSR 识别方法（如 DECIMER, MolVec）",
    )
    ocsr_confidence: Optional[float] = Field(
        default=None,
        description="OCSR 识别置信度（0-1）",
    )

    # ---- 备注 ----
    notes: Optional[str] = Field(default=None, description="备注/注释")

    # ---- 原始数据 ----
    raw_json: Optional[str] = Field(default=None, description="原始提取 JSON")

    # ---- 审计 ----
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ═══════════════════════════════════════════════════════════════════════════
# ReactionCondition — 反应条件
# ═══════════════════════════════════════════════════════════════════════════

class ReactionCondition(SQLModel, table=True):
    """反应条件详情。

    每个 Reaction 可以有多个反应条件（多个步骤），
    每条记录对应一个操作步骤，记录该步的试剂、催化剂、溶剂、温度、时间等。
    """

    __tablename__ = "reaction_conditions"

    id: Optional[int] = Field(default=None, primary_key=True)

    reaction_id: Optional[int] = Field(
        default=None,
        foreign_key="reactions.id",
        index=True,
        description="所属 Reaction ID",
    )

    step_number: Optional[str] = Field(
        default=None,
        max_length=50,
        description="步骤编号（如 1.1, 1.2）",
    )

    reagents: Optional[str] = Field(default=None, description="试剂列表（逗号分隔或 JSON）")
    catalysts: Optional[str] = Field(default=None, description="催化剂列表")
    solvents: Optional[str] = Field(default=None, description="溶剂列表")
    temperature: Optional[str] = Field(default=None, max_length=200, description="温度条件")
    time: Optional[str] = Field(default=None, max_length=200, description="反应时间")
    other: Optional[str] = Field(default=None, description="其他条件/后处理")

    raw_text: Optional[str] = Field(default=None, description="原始条件文本")


# ═══════════════════════════════════════════════════════════════════════════
# Literature — 文献引用
# ═══════════════════════════════════════════════════════════════════════════

class Literature(SQLModel, table=True):
    """化学文献引用记录。

    每个 Reaction 最多关联一条 Literature（1:1），
    存储论文/专利的标题、作者、期刊、年份等元数据。
    """

    __tablename__ = "literature"

    id: Optional[int] = Field(default=None, primary_key=True)

    reaction_id: Optional[int] = Field(
        default=None,
        foreign_key="reactions.id",
        unique=True,
        index=True,
        description="关联的 Reaction ID（1:1）",
    )

    title: Optional[str] = Field(default=None, description="文献标题")
    authors: Optional[str] = Field(default=None, description="作者列表")
    journal: Optional[str] = Field(default=None, max_length=500, description="期刊/来源名称")
    year: Optional[int] = Field(default=None, description="出版年份")
    volume: Optional[str] = Field(default=None, max_length=100, description="卷号")
    pages: Optional[str] = Field(default=None, max_length=100, description="页码")
    doi: Optional[str] = Field(default=None, max_length=255, description="DOI 标识符")

    raw_text: Optional[str] = Field(default=None, description="原始文献引用文本")


# ═══════════════════════════════════════════════════════════════════════════
# ExtractionLog — 提取日志
# ═══════════════════════════════════════════════════════════════════════════

class ExtractionLog(SQLModel, table=True):
    """SciFinder PDF 提取批次日志。

    记录每次 LLM 调用的批次信息、成功/失败状态、token 消耗等。
    """

    __tablename__ = "extraction_log"

    id: Optional[int] = Field(default=None, primary_key=True)

    batch_number: int = Field(index=True, description="批次编号")
    page_start: int = Field(description="起始页码")
    page_end: int = Field(description="结束页码")

    status: str = Field(max_length=50, description="状态（success/failed/partial）")
    schemes_found: int = Field(default=0, description="发现的 Scheme 数量")
    reactions_found: int = Field(default=0, description="发现的 Reaction 数量")

    error_message: Optional[str] = Field(default=None, description="错误信息")
    raw_response: Optional[str] = Field(default=None, description="LLM 原始响应")
    model_used: Optional[str] = Field(default=None, max_length=100, description="使用的模型")
    tokens_used: Optional[int] = Field(default=None, description="消耗的 token 数")
    duration_seconds: Optional[float] = Field(default=None, description="耗时（秒）")

    created_at: datetime = Field(default_factory=datetime.utcnow)


# ═══════════════════════════════════════════════════════════════════════════
# ReactionEquation — 反应方程式（知识图谱数据源）
# ═══════════════════════════════════════════════════════════════════════════

class ReactionEquation(SQLModel, table=True):
    """反应方程式记录（reaction_equations 表）。

    每个 Reaction 对应一条方程式记录，是知识图谱构建和方程式查询的
    核心数据源：
    - equation：SMILES 形式方程式（反应物 (条件) >> 产物）
    - equation_zh：中文名称形式方程式
    - reactant_smiles / product_smiles：反应物/产物 SMILES
    """

    __tablename__ = "reaction_equations"

    id: Optional[int] = Field(default=None, primary_key=True)

    reaction_id: int = Field(index=True, description="关联的 Reaction ID")

    equation: Optional[str] = Field(default=None, description="方程式（SMILES 形式）")
    equation_zh: Optional[str] = Field(default=None, description="方程式（中文名称形式）")
    reactant_smiles: Optional[str] = Field(default=None, description="反应物 SMILES")
    product_smiles: Optional[str] = Field(default=None, description="产物 SMILES")
    conditions_summary: Optional[str] = Field(default=None, description="条件摘要文本")

    created_at: datetime = Field(default_factory=datetime.utcnow)
