import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from app.chemistry.paper_import import extract_paper_preview


class PaperPreviewTests(unittest.TestCase):
    def test_wrong_page_for_yield_does_not_confirm_numeric_result(self):
        response = {"title": "Example", "authors": "", "source": "", "reactions": [
            {"reactants": ["A"], "products": ["B"], "temperature": "回流", "time": "5 h",
             "yield_value": "80%", "citations": [
                 {"field": "conditions", "page": 1, "quote": "under reflux"},
                 {"field": "yield", "page": 1, "quote": "entry B 80%"},
             ]}]}
        client = Mock()
        choice = SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content=json.dumps(response)))
        client.with_options.return_value.chat.completions.create.return_value.choices = [choice]
        result = extract_paper_preview(["under  reflux for 5 h", "entry B 80%"], client, "test")
        record = result["reactions"][0]
        self.assertIsNone(record["yield"])
        self.assertEqual(record["conditions"]["temperature"], "回流")
        self.assertEqual([c["page"] for c in record["paper_evidence"]], [1])
        self.assertTrue(result["warnings"])
