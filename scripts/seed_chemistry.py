"""化学数据库种子脚本。

首次运行时执行，在关系数据库和 Neo4j 知识图谱中写入示例数据：
- 化合物：布洛芬、苯甲醛、肉桂酸 等
- 反应：Knoevenagel 缩合、布洛芬合成路线
- 文献：关联参考文献

用法
----
.. code-block:: bash

    python scripts/seed_chemistry.py            # 仅关系数据库
    python scripts/seed_chemistry.py --neo4j    # 同时写入 Neo4j 图谱
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

# 确保项目根目录在 sys.path 中
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlmodel import Session, select

from app.database import engine, neo4j_available, neo4j_session
from app.chemistry.models import Compound, Literature, Reaction

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# 种子数据
# ═══════════════════════════════════════════════════════════════════════════

SEED_COMPOUNDS: list[dict] = [
    {
        "name": "布洛芬",
        "cas": "15687-27-1",
        "smiles": "CC(C)CC1=CC=C(C=C1)C(C)C(=O)O",
        "molecular_formula": "C13H18O2",
        "molecular_weight": 206.28,
        "synonyms": '["Ibuprofen", "异丁苯丙酸", "2-(4-异丁基苯基)丙酸"]',
        "iupac_name": "2-(4-isobutylphenyl)propanoic acid",
        "compound_class": "NSAID",
        "description": "非甾体抗炎药（NSAID），用于解热、镇痛和抗炎。",
    },
    {
        "name": "对异丁基苯乙酮",
        "cas": "38861-78-8",
        "smiles": "CC(C)CC1=CC=C(C=C1)C(=O)C",
        "molecular_formula": "C12H16O",
        "molecular_weight": 176.25,
        "synonyms": '["4-Isobutylacetophenone", "4-异丁基苯乙酮"]',
        "compound_class": "ketone",
        "description": "布洛芬合成的关键中间体。",
    },
    {
        "name": "苯甲醛",
        "cas": "100-52-7",
        "smiles": "C1=CC=C(C=C1)C=O",
        "molecular_formula": "C7H6O",
        "molecular_weight": 106.12,
        "synonyms": '["Benzaldehyde", "安息香醛"]',
        "iupac_name": "benzaldehyde",
        "compound_class": "aldehyde",
        "description": "最简单的芳香醛，广泛用于香料和医药中间体合成。",
    },
    {
        "name": "丙二酸",
        "cas": "141-82-2",
        "smiles": "C(C(=O)O)C(=O)O",
        "molecular_formula": "C3H4O4",
        "molecular_weight": 104.06,
        "synonyms": '["Malonic acid", "胡萝卜酸"]',
        "compound_class": "dicarboxylic_acid",
        "description": "Knoevenagel 缩合反应常用原料。",
    },
    {
        "name": "肉桂酸",
        "cas": "621-82-9",
        "smiles": "C1=CC=C(C=C1)C=CC(=O)O",
        "molecular_formula": "C9H8O2",
        "molecular_weight": 148.16,
        "synonyms": '["Cinnamic acid", "3-苯基丙烯酸"]',
        "iupac_name": "(E)-3-phenylprop-2-enoic acid",
        "compound_class": "carboxylic_acid",
        "description": "重要香料和医药中间体，Knoevenagel 缩合的经典产物。",
    },
    {
        "name": "哌啶",
        "cas": "110-89-4",
        "smiles": "C1CCNCC1",
        "molecular_formula": "C5H11N",
        "molecular_weight": 85.15,
        "synonyms": '["Piperidine", "六氢吡啶"]',
        "compound_class": "amine",
        "description": "常用有机碱催化剂，Knoevenagel 缩合中使用。",
    },
    {
        "name": "异丁苯",
        "cas": "538-93-2",
        "smiles": "CC(C)CC1=CC=CC=C1",
        "molecular_formula": "C10H14",
        "molecular_weight": 134.22,
        "synonyms": '["Isobutylbenzene", "2-甲基-1-苯基丙烷"]',
        "compound_class": "hydrocarbon",
        "description": "布洛芬合成的起始原料之一。",
    },
    {
        "name": "乙酰氯",
        "cas": "75-36-5",
        "smiles": "CC(=O)Cl",
        "molecular_formula": "C2H3ClO",
        "molecular_weight": 78.50,
        "synonyms": '["Acetyl chloride", "氯化乙酰"]',
        "compound_class": "acyl_chloride",
        "description": "常用乙酰化试剂，Friedel-Crafts 酰基化反应原料。",
    },
    {
        "name": "三氯化铝",
        "cas": "7446-70-0",
        "smiles": "Cl[Al](Cl)Cl",
        "molecular_formula": "AlCl3",
        "molecular_weight": 133.34,
        "synonyms": '["Aluminum chloride", "无水三氯化铝"]',
        "compound_class": "lewis_acid",
        "description": "Friedel-Crafts 反应常用 Lewis 酸催化剂。",
    },
]

SEED_LITERATURE: list[dict] = [
    {
        "title": "布洛芬合成工艺研究进展",
        "authors": "张明; 李华; 王强",
        "year": 2023,
        "journal": "中国医药工业杂志",
        "doi": "10.16522/j.cnki.cjph.2023.05.001",
        "abstract": "综述了布洛芬的主要合成路线，包括 Boots 法和 Hoechst 法等，比较了各路线的收率、成本和环保性。",
        "keywords": "布洛芬; 合成; 工艺优化; 绿色化学",
        "source_type": "review",
        "language": "zh",
    },
    {
        "title": "Knoevenagel Condensation: A Versatile Tool in Organic Synthesis",
        "authors": "Smith J.; Brown R.",
        "year": 2021,
        "journal": "Chemical Reviews",
        "doi": "10.1021/cr.2021.00123",
        "abstract": "Comprehensive review of Knoevenagel condensation reactions, including mechanism, catalysts, and applications in pharmaceutical synthesis.",
        "keywords": "Knoevenagel; condensation; catalysis; green chemistry",
        "source_type": "review",
        "language": "en",
    },
    {
        "title": "一种改进的布洛芬合成方法",
        "authors": "赵刚; 刘洋",
        "year": 2022,
        "journal": "CN Patent",
        "doi": "CN114560763A",
        "abstract": "公开了一种以异丁苯为原料，经 Friedel-Crafts 酰基化、Darzens 缩合、重排和水解四步合成布洛芬的方法，总收率可达 85%。",
        "keywords": "布洛芬; 合成; 专利; Friedel-Crafts",
        "source_type": "patent",
        "language": "zh",
    },
]

SEED_REACTIONS: list[dict] = [
    {
        "name": "Friedel-Crafts 酰基化",
        "reaction_type": "酰基化",
        "reactant_names": ["异丁苯", "乙酰氯"],
        "product_names": ["对异丁基苯乙酮"],
        "equation": "异丁苯 + 乙酰氯 → 对异丁基苯乙酮 + HCl（AlCl₃ 催化）",
        "catalyst": "AlCl₃（无水）",
        "solvent": "二氯甲烷",
        "temperature": "0-5°C",
        "reaction_time": "4h",
        "yield_percent": 92.0,
        "difficulty": 4,
        "safety_level": 6,
        "eco_score": 5,
        "cost_level": 7,
        "source": "patent",
    },
    {
        "name": "Knoevenagel 缩合（苯甲醛 → 肉桂酸）",
        "reaction_type": "缩合",
        "reactant_names": ["苯甲醛", "丙二酸"],
        "product_names": ["肉桂酸"],
        "equation": "苯甲醛 + 丙二酸 → 肉桂酸 + CO₂ + H₂O（哌啶催化）",
        "catalyst": "哌啶",
        "solvent": "吡啶",
        "temperature": "80°C（回流）",
        "reaction_time": "3h",
        "yield_percent": 85.0,
        "difficulty": 3,
        "safety_level": 8,
        "eco_score": 7,
        "cost_level": 8,
        "source": "paper",
    },
    {
        "name": "布洛芬最终水解",
        "reaction_type": "水解",
        "reactant_names": [],  # 中间体略
        "product_names": ["布洛芬"],
        "equation": "腈基中间体 → 布洛芬（酸性水解）",
        "catalyst": "H₂SO₄（稀）",
        "solvent": "水/乙醇",
        "temperature": "100°C（回流）",
        "reaction_time": "6h",
        "yield_percent": 88.0,
        "difficulty": 2,
        "safety_level": 7,
        "eco_score": 6,
        "cost_level": 8,
        "source": "patent",
    },
]


# ═══════════════════════════════════════════════════════════════════════════
# 关系数据库种子
# ═══════════════════════════════════════════════════════════════════════════

def _resolve_compound_ids(session: Session, names: list[str]) -> list[int]:
    """根据名称列表查找化合物 ID。"""
    ids = []
    for name in names:
        compound = session.exec(
            select(Compound).where(Compound.name == name)
        ).first()
        if compound:
            ids.append(compound.id)
    return ids


def seed_relational() -> dict[str, int]:
    """向关系数据库写入示例数据（幂等：按唯一字段跳过已存在的记录）。"""
    counts = {"compounds": 0, "literatures": 0, "reactions": 0}

    with Session(engine) as session:
        # ---- 1. 化合物 ----
        for item in SEED_COMPOUNDS:
            existing = session.exec(
                select(Compound).where(Compound.cas == item["cas"])
            ).first()
            if existing:
                logger.debug("化合物已存在，跳过: %s", item["name"])
                continue
            compound = Compound(**item)
            session.add(compound)
            counts["compounds"] += 1

        session.commit()

        # ---- 2. 文献 ----
        for item in SEED_LITERATURE:
            existing = session.exec(
                select(Literature).where(Literature.doi == item["doi"])
            ).first()
            if existing:
                logger.debug("文献已存在，跳过: %s", item["title"])
                continue
            lit = Literature(**item)
            session.add(lit)
            counts["literatures"] += 1

        session.commit()

        # ---- 3. 反应 ----
        for item in SEED_REACTIONS:
            existing = session.exec(
                select(Reaction).where(
                    Reaction.name == item["name"],
                    Reaction.source == item["source"],
                )
            ).first()
            if existing:
                logger.debug("反应已存在，跳过: %s", item["name"])
                continue

            # 解析化合物名称 → ID
            reactant_ids = _resolve_compound_ids(session, item.pop("reactant_names", []))
            product_ids = _resolve_compound_ids(session, item.pop("product_names", []))

            import json
            reaction = Reaction(
                **item,
                reactant_ids=json.dumps(reactant_ids, ensure_ascii=False),
                product_ids=json.dumps(product_ids, ensure_ascii=False),
            )
            session.add(reaction)
            counts["reactions"] += 1

        session.commit()

    return counts


# ═══════════════════════════════════════════════════════════════════════════
# Neo4j 知识图谱种子
# ═══════════════════════════════════════════════════════════════════════════

def seed_neo4j() -> int:
    """在 Neo4j 中创建化学知识图谱节点与关系（幂等）。"""
    if not neo4j_available():
        logger.warning("Neo4j 不可用，跳过图谱种子。")
        return 0

    with neo4j_session() as n4j:
        # 创建约束（幂等）
        n4j.run("CREATE CONSTRAINT IF NOT EXISTS FOR (c:Compound) REQUIRE c.name IS UNIQUE")
        n4j.run("CREATE CONSTRAINT IF NOT EXISTS FOR (r:Reaction) REQUIRE r.name IS UNIQUE")

        # ---- 化合物节点 ----
        for item in SEED_COMPOUNDS:
            n4j.run(
                """
                MERGE (c:Compound {name: $name})
                SET c.cas = $cas,
                    c.smiles = $smiles,
                    c.molecular_formula = $molecular_formula,
                    c.molecular_weight = $molecular_weight,
                    c.compound_class = $compound_class
                """,
                name=item["name"],
                cas=item.get("cas"),
                smiles=item.get("smiles"),
                molecular_formula=item.get("molecular_formula"),
                molecular_weight=item.get("molecular_weight"),
                compound_class=item.get("compound_class"),
            )

        # ---- 反应节点 + 关系 ----
        for item in SEED_REACTIONS:
            n4j.run(
                """
                MERGE (r:Reaction {name: $name})
                SET r.reaction_type = $reaction_type,
                    r.catalyst = $catalyst,
                    r.solvent = $solvent,
                    r.temperature = $temperature,
                    r.reaction_time = $reaction_time,
                    r.yield_percent = $yield_percent
                """,
                name=item["name"],
                reaction_type=item.get("reaction_type"),
                catalyst=item.get("catalyst"),
                solvent=item.get("solvent"),
                temperature=item.get("temperature"),
                reaction_time=item.get("reaction_time"),
                yield_percent=item.get("yield_percent"),
            )

            # 反应物 → 反应 (PARTICIPATES_IN)
            for r_name in item.get("reactant_names", []):
                n4j.run(
                    """
                    MATCH (c:Compound {name: $compound_name})
                    MATCH (r:Reaction {name: $reaction_name})
                    MERGE (c)-[:PARTICIPATES_IN {role: 'reactant'}]->(r)
                    """,
                    compound_name=r_name,
                    reaction_name=item["name"],
                )

            # 反应 → 产物 (PRODUCES)
            for p_name in item.get("product_names", []):
                n4j.run(
                    """
                    MATCH (r:Reaction {name: $reaction_name})
                    MATCH (c:Compound {name: $compound_name})
                    MERGE (r)-[:PRODUCES {is_main: true}]->(c)
                    """,
                    reaction_name=item["name"],
                    compound_name=p_name,
                )

    return len(SEED_COMPOUNDS) + len(SEED_REACTIONS)


# ═══════════════════════════════════════════════════════════════════════════
# 验证
# ═══════════════════════════════════════════════════════════════════════════

def verify() -> None:
    """验证种子数据是否正确写入。"""
    with Session(engine) as session:
        compounds = session.exec(select(Compound)).all()
        reactions = session.exec(select(Reaction)).all()
        literatures = session.exec(select(Literature)).all()

        print(f"\n{'='*50}")
        print("数据库验证")
        print(f"{'='*50}")
        print(f"化合物: {len(compounds)} 条")
        for c in compounds:
            print(f"  - [{c.id}] {c.name} (CAS: {c.cas}, {c.molecular_formula})")
        print(f"反应:   {len(reactions)} 条")
        for r in reactions:
            print(f"  - [{r.id}] {r.name} (收率: {r.yield_percent}%)")
        print(f"文献:   {len(literatures)} 条")
        for l in literatures:
            print(f"  - [{l.id}] {l.title[:50]}...")

        # 验证关系数据
        if reactions:
            import json
            r = reactions[0]
            print(f"\n关系验证（以 '{r.name}' 为例）:")
            print(f"  reactant_ids: {r.reactant_ids}")
            print(f"  product_ids:  {r.product_ids}")


# ═══════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(description="化学数据库种子脚本")
    parser.add_argument(
        "--neo4j",
        action="store_true",
        help="同时写入 Neo4j 知识图谱",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="仅验证，不写入数据",
    )
    args = parser.parse_args()

    if args.verify:
        verify()
        return

    print("写入关系数据库...")
    counts = seed_relational()
    print(f"  化合物: {counts['compounds']} 条（新增）")
    print(f"  反应:   {counts['reactions']} 条（新增）")
    print(f"  文献:   {counts['literatures']} 条（新增）")

    if args.neo4j:
        print("\n写入 Neo4j 知识图谱...")
        kg_count = seed_neo4j()
        print(f"  节点/关系: {kg_count} 个")

    print("\n验证写入结果:")
    verify()


if __name__ == "__main__":
    main()
