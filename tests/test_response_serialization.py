import json
import unittest
from datetime import datetime

from app.core.response import api_success


class ResponseSerializationTests(unittest.TestCase):
    def test_api_success_serializes_datetime_values(self):
        response = api_success(
            "ok",
            {
                "created_at": datetime(2024, 1, 2, 3, 4, 5),
                "nested": [{"updated_at": datetime(2024, 1, 2, 3, 4, 6)}],
            },
        )

        payload = json.loads(response.body.decode("utf-8"))

        self.assertEqual(payload["data"]["created_at"], "2024-01-02T03:04:05")
        self.assertEqual(payload["data"]["nested"][0]["updated_at"], "2024-01-02T03:04:06")


if __name__ == "__main__":
    unittest.main()
