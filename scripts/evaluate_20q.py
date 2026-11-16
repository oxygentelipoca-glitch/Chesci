"""RAGAS 自动评估脚本 —— 用 20 个测试问题计算 faithfulness / answer_relevancy / answer_correctness。

用法：
    python scripts/evaluate_20q.py
"""

import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from datasets import Dataset
from dotenv import load_dotenv
from openai import OpenAI
from ragas import evaluate
from ragas.embeddings.base import BaseRagasEmbedding
from ragas.llms import llm_factory
from ragas.metrics import answer_correctness, answer_relevancy, faithfulness
from sentence_transformers import SentenceTransformer

from app.services.rag_service import ask_question, search_knowledge

load_dotenv()

# ---------------------------------------------------------------------------
# Embeddings wrapper (required by ragas)
# ---------------------------------------------------------------------------

class STEmbeddings(BaseRagasEmbedding):
    def __init__(self, model_name: str = "BAAI/bge-base-zh-v1.5"):
        super().__init__()
        self._model = SentenceTransformer(model_name, local_files_only=True)
        self.model = model_name

    def embed_text(self, text: str, **kwargs):
        return self._model.encode(text, normalize_embeddings=True).tolist()

    async def aembed_text(self, text: str, **kwargs):
        return await asyncio.to_thread(self.embed_text, text)

    def embed_query(self, text: str):
        return self.embed_text(text)

    def embed_documents(self, texts):
        return [self.embed_text(t) for t in texts]

    async def aembed_query(self, text: str):
        return await self.aembed_text(text)

    async def aembed_documents(self, texts):
        return [await self.aembed_text(t) for t in texts]


# ---------------------------------------------------------------------------
# 20 个测试问题（与 test_rag_questions.py 相同）
# ---------------------------------------------------------------------------

QUESTIONS = [
    {"question": "星河咖啡馆的营业时间是什么？", "reference": "每天 08:00 至 22:00"},
    {"question": "青提冷萃的售价和供应时间是什么？", "reference": "32 元，每年 5 月 1 日至 9 月 30 日"},
    {"question": "会员积分多久失效？", "reference": "到账之日起 12 个月"},
    {"question": "200 积分可以兑换什么？有效期多久？", "reference": "一张 20 元饮品券，有效期 30 天"},
    {"question": "中杯拿铁和大杯拿铁分别多少钱？", "reference": "中杯 26 元，大杯 30 元"},
    {"question": "累计消费多少可以升级为金卡？", "reference": "累计满 2000 元"},
    {"question": "配送费怎么算？什么条件可以免配送费？", "reference": "3 公里内 5 元，满 49 元免配送费"},
    {"question": "加一份浓缩咖啡需要多少钱？", "reference": "6 元"},
    {"question": "饮品漏洒了应该怎么处理？多久内可以反馈？", "reference": "取餐或签收后 2 小时内联系客服或提交反馈"},
    {"question": "生日券能兑换青提冷萃吗？能加钱升级大杯吗？", "reference": "不能兑换青提冷萃，不能升级大杯"},
    {"question": "金卡会员买一杯大杯燕麦拿铁，实际付多少钱？", "reference": "34 元打 9 折，30.6 元"},
    {"question": "退款审核通过后多久到账？通过什么渠道反馈质量问题？", "reference": "3 至 5 个工作日，客服电话或订单页面"},
    {"question": "18:00 以后还能买到火腿芝士三明治吗？", "reference": "不能，18:00 后不再制作热三明治"},
    {"question": "拿铁能不能换成雨林 SOE 单品豆？", "reference": "不能，雨林 SOE 只用于手冲及指定活动"},
    {"question": "燕麦拿铁能保证完全不含乳制品吗？为什么？", "reference": "不能保证，生产环境仍可能接触乳制品"},
    {"question": "外卖骑手已接单后取消订单，配送费能退吗？", "reference": "不能退还"},
    {"question": "星享会会员花 30 块买一杯饮品，能积多少分？", "reference": "30 分，每消费 1 元积 1 分"},
    {"question": "恶劣天气导致配送延迟，能索赔吗？", "reference": "不能，只协助催单不提供延迟赔付"},
    {"question": "日出拼配咖啡豆的风味是什么？有没有其他豆子可以选？", "reference": "坚果、可可、焦糖；雨林 SOE 仅限手冲"},
    {"question": "觉得咖啡太苦想退款，能退吗？", "reference": "不能，个人口味偏好不属于质量问题"},
]


def build_eval_dataset() -> Dataset:
    """对每个问题调用 RAG 管道，构建 ragas 数据集。"""
    rows = []
    for i, item in enumerate(QUESTIONS):
        question = item["question"]
        reference = item["reference"]
        print(f"  [{i+1:02d}/20] {question[:40]}...")

        result = ask_question(question, user_id=None, adaptive=True)
        retrieved = search_knowledge(question, user_id=None)

        rows.append({
            "user_input": question,
            "response": result["answer"],
            "reference": reference,
            "retrieved_contexts": retrieved["documents"],
        })
    return Dataset.from_list(rows)


def main() -> None:
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY is not configured")

    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
    llm = llm_factory("deepseek-chat", provider="openai", client=client)
    embeddings = STEmbeddings()

    # 配置各指标的 evaluator LLM
    faithfulness_metric = faithfulness
    faithfulness_metric.llm = llm

    answer_relevancy_metric = answer_relevancy
    answer_relevancy_metric.llm = llm
    answer_relevancy_metric.embeddings = embeddings

    answer_correctness_metric = answer_correctness
    answer_correctness_metric.llm = llm
    answer_correctness_metric.embeddings = embeddings

    print("正在构建评估数据集（20 个问题 × ask_question）...")
    dataset = build_eval_dataset()

    print("\n正在运行 RAGAS 评估...")
    results = evaluate(
        dataset,
        metrics=[
            faithfulness_metric,
            answer_relevancy_metric,
            answer_correctness_metric,
        ],
        llm=llm,
        embeddings=embeddings,
        show_progress=True,
    )

    # 输出
    df = results.to_pandas()
    print("\n" + "=" * 50)
    print("RAGAS 评估结果")
    print("=" * 50)
    print(df[["user_input", "faithfulness", "answer_relevancy", "answer_correctness"]].to_string())

    print("\n" + "=" * 50)
    print("汇总统计")
    print("=" * 50)
    for col in ["faithfulness", "answer_relevancy", "answer_correctness"]:
        if col in df.columns:
            vals = df[col].dropna()
            print(f"  {col:25s}  mean={vals.mean():.4f}  median={vals.median():.4f}  "
                  f"min={vals.min():.4f}  max={vals.max():.4f}")

    # 保存
    out_path = ROOT / "eval_20q_v3.json"
    out_path.write_text(
        df.to_json(orient="records", force_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n详细结果已保存到: {out_path}")


if __name__ == "__main__":
    main()
