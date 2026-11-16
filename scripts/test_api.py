#!/usr/bin/env python3
"""Quick API test for reactions.db data queries."""
import sys
sys.path.insert(0, '.')

from app.chemistry.reaction_parser import get_stats, list_schemes, list_reactions, get_graph_data
from app.chemistry.scoring import score_reaction, score_reactions_batch

# Test stats
stats = get_stats()
print(f"Stats: {stats}")

# Test schemes
result = list_schemes(limit=3)
print(f"Schemes total: {result['total']}")
for s in result['items']:
    print(f"  Scheme #{s['scheme_number']}: {s['reaction_count']} reactions, yield={s['overall_yield']}")

# Test reactions
result2 = list_reactions(limit=3)
print(f"Reactions total: {result2['total']}")
for r in result2['items']:
    print(f"  {r['cas_registry_id']}: yield={r['yield_']}, react={r['reactants_text']}, prod={r['products_text']}")

# Test graph data
graph = get_graph_data()
print(f"Graph: {len(graph['nodes'])} nodes, {len(graph['links'])} edges")

# Test scoring
scored = score_reactions_batch(limit=3)
print(f"Scored: {len(scored)} reactions")
for s in scored:
    print(f"  {s['cas_registry_id']}: total={s['total']}, yield={s['yield_score']}, safety={s['safety_score']}")

print("\n=== All tests passed ===")
