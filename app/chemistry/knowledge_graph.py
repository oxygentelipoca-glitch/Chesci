"""化学知识图谱 — 基于 reactions.db 的上下游查询和 Neo4j 同步。

提供：
- 上下游反应查询（通过 SMILES 匹配）
- Neo4j 数据同步（Scheme → CONTAINS → Reaction）
- 化合物网络构建
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlmodel import Session, select

from app.chemistry.models import Scheme, Reaction
from app.database import chemistry_engine, neo4j_available, neo4j_session

logger = logging.getLogger(__name__)


def get_upstream(reaction_id: int, limit: int = 20) -> list[dict]:
    """查询上游反应：哪些反应的产物与本反应的反应物匹配。

    通过 reactant_smiles 匹配其他反应的 product_smiles。
    """
    with Session(chemistry_engine) as session:
        reaction = session.get(Reaction, reaction_id)
        if not reaction or not reaction.reactant_smiles:
            return []

        # 查找 product_smiles 包含本反应 reactant_smiles 的其他反应
        upstream = session.exec(
            select(Reaction).where(
                Reaction.product_smiles.contains(reaction.reactant_smiles),
                Reaction.id != reaction_id,
            ).limit(limit)
        ).all()

        result = []
        for r in upstream:
            scheme = session.get(Scheme, r.scheme_id) if r.scheme_id else None
            result.append({
                "id": r.id,
                "cas_registry_id": r.cas_registry_id,
                "reactants_text": r.reactants_text,
                "products_text": r.products_text,
                "yield_": r.yield_,
                "reactant_smiles": r.reactant_smiles,
                "product_smiles": r.product_smiles,
                "scheme_number": scheme.scheme_number if scheme else None,
            })

        return result


def get_downstream(reaction_id: int, limit: int = 20) -> list[dict]:
    """查询下游反应：哪些反应将本反应的产物作为反应物。

    通过 product_smiles 匹配其他反应的 reactant_smiles。
    """
    with Session(chemistry_engine) as session:
        reaction = session.get(Reaction, reaction_id)
        if not reaction or not reaction.product_smiles:
            return []

        downstream = session.exec(
            select(Reaction).where(
                Reaction.reactant_smiles.contains(reaction.product_smiles),
                Reaction.id != reaction_id,
            ).limit(limit)
        ).all()

        result = []
        for r in downstream:
            scheme = session.get(Scheme, r.scheme_id) if r.scheme_id else None
            result.append({
                "id": r.id,
                "cas_registry_id": r.cas_registry_id,
                "reactants_text": r.reactants_text,
                "products_text": r.products_text,
                "yield_": r.yield_,
                "reactant_smiles": r.reactant_smiles,
                "product_smiles": r.product_smiles,
                "scheme_number": scheme.scheme_number if scheme else None,
            })

        return result


def sync_to_neo4j() -> dict:
    """将 Scheme 和 Reaction 数据同步到 Neo4j 知识图谱。

    节点：
    - (:Scheme {id, scheme_number, reaction_count, overall_yield})
    - (:Reaction {id, cas_registry_id, yield_, reactants_text, products_text})

    关系：
    - (s:Scheme)-[:CONTAINS]->(r:Reaction)
    """
    if not neo4j_available():
        return {"success": False, "message": "Neo4j 不可用，请检查环境变量 NEO4J_URI"}

    with Session(chemistry_engine) as session:
        schemes = session.exec(select(Scheme)).all()
        reactions = session.exec(select(Reaction)).all()

    created_schemes = 0
    created_reactions = 0
    created_relations = 0

    try:
        with neo4j_session() as ns:
            # 创建唯一性约束（幂等）
            ns.run("CREATE CONSTRAINT IF NOT EXISTS FOR (s:Scheme) REQUIRE s.id IS UNIQUE")
            ns.run("CREATE CONSTRAINT IF NOT EXISTS FOR (r:Reaction) REQUIRE r.id IS UNIQUE")

            # 同步 Scheme 节点
            for s in schemes:
                ns.run(
                    """
                    MERGE (s:Scheme {id: $id})
                    SET s.scheme_number = $scheme_number,
                        s.reaction_count = $reaction_count,
                        s.overall_yield = $overall_yield
                    """,
                    id=s.id,
                    scheme_number=s.scheme_number,
                    reaction_count=s.reaction_count,
                    overall_yield=s.overall_yield,
                )
                created_schemes += 1

            # 同步 Reaction 节点和 CONTAINS 关系
            for r in reactions:
                ns.run(
                    """
                    MERGE (r:Reaction {id: $id})
                    SET r.cas_registry_id = $cas,
                        r.yield = $yield,
                        r.reactants_text = $reactants,
                        r.products_text = $products
                    """,
                    id=r.id,
                    cas=r.cas_registry_id,
                    yield_value=r.yield_,
                    reactants=r.reactants_text,
                    products=r.products_text,
                )
                created_reactions += 1

                # 创建 Scheme → Reaction 关系
                if r.scheme_id:
                    ns.run(
                        """
                        MATCH (s:Scheme {id: $scheme_id})
                        MATCH (r:Reaction {id: $reaction_id})
                        MERGE (s)-[:CONTAINS]->(r)
                        """,
                        scheme_id=r.scheme_id,
                        reaction_id=r.id,
                    )
                    created_relations += 1

        logger.info(
            "Neo4j 同步完成: %d Scheme, %d Reaction, %d 关系",
            created_schemes, created_reactions, created_relations,
        )

    except Exception as exc:
        logger.error("Neo4j 同步失败: %s", exc)
        return {"success": False, "message": str(exc)}

    return {
        "success": True,
        "schemes": created_schemes,
        "reactions": created_reactions,
        "relations": created_relations,
    }


def get_compound_network(compound_name: str, limit: int = 30) -> dict:
    """通过反应物/产物文本匹配构建化合物关系网络。

    返回该化合物参与的所有反应及其上下游关系。
    """
    with Session(chemistry_engine) as session:
        pattern = f"%{compound_name}%"

        # 该化合物作为反应物的反应
        as_reactant = session.exec(
            select(Reaction).where(Reaction.reactants_text.contains(pattern)).limit(limit)
        ).all()

        # 该化合物作为产物的反应
        as_product = session.exec(
            select(Reaction).where(Reaction.products_text.contains(pattern)).limit(limit)
        ).all()

        nodes: list[dict] = []
        edges: list[dict] = []
        seen_ids: set[int] = set()

        # 添加核心化合物节点
        nodes.append({
            "id": "compound_target",
            "name": compound_name,
            "category": "target",
            "symbolSize": 40,
        })

        for r in as_reactant:
            if r.id not in seen_ids:
                seen_ids.add(r.id)
                scheme = session.get(Scheme, r.scheme_id) if r.scheme_id else None
                nodes.append({
                    "id": f"reaction_{r.id}",
                    "name": f"R#{r.id}",
                    "category": "reaction",
                    "symbolSize": 30,
                    "cas_registry_id": r.cas_registry_id,
                    "yield_": r.yield_,
                    "reactants_text": r.reactants_text,
                    "products_text": r.products_text,
                    "scheme_number": scheme.scheme_number if scheme else None,
                })
                edges.append({
                    "source": "compound_target",
                    "target": f"reaction_{r.id}",
                    "label": "作为反应物",
                    "direction": "forward",
                })

        for r in as_product:
            if r.id not in seen_ids:
                seen_ids.add(r.id)
                scheme = session.get(Scheme, r.scheme_id) if r.scheme_id else None
                nodes.append({
                    "id": f"reaction_{r.id}",
                    "name": f"R#{r.id}",
                    "category": "reaction",
                    "symbolSize": 30,
                    "cas_registry_id": r.cas_registry_id,
                    "yield_": r.yield_,
                    "reactants_text": r.reactants_text,
                    "products_text": r.products_text,
                    "scheme_number": scheme.scheme_number if scheme else None,
                })
                edges.append({
                    "source": f"reaction_{r.id}",
                    "target": "compound_target",
                    "label": "产生产物",
                    "direction": "backward",
                })

    return {
        "compound": compound_name,
        "nodes": nodes,
        "edges": edges,
        "total_reactions": len(as_reactant) + len(as_product),
    }
