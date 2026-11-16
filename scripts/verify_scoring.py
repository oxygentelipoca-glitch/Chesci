"""快速验证：路线评分引擎。"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.chemistry.scoring import score_route, score_routes, format_scored_routes

print("=== 单条评分 ===")
r = score_route("Knoevenagel 缩合", yield_pct=85.0, difficulty_score=7, safety_score=8, environment_score=7, cost_score=8)
print(f"  {r.route_name}: {r.total_score}分 ({r.verdict})")
print(f"  归一化: yield={r.normalized['yield']:.0f} cost={r.normalized['cost']:.0f} safety={r.normalized['safety']:.0f} env={r.normalized['environment']:.0f} diff={r.normalized['difficulty']:.0f}")

print("\n=== 批量评分 + 排序 ===")
routes = [
    {"name": "路线A: Boots法", "yield": 88.0, "difficulty": 6, "safety": 7, "eco": 5, "cost": 7},
    {"name": "路线B: Hoechst法", "yield": 92.0, "difficulty": 5, "safety": 8, "eco": 8, "cost": 6},
    {"name": "路线C: 改进法", "yield": 75.0, "difficulty": 3, "safety": 9, "eco": 9, "cost": 8},
]
result = score_routes(routes)
print(result.summary)

print("\n=== 格式化输出（LLM 上下文）===")
print(format_scored_routes(result))

print("\n✅ 评分引擎验证通过")
