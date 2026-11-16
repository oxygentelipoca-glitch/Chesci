import asyncio
import os
import sys
from pathlib import Path

from datasets import Dataset
from dotenv import load_dotenv
from openai import OpenAI

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from ragas import evaluate
from ragas.embeddings.base import BaseRagasEmbedding
from ragas.llms import llm_factory
from ragas.metrics import answer_correctness, answer_relevancy, faithfulness
from sentence_transformers import SentenceTransformer

from app.services.rag_service import ask_question, search_knowledge


load_dotenv()


class SentenceTransformerEmbeddings(BaseRagasEmbedding):
    def __init__(self, model_name: str = "BAAI/bge-base-zh-v1.5"):
        super().__init__()
        self._model = SentenceTransformer(model_name, local_files_only=True)
        self.model = model_name

    def embed_text(self, text: str, **kwargs):
        return self._embed_text(text)

    async def aembed_text(self, text: str, **kwargs):
        return await asyncio.to_thread(self._embed_text, text)

    def embed_query(self, text: str):
        return self.embed_text(text)

    def embed_documents(self, texts):
        return [self.embed_text(text) for text in texts]

    async def aembed_query(self, text: str):
        return await self.aembed_text(text)

    async def aembed_documents(self, texts):
        return [await self.aembed_text(text) for text in texts]

    def _embed_text(self, text: str):
        return self._model.encode(text, normalize_embeddings=True).tolist()

    def _embed_texts(self, texts):
        return [self._embed_text(text) for text in texts]


def build_eval_dataset() -> Dataset:
    samples = [
        {"question": "1. 恐龙最早出现在什么时候？", "reference": "恐龙最早出现在大约2.45亿年前，中三叠纪开始时。"},
        {"question": "2. 恐龙在地球上繁衍了大约多长时间？", "reference": "恐龙在全球范围内繁衍了近1.8亿年。"},
        {"question": "3. 恐龙为什么被称为“恐怖的蜥蜴”？", "reference": "因为欧文将它们命名为“恐怖的蜥蜴”，意思是恐怖的或极其巨大的蜥蜴。"},
        {"question": "4. 恐龙这个名称是谁创造的？", "reference": "恐龙这个名称是英国古生物学家理查德·欧文创造的。"},
        {"question": "5. 理查德·欧文在哪一年提出了恐龙这一名称？", "reference": "理查德·欧文在1841年提出了恐龙这一名称。"},
        {"question": "6. Dinosauria这个拉丁名称由哪些词根组成？", "reference": "Dinosauria由deinos和sauros两个词根组成。"},
        {"question": "7. deinos和sauros分别是什么意思？", "reference": "deinos意思是“恐怖的”或“极其巨大的”，sauros意思是“蜥蜴”。"},
        {"question": "8. 中国“恐龙”这个名称是如何翻译来的？", "reference": "中国把这个拉丁名称翻译成了“恐龙”，最初由中国地质学家章鸿钊从日语翻译中引入并提出。"},
        {"question": "9. 恐龙属于哪个生物界？", "reference": "恐龙属于动物界。"},
        {"question": "10. 恐龙属于哪个门？", "reference": "恐龙属于脊索动物门。"},
        {"question": "11. 恐龙的拉丁学名是什么？", "reference": "恐龙的拉丁学名是Dinosauria。"},
        {"question": "12. 恐龙主要分为哪两个目？", "reference": "恐龙主要分为鸟臀目和蜥臀目。"},
        {"question": "13. 恐龙的生存时代是什么时期？", "reference": "恐龙的生存时代是中晚三叠世至白垩纪末。"},
        {"question": "14. 恐龙为什么能够成为中生代陆地动物的主要形式？", "reference": "因为它们在中生代时期广泛分布、种类繁多，并在陆地生态系统中占据主导地位。"},
        {"question": "15. 恐龙化石主要保存在哪类岩石中？", "reference": "恐龙化石主要保存于沉积岩层中。"},
        {"question": "16. 第一个发现恐龙化石的人是谁？", "reference": "第一个发现恐龙化石的是英国医师吉迪昂·曼特尔。"},
        {"question": "17. 曼特尔发现禽龙有什么意义？", "reference": "曼特尔发现禽龙并与鬣蜥对比后，科学界才初步确定它们是一种类似蜥蜴的、早已灭绝的爬行动物。"},
        {"question": "18. 早期欧洲人为什么认为巨大骨骼是巨人的遗骸？", "reference": "因为当时人们并不知道这些巨大骨骼是古生物化石，因此误认为是巨人的遗骸。"},
        {"question": "19. 自贡为什么被称为“恐龙之乡”？", "reference": "因为在自贡发现了大量恐龙化石，具有重要的恐龙化石研究价值。"},
        {"question": "20. 自贡恐龙化石群是什么时候发现的？", "reference": "1915年，美国加利福尼亚大学地质学家乔治·D·劳德伯克博士和R·R·莫斯博士在自贡发现恐龙化石。"},
        {"question": "21. 自贡恐龙化石群有什么重要价值？", "reference": "自贡恐龙化石群为研究中国恐龙多样性和演化提供了重要材料。"},
        {"question": "22. 1915年谁在中国发现了恐龙化石？", "reference": "1915年，乔治·D·劳德伯克博士和R·R·莫斯博士在自贡发现了恐龙化石。"},
        {"question": "23. 2022年云南大学发现了哪种有甲类恐龙？", "reference": "2022年云南大学发现的是科氏玉溪龙。"},
        {"question": "24. 科氏玉溪龙发现于哪里？", "reference": "科氏玉溪龙是在云南发现的。"},
        {"question": "25. 穆桑戈·马图萨多纳龙在哪里被发现？", "reference": "穆桑戈·马图萨多纳龙是在津巴布韦北部卡里巴湖附近发现的。"},
        {"question": "26. 恐龙的定义是什么？", "reference": "根据定义，恐龙指的是三角龙和现代鸟类最近共同祖先的全部后代，除鸟类外已全部灭绝。"},
        {"question": "27. 恐龙与现代鸟类有什么关系？", "reference": "现代鸟类是恐龙的后代。"},
        {"question": "28. 哪一类恐龙进化成了鸟类？", "reference": "一支恐龙谱系演化成了鸟类。"},
        {"question": "29. 恐龙演化成鸟类过程中尾骨发生了什么变化？", "reference": "恐龙演化成鸟类过程中尾骨缩短。"},
        {"question": "30. 恐龙有哪些主要形态特征？", "reference": "恐龙常具有四肢矫健、长尾巴、庞大身躯等形态特征。"},
        {"question": "31. 非鸟恐龙常见的身体结构有哪些？", "reference": "非鸟恐龙常见的身体结构包括强壮四肢、长尾巴和庞大身躯。"},
        {"question": "32. 恐龙主要生活在哪些环境中？", "reference": "恐龙主要生活在湖岸平原或海岸平原上的森林和开阔地带。"},
        {"question": "33. 恐龙最大的特点之一是什么？", "reference": "恐龙最大的特点之一是它们具有直立姿态和高效的行走方式。"},
        {"question": "34. 蜥脚类恐龙为什么被称为巨无霸？", "reference": "因为蜥脚类恐龙是体型非常巨大的恐龙，常被称为恐龙中的巨无霸。"},
        {"question": "35. 最大的恐龙之一长颈巨龙有什么特点？", "reference": "长颈巨龙体型巨大，化石骨架高12米、长22.5米，活体重量估计在30到60吨之间。"},
        {"question": "36. 长颈巨龙的化石在哪里发现？", "reference": "长颈巨龙的化石是在坦桑尼亚发现的。"},
        {"question": "37. 梁龙为什么被认为是最长的恐龙之一？", "reference": "因为梁龙的体长可达27米，被认为是最长的恐龙之一。"},
        {"question": "38. 恐龙骨骼有哪些特殊适应？", "reference": "恐龙骨骼具有强壮的腿骨和薄壁长骨等结构，适合承重和提高运动效率。"},
        {"question": "39. 大型植食性恐龙如何减轻骨骼重量？", "reference": "大型植食性恐龙通过演化出轻质骨骼结构来减轻骨骼重量。"},
        {"question": "40. 薄壁长骨有什么作用？", "reference": "薄壁长骨可以减轻重量，提高奔跑时的速度。"},
        {"question": "41. 恐龙和其他爬行动物最大的区别是什么？", "reference": "恐龙与其他爬行动物最大的区别在于它们具有直立姿态和行进方式。"},
        {"question": "42. 恐龙为什么能够直立行走？", "reference": "因为恐龙的四肢构建在躯体的正下方，能够稳定支撑身体。"},
        {"question": "43. 蜥臀目和鸟臀目的主要区别是什么？", "reference": "两者的主要区别在于骨盆结构，蜥臀目耻骨向前突出，鸟臀目耻骨向后倾斜。"},
        {"question": "44. 蜥臀目的腰带有什么特点？", "reference": "蜥臀目的腰带从侧面看是三射型，耻骨向前延伸。"},
        {"question": "45. 鸟臀目的腰带有什么特点？", "reference": "鸟臀目的腰带从侧面看是四射型，耻骨向后延伸。"},
        {"question": "46. 蜥脚形类恐龙有哪些典型特征？", "reference": "蜥脚形类恐龙头小、脖子长、尾巴长、牙齿成小匙状，通常是大型素食恐龙。"},
        {"question": "47. 马门溪龙属于哪一类恐龙？", "reference": "马门溪龙属于蜥脚亚目恐龙。"},
        {"question": "48. 兽脚类恐龙有哪些特点？", "reference": "兽脚类恐龙大多为肉食性，两足行走，趾端长有锐利爪子，头部很发达。"},
        {"question": "49. 暴龙属于哪个分类？", "reference": "暴龙属于兽脚亚目中的暴龙科。"},
        {"question": "50. 肉食性恐龙如何捕猎？", "reference": "肉食性恐龙主要依靠牙齿和爪子捕猎，常常单独行动。"},
        {"question": "51. 草食性恐龙如何防御肉食性恐龙？", "reference": "草食性恐龙会用皮甲、骨棒、骨钉和强壮尾巴进行防御。"},
        {"question": "52. 为什么有些恐龙会群体行动？", "reference": "有些恐龙会群体行动，以便协同防御或捕猎。"},
        {"question": "53. 恐龙主要吃什么食物？", "reference": "恐龙主要有草食性和肉食性两类，分别以植物和其他动物为食。"},
        {"question": "54. 恐龙的牙齿能够反映什么信息？", "reference": "恐龙的牙齿能够反映它们的觅食方式和生态位。"},
        {"question": "55. 恐龙是如何繁殖后代的？", "reference": "恐龙主要通过产卵和孵蛋繁殖后代。"},
        {"question": "56. 恐龙蛋属于什么类型的蛋？", "reference": "恐龙蛋属于羊膜卵。"},
        {"question": "57. 羊膜卵有什么优势？", "reference": "羊膜卵在陆地上不会干涸和失水，胚胎更安全。"},
        {"question": "58. 最初发现的恐龙蛋属于哪种恐龙？", "reference": "最初发现的恐龙蛋是原角龙的蛋。"},
        {"question": "59. 恐龙蛋通常有多大？", "reference": "恐龙蛋通常直径在10厘米到15厘米之间。"},
        {"question": "60. 河南西峡发现的恐龙蛋有什么特点？", "reference": "河南西峡发现的一种恐龙蛋化石长直径达30厘米，短直径12厘米。"},
        {"question": "61. 为什么恐龙蛋化石很难确定来源？", "reference": "因为世界各地发现的恐龙蛋数量很多，但其中绝大多数无法确定属于哪种恐龙。"},
        {"question": "62. 恐龙是否会孵蛋？", "reference": "科学家认为恐龙会孵蛋。"},
        {"question": "63. 哪些发现证明恐龙可能会照顾后代？", "reference": "发现孵蛋化石和巢穴说明恐龙可能会照顾后代。"},
        {"question": "64. 恐龙有哪些主要分类？", "reference": "恐龙主要分为蜥臀目和鸟臀目两大类。"},
        {"question": "65. 蜥臀目包括哪些亚类？", "reference": "蜥臀目包括兽脚亚目和蜥脚亚目。"},
        {"question": "66. 兽脚亚目有哪些代表恐龙？", "reference": "兽脚亚目有暴龙、异特龙、南方巨兽龙和棘龙等。"},
        {"question": "67. 暴龙科有哪些特点？", "reference": "暴龙科恐龙通常体型巨大、头部发达、属于肉食性恐龙。"},
        {"question": "68. 似鸟龙科有什么特点？", "reference": "似鸟龙科是体型较小、行动敏捷的小型兽脚类恐龙。"},
        {"question": "69. 窃蛋龙科的代表是什么？", "reference": "窃蛋龙科的代表是窃蛋龙。"},
        {"question": "70. 蜥脚亚目有哪些代表恐龙？", "reference": "蜥脚亚目代表有马门溪龙和易碎双腔龙等。"},
        {"question": "71. 鸟臀目包括哪些主要分类？", "reference": "鸟臀目包括角龙亚目、鸭嘴龙科、甲龙亚目、剑龙亚目和肿头龙亚目。"},
        {"question": "72. 角龙亚目的代表有哪些？", "reference": "角龙亚目代表有角龙和三角龙。"},
        {"question": "73. 鸭嘴龙科有哪些代表？", "reference": "鸭嘴龙科的代表是鸭嘴龙。"},
        {"question": "74. 甲龙亚目有什么特点？", "reference": "甲龙亚目恐龙身披甲板和骨刺，具有明显装甲。"},
        {"question": "75. 剑龙亚目有哪些代表？", "reference": "剑龙亚目代表有剑龙。"},
        {"question": "76. 肿头龙亚目有什么特点？", "reference": "肿头龙亚目以头骨特别大而著称。"},
        {"question": "77. 科学家如何通过化石研究恐龙？", "reference": "科学家通过研究骨骼、化石、足迹和蛋化石来了解恐龙。"},
        {"question": "78. 恐龙化石可以分为哪两类？", "reference": "恐龙化石主要分为骨骼化石和蛋化石。"},
        {"question": "79. 恐龙足迹研究有什么意义？", "reference": "恐龙足迹研究可以帮助了解其活动方式和行为。"},
        {"question": "80. 广西东兴发现的恐龙足迹属于哪类恐龙？", "reference": "广西东兴发现的恐龙足迹属于兽脚类恐龙。"},
        {"question": "81. 恐龙DNA复活是否容易实现？", "reference": "恐龙DNA复活并不容易，因为DNA保存条件极差。"},
        {"question": "82. 人工智能和基因编辑是否可能帮助研究恐龙？", "reference": "人工智能和基因编辑可能有助于研究恐龙，但仍面临很大技术限制。"},
        {"question": "83. 非鸟恐龙为什么灭绝？", "reference": "非鸟恐龙灭绝原因复杂，可能与环境变化和大规模灾变有关。"},
        {"question": "84. 白垩纪末期发生了什么重大事件？", "reference": "白垩纪末期发生了大规模灭绝事件。"},
        {"question": "85. 恐龙灭绝有哪些主要假说？", "reference": "恐龙灭绝有小行星撞击说、火山爆发说、气候变化说、海洋退潮说和造山运动说等。"},
        {"question": "86. 小行星撞击说的依据是什么？", "reference": "小行星撞击说依据是铱元素异常、撞击坑和火山灰层。"},
        {"question": "87. 白垩纪末期铱元素异常说明了什么？", "reference": "白垩纪末期铱元素异常说明地球遭遇了外来物体撞击。"},
        {"question": "88. 小行星撞击可能造成哪些环境变化？", "reference": "小行星撞击可能造成黑暗、寒冷、生态崩溃和食物短缺。"},
        {"question": "89. 火山爆发说认为恐龙灭绝的原因是什么？", "reference": "火山爆发说认为火山活动造成气候恶化和生态破坏。"},
        {"question": "90. 气候变化说如何解释恐龙灭绝？", "reference": "气候变化说认为气温和环境变化使恐龙难以适应。"},
        {"question": "91. 海洋退潮说的主要观点是什么？", "reference": "海洋退潮说认为海平面变化改变了生态系统并影响恐龙生存。"},
        {"question": "92. 造山运动说如何解释恐龙灭绝？", "reference": "造山运动说认为地壳抬升和环境改变对恐龙构成压力。"},
        {"question": "93. 恐龙到底是冷血动物还是温血动物？", "reference": "目前普遍认为恐龙可能介于冷血和温血之间。"},
        {"question": "94. 恐龙的新陈代谢有什么特点？", "reference": "恐龙的新陈代谢可能较高，具有较强的活动能力。"},
        {"question": "95. 恐龙与鸟类有哪些共同点？", "reference": "恐龙与鸟类有亲缘关系，并且有许多共同的骨骼和行为特征。"},
        {"question": "96. 恐龙与鳄鱼有什么关系？", "reference": "恐龙与鳄鱼都属于爬行动物，但它们的亲缘关系并不如恐龙与鸟类那样近。"},
        {"question": "97. 始祖鸟为什么被认为与恐龙关系密切？", "reference": "始祖鸟具有许多恐龙特征，因此被认为与恐龙关系密切。"},
        {"question": "98. 华丽羽王龙有什么特殊之处？", "reference": "华丽羽王龙因其羽毛和飞行相关特征而备受关注。"},
        {"question": "99. 未来科学技术是否可能制造类似恐龙的生物？", "reference": "未来科学技术可能在一定程度上重建类恐龙生物，但仍面临巨大技术挑战。"},
        {"question": "100. 恐龙研究为什么需要不断更新认识？", "reference": "因为新的化石发现和研究方法会不断更新人们对恐龙的认识。"},
    ]

    rows = []
    for sample in samples:
        question = sample["question"]
        result = ask_question(question, user_id=None)
        retrieved = search_knowledge(question, user_id=None)
        rows.append(
            {
                "user_input": question,
                "response": result["answer"],
                "reference": sample["reference"],
                "retrieved_contexts": retrieved["documents"],
            }
        )

    return Dataset.from_list(rows)


def main() -> None:
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY is not configured")

    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
    llm = llm_factory("deepseek-chat", provider="openai", client=client)
    embeddings = SentenceTransformerEmbeddings()
    faithfulness_metric = faithfulness
    faithfulness_metric.llm = llm
    answer_relevancy_metric = answer_relevancy
    answer_relevancy_metric.llm = llm
    answer_relevancy_metric.embeddings = embeddings
    answer_correctness_metric = answer_correctness
    answer_correctness_metric.llm = llm
    answer_correctness_metric.embeddings = embeddings

    dataset = build_eval_dataset()
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

    output_path = Path("eval_results.json")
    output_path.write_text(
        results.to_pandas().to_json(orient="records", force_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Evaluation complete. Results saved to {output_path}")
    print(results)


if __name__ == "__main__":
    main()
