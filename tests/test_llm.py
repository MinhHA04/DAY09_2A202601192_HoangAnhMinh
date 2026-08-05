from __future__ import annotations

import json
import unittest
from types import SimpleNamespace

from ecommerce_agents.llm import ModelReviewPayload, ModelUsage, OpenAIModelClient


class ModelResponseParsingTests(unittest.TestCase):
    def test_markdown_fenced_json_is_parsed(self) -> None:
        text = '```json\n{"status":"accepted","summary":"ok","observations":[]}\n```'
        self.assertEqual(OpenAIModelClient._parse_json(text)["status"], "accepted")

    def test_double_encoded_json_is_parsed(self) -> None:
        payload = {"status": "accepted", "summary": "ok", "observations": []}
        text = json.dumps(json.dumps(payload))
        self.assertEqual(OpenAIModelClient._parse_json(text), payload)

    def test_agent_prompt_uses_authoritative_review_protocol(self) -> None:
        instructions = OpenAIModelClient._instructions("delivery_agent")
        self.assertIn("copy required_status exactly", instructions)
        self.assertIn("Positive or negative variance is valid", instructions)
        self.assertIn("Do not recalculate", instructions)

    def test_review_uses_structured_outputs(self) -> None:
        captured: dict = {}

        class FakeResponses:
            def parse(self, **kwargs):
                captured.update(kwargs)
                return SimpleNamespace(
                    output_parsed=ModelReviewPayload(
                        status="accepted",
                        summary="Dữ liệu nhất quán.",
                        observations=[],
                    ),
                    output_text='{"status":"accepted"}',
                    usage=SimpleNamespace(input_tokens=10, output_tokens=5),
                    _request_id="req_test",
                )

        client = OpenAIModelClient.__new__(OpenAIModelClient)
        client._client = SimpleNamespace(responses=FakeResponses())
        client.usage = ModelUsage()
        result = client.review("customer_agent", "Review customer.", {})

        self.assertIs(captured["text_format"], ModelReviewPayload)
        self.assertEqual(captured["temperature"], 0)
        model_input = json.loads(captured["input"])
        self.assertEqual(
            model_input["review_protocol"],
            {
                "deterministic_validation": "passed",
                "required_status": "accepted",
            },
        )
        self.assertEqual(result["status"], "accepted")
        self.assertEqual(result["request_id"], "req_test")
        self.assertEqual(client.usage.as_dict(), {
            "request_count": 1,
            "input_tokens": 10,
            "output_tokens": 5,
        })


if __name__ == "__main__":
    unittest.main()
