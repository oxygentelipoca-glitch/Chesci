#!/usr/bin/env python3
"""批量翻译 ReactionRecord 中的化学信息为中文（DeepSeek LLM）。

将 reaction_record 表中的 title、reactants、products 字段翻译为中文，
写入 title_cn、reactants_cn、products_cn 字段。

用法:
    python scripts/translate_reactions.py [--batch-size 20] [--limit 50]
"""

import json, os, sys, time
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from openai import OpenAI
from sqlmodel import Session, select
from app.database import engine
from app.chemistry.models import ReactionRecord

BATCH_SIZE = 20
TRANSLATE_PROMPT = """你是一位专业化学翻译。请将以下化学反应信息的标题和化合物名称翻译为中文。

规则：
1. 化学专有名词使用标准中文译名（如 cinnamic acid → 肉桂酸、pyridine → 吡啶）
2. 没有标准译名的保持英文原文
3. 返回严格 JSON 格式：{"title_cn": "...", "reactants_cn": "...", "products_cn": "..."}
4. reactants_cn 和 products_cn 是逗号分隔的中文名列表
"""


def translate_one(client, record) -> dict | None:
    """翻译单条反应记录（JSON mode 保证格式）。"""
    title = record.title or "Reaction"
    reactants = ", ".join(json.loads(record.reactants)) if record.reactants else ""
    products = ", ".join(json.loads(record.products)) if record.products else ""

    prompt = f"标题: {title}\n反应物: {reactants}\n产物: {products}"

    for attempt in range(2):
        try:
            response = client.chat.completions.create(
                model="deepseek-chat",
                temperature=0.1,
                max_tokens=500,
                messages=[
                    {"role": "system", "content": TRANSLATE_PROMPT},
                    {"role": "user", "content": f"请将以下化学反应信息翻译为中文，返回 JSON：\n\n{prompt}"},
                ],
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content or ""
            return json.loads(content)
        except Exception as e:
            if attempt == 1:
                return None
            time.sleep(1)
    return None


def main():
    client = OpenAI(
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
    )

    with Session(engine) as session:
        # 只翻译还没有中文的
        stmt = select(ReactionRecord).where(ReactionRecord.title_cn.is_(None))
        records = session.exec(stmt).all()
        total = len(records)
        print(f"待翻译: {total} 条")

        translated = 0
        for i, rec in enumerate(records):
            if i % 20 == 0:
                print(f"  [{i+1}/{total}] ...", end=" ", flush=True)
            result = translate_one(client, rec)
            if result:
                rec.title_cn = result.get("title_cn", "") or None
                rec.reactants_cn = result.get("reactants_cn", "") or None
                rec.products_cn = result.get("products_cn", "") or None
                session.add(rec)
                translated += 1
            if (i + 1) % 20 == 0:
                session.commit()
                print(f"OK ({translated} done)")
            time.sleep(0.15)
        session.commit()
        print(f"\n翻译完成: {translated}/{total}")


if __name__ == "__main__":
    main()
