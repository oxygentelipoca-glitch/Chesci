"""混合检索 RAG 问答演示脚本。

直接运行即可体验完整的混合检索 RAG 管道：
Dense (BGE) + BM25 → RRF Fusion → Reranker → DeepSeek 回答。

依赖 ``app/services/rag_service.py`` 中已实现的 ``ask_question`` 函数。
"""

import sys
from pathlib import Path

# 确保项目根目录在 sys.path 中，使 app 包可导入
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.rag_service import ask_question, retrieval_status


def print_status() -> None:
    """打印当前检索管线状态。"""
    status = retrieval_status()
    reranker = status["reranker"]
    thresholds = status["thresholds"]
    weights = status["weights"]

    print("=" * 50)
    print("RAG 管线状态")
    print("=" * 50)
    print(f"  LLM           : deepseek-chat")
    print(f"  Reranker 模型 : {reranker['model']}")
    print(f"  Reranker 可用 : {'是' if reranker['available'] else '否（回退到融合排序）'}")
    if reranker["detail"]:
        print(f"  原因          : {reranker['detail']}")
    print(f"  稠密距离阈值  : {thresholds['max_dense_distance']}")
    print(f"  BM25 分数阈值 : {thresholds['min_bm25_score']}")
    print(f"  默认权重      : dense={weights['dense']}, sparse={weights['sparse']}")
    print()


def main() -> None:
    print_status()

    while True:
        try:
            question = input("\n请输入问题（输入 exit 退出）: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n退出程序")
            break

        if not question:
            continue
        if question.lower() == "exit":
            print("退出程序")
            break

        # 调用完整的 RAG 管道（混合检索 + LLM 回答）
        result = ask_question(
            question,
            user_id=None,            # None = 同时搜索 system 和用户文档
            adaptive=True,           # 自适应权重：精确查询偏 BM25，语义查询偏向量
            include_debug=True,      # 返回调试信息
        )

        print("\n" + "=" * 50)
        print("AI 回答")
        print("=" * 50)
        print(result["answer"])

        # 显示来源和检索详情
        retrieval = result.get("retrieval", {})
        has_context = retrieval.get("has_sufficient_context", True)
        print(f"\n上下文充足: {has_context}")

        if result.get("citations"):
            print("\n引用片段:")
            for i, citation in enumerate(result["citations"]):
                print(f"  [{i+1}] {citation['section']} — {citation['preview'][:80]}...")

        if result.get("sources"):
            print(f"\n来源文件: {', '.join(result['sources'])}")

        # 调试信息
        debug = result.get("debug")
        if debug:
            print(f"\n[调试] 查询类型: {debug['query_type']}, "
                  f"权重: dense={debug['weights']['dense']}, bm25={debug['weights']['bm25']}")
            print(f"[调试] 候选: dense={debug['candidates']['dense']}, "
                  f"bm25={debug['candidates']['bm25']}, fused={debug['candidates']['fused']}")
            if debug["hits"]:
                print("[调试] 命中片段:")
                for hit in debug["hits"]:
                    print(f"  - {hit['filename']} | {hit['section']} "
                          f"| 通道: {'+'.join(hit['channels'])} | 分数: {hit['score']}")


if __name__ == "__main__":
    main()
