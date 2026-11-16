"""化学信息解析模块。

将用户输入的化合物名称、CAS 号或 SMILES 识别并标准化，
返回数据库中匹配的化合物完整信息及其关联的反应和文献。

输入类型自动识别
------------------
- **CAS 号**：正则 ``\\d{2,7}-\\d{2}-\\d``（如 ``15687-27-1``）
- **SMILES**：包含 ``= # ( ) [ ] @ + - \\ / %`` 等特征字符
- **名称**：其余输入，模糊匹配（LIKE %query%）

降级策略
--------
当 Neo4j 不可用时，通过关系数据库的 ``reactant_ids`` / ``product_ids``
JSON 字段做关联查询，保证基本可用。
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from sqlmodel import Session, or_, select

from app.chemistry.models import Compound, Literature, Reaction
from app.database import engine, neo4j_available, neo4j_session

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 输入类型识别
# ---------------------------------------------------------------------------

_CAS_PATTERN = re.compile(r"^\d{2,7}-\d{2}-\d$")
_SMILES_CHARS = re.compile(r"[=#()\[\]@+\-/\\%]")


def detect_input_type(text: str) -> str:
    """检测输入类型：``cas`` / ``smiles`` / ``name``。"""
    if _CAS_PATTERN.match(text.strip()):
        return "cas"
    if _SMILES_CHARS.search(text):
        return "smiles"
    return "name"


# ---------------------------------------------------------------------------
# 结果类型
# ---------------------------------------------------------------------------

@dataclass
class CompoundResult:
    """解析后的化合物完整信息。"""
    compound: dict
    reactions_as_product: list[dict] = field(default_factory=list)
    reactions_as_reactant: list[dict] = field(default_factory=list)
    related_literature: list[dict] = field(default_factory=list)
    upstream: list[dict] = field(default_factory=list)    # 上游原料（从图谱）
    downstream: list[dict] = field(default_factory=list)  # 下游产物（从图谱）
    query_type: str = "name"
    neo4j_used: bool = False


def _compound_to_dict(c: Compound) -> dict:
    """将 ORM 对象转为前端友好的字典。"""
    return {
        "id": c.id,
        "name": c.name,
        "cas": c.cas,
        "smiles": c.smiles,
        "molecular_formula": c.molecular_formula,
        "molecular_weight": c.molecular_weight,
        "compound_class": c.compound_class,
        "iupac_name": c.iupac_name,
        "description": c.description,
        "synonyms": json.loads(c.synonyms) if c.synonyms else [],
    }


def _reaction_to_dict(r: Reaction) -> dict:
    """将 Reaction ORM 对象转为字典。"""
    return {
        "id": r.id,
        "name": r.name,
        "reaction_type": r.reaction_type,
        "equation": r.equation,
        "catalyst": r.catalyst,
        "solvent": r.solvent,
        "temperature": r.temperature,
        "reaction_time": r.reaction_time,
        "yield_percent": r.yield_percent,
        "difficulty": r.difficulty,
        "safety_level": r.safety_level,
        "eco_score": r.eco_score,
        "cost_level": r.cost_level,
        "reactant_ids": json.loads(r.reactant_ids) if r.reactant_ids else [],
        "product_ids": json.loads(r.product_ids) if r.product_ids else [],
        "literature_id": r.literature_id,
        "source": r.source,
    }


def _literature_to_dict(l: Literature) -> dict:
    """将 Literature ORM 对象转为字典。"""
    return {
        "id": l.id,
        "title": l.title,
        "authors": l.authors,
        "year": l.year,
        "journal": l.journal,
        "doi": l.doi,
        "abstract": l.abstract,
        "source_type": l.source_type,
        "language": l.language,
    }


# ---------------------------------------------------------------------------
# 主解析函数
# ---------------------------------------------------------------------------

def parse_compound(
    query: str,
    *,
    include_relations: bool = True,
    include_graph: bool = True,
) -> Optional[CompoundResult]:
    """解析用户输入的化合物查询。

    Parameters
    ----------
    query : str
        用户输入（名称、CAS 或 SMILES）。
    include_relations : bool
        是否同时查询关联反应和文献。
    include_graph : bool
        是否同时查询知识图谱上下游关系。

    Returns
    -------
    CompoundResult or None
        匹配成功时返回完整信息；未找到时返回 None。
    """
    query = query.strip()
    if not query:
        return None

    input_type = detect_input_type(query)
    logger.info("解析化合物: type=%s, query=%s", input_type, query)

    with Session(engine) as session:
        # ---- 1. 查找化合物 ----
        compound = _find_compound(session, query, input_type)
        if not compound:
            # 名称模式下尝试同义词模糊匹配
            if input_type == "name":
                compound = _find_by_synonym(session, query)
        if not compound:
            logger.info("未找到化合物: %s", query)
            return None

        result = CompoundResult(
            compound=_compound_to_dict(compound),
            query_type=input_type,
        )

        if not include_relations:
            return result

        cid = compound.id

        # ---- 2. 关联反应 ----
        all_reactions = session.exec(select(Reaction)).all()

        for r in all_reactions:
            r_dict = _reaction_to_dict(r)
            if cid in r_dict["product_ids"]:
                result.reactions_as_product.append(r_dict)
            if cid in r_dict["reactant_ids"]:
                result.reactions_as_reactant.append(r_dict)

        # ---- 3. 关联文献 ----
        lit_ids = set()
        for r_dict in result.reactions_as_product + result.reactions_as_reactant:
            if r_dict["literature_id"]:
                lit_ids.add(r_dict["literature_id"])

        if lit_ids:
            literatures = session.exec(
                select(Literature).where(Literature.id.in_(lit_ids))
            ).all()
            for l in literatures:
                result.related_literature.append(_literature_to_dict(l))

        # ---- 4. 知识图谱上下游（Neo4j 优先，SQL 降级） ----
        if include_graph:
            if neo4j_available():
                result.upstream = _graph_upstream_neo4j(compound.name)
                result.downstream = _graph_downstream_neo4j(compound.name)
                result.neo4j_used = True
            else:
                result.upstream = _graph_upstream_sql(session, cid)
                result.downstream = _graph_downstream_sql(session, cid)
                result.neo4j_used = False

        return result


# ---------------------------------------------------------------------------
# 数据库查找
# ---------------------------------------------------------------------------

def _find_compound(session: Session, query: str, input_type: str) -> Optional[Compound]:
    """按类型精确查找化合物。"""
    if input_type == "cas":
        return session.exec(
            select(Compound).where(Compound.cas == query)
        ).first()
    elif input_type == "smiles":
        return session.exec(
            select(Compound).where(Compound.smiles == query)
        ).first()
    else:
        # 名称精确匹配 + 模糊匹配
        compound = session.exec(
            select(Compound).where(Compound.name == query)
        ).first()
        if compound:
            return compound
        # 模糊匹配
        return session.exec(
            select(Compound).where(
                or_(
                    Compound.name.contains(query),
                    Compound.iupac_name.contains(query),
                )
            )
        ).first()


def _find_by_synonym(session: Session, query: str) -> Optional[Compound]:
    """通过同义词 JSON 字段模糊查找。"""
    compounds = session.exec(select(Compound)).all()
    for c in compounds:
        if c.synonyms and query.lower() in c.synonyms.lower():
            return c
    return None


# ---------------------------------------------------------------------------
# 图谱查询 — Neo4j
# ---------------------------------------------------------------------------

def _graph_upstream_neo4j(compound_name: str) -> list[dict]:
    """Neo4j：查询谁参与反应产生目标化合物（上游原料）。"""
    try:
        with neo4j_session() as n4j:
            result = n4j.run(
                """
                MATCH (upstream:Compound)-[:PARTICIPATES_IN]->(r:Reaction)
                      -[:PRODUCES]->(target:Compound {name: $name})
                RETURN upstream.name AS name, upstream.cas AS cas,
                       r.name AS reaction, r.yield_percent AS yield_pct
                """,
                name=compound_name,
            )
            return [
                {
                    "compound": record["name"],
                    "cas": record["cas"],
                    "reaction": record["reaction"],
                    "yield_percent": record["yield_pct"],
                }
                for record in result
            ]
    except Exception as exc:
        logger.warning("Neo4j 上游查询失败: %s", exc)
        return []


def _graph_downstream_neo4j(compound_name: str) -> list[dict]:
    """Neo4j：查询目标化合物参与反应后产生什么（下游产物）。"""
    try:
        with neo4j_session() as n4j:
            result = n4j.run(
                """
                MATCH (start:Compound {name: $name})-[:PARTICIPATES_IN]->(r:Reaction)
                      -[:PRODUCES]->(downstream:Compound)
                RETURN downstream.name AS name, downstream.cas AS cas,
                       r.name AS reaction, r.yield_percent AS yield_pct
                """,
                name=compound_name,
            )
            return [
                {
                    "compound": record["name"],
                    "cas": record["cas"],
                    "reaction": record["reaction"],
                    "yield_percent": record["yield_pct"],
                }
                for record in result
            ]
    except Exception as exc:
        logger.warning("Neo4j 下游查询失败: %s", exc)
        return []


# ---------------------------------------------------------------------------
# 图谱查询 — SQL 降级
# ---------------------------------------------------------------------------

def _resolve_compound_names(session: Session, ids: list[int]) -> list[dict]:
    """将化合物 ID 列表解析为名称字典。"""
    if not ids:
        return []
    compounds = session.exec(
        select(Compound).where(Compound.id.in_(ids))
    ).all()
    return [{"id": c.id, "name": c.name, "cas": c.cas} for c in compounds]


def _graph_upstream_sql(session: Session, compound_id: int) -> list[dict]:
    """SQL 降级：查找哪些反应产生目标化合物 → 其反应物即为上游原料。"""
    reactions = session.exec(select(Reaction)).all()
    upstream = []
    for r in reactions:
        pids = json.loads(r.product_ids) if r.product_ids else []
        if compound_id in pids:
            rids = json.loads(r.reactant_ids) if r.reactant_ids else []
            for reactant in _resolve_compound_names(session, rids):
                upstream.append({
                    "compound": reactant["name"],
                    "cas": reactant["cas"],
                    "reaction": r.name,
                    "yield_percent": r.yield_percent,
                })
    return upstream


def _graph_downstream_sql(session: Session, compound_id: int) -> list[dict]:
    """SQL 降级：查找目标化合物作为反应物的反应 → 其产物即为下游产物。"""
    reactions = session.exec(select(Reaction)).all()
    downstream = []
    for r in reactions:
        rids = json.loads(r.reactant_ids) if r.reactant_ids else []
        if compound_id in rids:
            pids = json.loads(r.product_ids) if r.product_ids else []
            for product in _resolve_compound_names(session, pids):
                downstream.append({
                    "compound": product["name"],
                    "cas": product["cas"],
                    "reaction": r.name,
                    "yield_percent": r.yield_percent,
                })
    return downstream


# ---------------------------------------------------------------------------
# 便捷函数：查询所有化合物列表
# ---------------------------------------------------------------------------

def list_compounds(search: str = "") -> list[dict]:
    """列出数据库中所有化合物（支持名称搜索过滤）。"""
    with Session(engine) as session:
        if search:
            compounds = session.exec(
                select(Compound).where(
                    or_(
                        Compound.name.contains(search),
                        Compound.cas.contains(search),
                    )
                )
            ).all()
        else:
            compounds = session.exec(select(Compound)).all()
        return [_compound_to_dict(c) for c in compounds]
