"""混合检索演示脚本：Dense + BM25 → RRF Fusion → Reranker.

直接运行即可体验混合检索效果。依赖 ``app/services/rag_service.py`` 中
已实现的完整混合检索管道，包括自适应权重、噪声过滤和 Cross-Encoder 重排序。
"""

import sys
from pathlib import Path

# 确保项目根目录在 sys.path 中，使 app 包可导入
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.rag_service import search_knowledge, retrieval_status


def print_status() -> None:
    """打印当前检索管线状态（reranker 是否就绪、阈值等）。"""
    status = retrieval_status()
    reranker = status["reranker"]
    thresholds = status["thresholds"]
    weights = status["weights"]

    print("=" * 50)
    print("检索管线状态")
    print("=" * 50)
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

        # 调用混合检索（Dense + BM25 → RRF Fusion → Reranker）
        result = search_knowledge(
            question,
            user_id=None,           # None = 同时搜索 system 和用户文档
            include_debug=True,     # 返回调试信息（各通道候选数、权重等）
        )

        print("\n" + "=" * 50)
        print(f"检索结果（共 {len(result['documents'])} 条命中，"
              f"上下文充足: {result['has_sufficient_context']}）")
        print("=" * 50)

        if result["debug"]:
            debug = result["debug"]
            print(f"\n查询类型: {debug['query_type']}")
            print(f"自适应权重: dense={debug['weights']['dense']}, "
                  f"bm25={debug['weights']['bm25']}")
            print(f"候选数: dense={debug['candidates']['dense']}, "
                  f"bm25={debug['candidates']['bm25']}, fused={debug['candidates']['fused']}")

        if not result["documents"]:
            print("\n未检索到足够相关的资料。")
            print(f"  best_dense_distance: {result['best_dense_distance']}")
            print(f"  best_bm25_score: {result['best_bm25_score']}")
            continue

        print()
        for i, text in enumerate(result["documents"]):
            meta = result["metadatas"][i] if i < len(result["metadatas"]) else {}
            # 显示文件、章节、分数和命中通道
            file_info = meta.get("filename", "未知文件")
            section = meta.get("section_title", "—")
            score = result["scores"][i] if i < len(result["scores"]) else "—"

            channels_str = ""
            if result["debug"] and i < len(result["debug"]["hits"]):
                hit = result["debug"]["hits"][i]
                channels_str = f" | 通道: {'+'.join(hit['channels'])}"

            print(f"\n--- 结果 {i+1} ---")
            print(f"文件: {file_info} | 章节: {section}")
            print(f"分数: {score}{channels_str}")
            # 截取前 200 字符预览
            preview = text[:200].replace("\n", " ")
            print(f"内容: {preview}{'...' if len(text) > 200 else ''}")


if __name__ == "__main__":
    main()
