import unittest

from utils.text_splitter import split_text


class TextSplitterTests(unittest.TestCase):
    def test_retains_section_and_chunk_metadata(self):
        chunks = split_text(
            [
                {
                    "text": "资料说明\n\n一、积分规则\n每消费一元积一分。\n\n二、退款规则\n审核通过后退款。",
                    "filename": "policy.txt",
                    "stored_filename": "policy.txt",
                    "user_id": "system",
                }
            ]
        )

        self.assertGreaterEqual(len(chunks), 2)
        self.assertEqual(chunks[0]["section_title"], "文档摘要")
        self.assertEqual(chunks[1]["section_title"], "积分规则")
        self.assertEqual([chunk["chunk_index"] for chunk in chunks], list(range(len(chunks))))
        self.assertTrue(chunks[1]["text"].startswith("【积分规则】"))


if __name__ == "__main__":
    unittest.main()
