from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

from ecommerce_agents.config import ARRAY_LIMITS
from ecommerce_agents.coordinator import CoordinatorAgent
from ecommerce_agents.llm import OfflineModelClient
from ecommerce_agents.repository import OlistRepository


class TraceCollector:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def emit(
        self,
        case_id: str,
        sender: str,
        recipient: str,
        event: str,
        payload: dict[str, Any],
    ) -> None:
        self.records.append(
            {
                "case_id": case_id,
                "sender": sender,
                "event": event,
                "payload": payload,
            }
        )


class ContextCompletenessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cases = [
            json.loads(path.read_text(encoding="utf-8-sig"))
            for path in sorted(Path("input").glob("EC_*.json"))
        ]
        order_ids = [
            case["customer_request"]["claimed_order_id"] for case in cls.cases
        ]
        cls.repository = OlistRepository("data", order_ids)

    def test_current_cases_fit_schema_limits_without_truncation(self) -> None:
        for case in self.cases:
            with self.subTest(case_id=case["case_id"]):
                order_id = case["customer_request"]["claimed_order_id"]
                items = self.repository.order_items(order_id)
                payments = self.repository.order_payments(order_id)
                related = self.repository.related_order_ids(order_id)
                product_ids = []
                seller_ids = []
                categories = []
                for item in items:
                    if item["seller_id"] not in seller_ids:
                        seller_ids.append(item["seller_id"])
                    if item["product_id"] not in product_ids:
                        product_ids.append(item["product_id"])
                for product_id in product_ids:
                    category = self.repository.product(product_id).get(
                        "product_category_name", ""
                    )
                    if category and category not in categories:
                        categories.append(category)

                self.assertLessEqual(len(items), ARRAY_LIMITS["item_ids"])
                self.assertLessEqual(len(payments), ARRAY_LIMITS["payment_ids"])
                self.assertLessEqual(len(seller_ids), ARRAY_LIMITS["seller_ids"])
                self.assertLessEqual(len(product_ids), ARRAY_LIMITS["product_ids"])
                self.assertLessEqual(len(categories), ARRAY_LIMITS["category_names"])
                self.assertLessEqual(len(related), ARRAY_LIMITS["related_order_ids"])

    def test_handoffs_match_output_context_for_current_cases(self) -> None:
        trace = TraceCollector()
        coordinator = CoordinatorAgent(
            self.repository, trace, OfflineModelClient()
        )
        for case in self.cases:
            with self.subTest(case_id=case["case_id"]):
                before = len(trace.records)
                result = coordinator.process(case)
                records = trace.records[before:]
                handoffs = {
                    row["sender"]: row["payload"]
                    for row in records
                    if row["event"] == "analysis_handoff"
                }
                customer = handoffs["customer_agent"]
                order_product = handoffs["order_product_agent"]
                payment = handoffs["payment_agent"]
                delivery = handoffs["delivery_agent"]

                self.assertEqual(
                    result["affected_entities"]["item_ids"],
                    order_product["item_ids"],
                )
                self.assertEqual(
                    result["affected_entities"]["seller_ids"],
                    order_product["seller_ids"],
                )
                self.assertEqual(
                    result["affected_entities"]["payment_ids"],
                    payment["payment_ids"],
                )
                self.assertEqual(
                    result["customer_context"]["related_order_ids"],
                    customer["related_order_ids"],
                )
                self.assertEqual(
                    result["product_context"]["product_ids"],
                    order_product["product_ids"],
                )
                self.assertEqual(
                    result["product_context"]["category_names"],
                    order_product["category_names"],
                )
                self.assertEqual(
                    result["delivery_analysis"]["seller_handoff_analysis"],
                    delivery["seller_handoff_analysis"],
                )


if __name__ == "__main__":
    unittest.main()
