from __future__ import annotations

import unittest

from ecommerce_agents.agents import PolicyAgent


def base_reports() -> tuple[dict, dict, dict, dict]:
    order_product = {
        "order": {"order_id": "o1", "order_status": "delivered"},
        "items": [
            {"seller_id": "s1", "price": "10.00", "freight_value": "2.00"}
        ],
        "seller_ids": ["s1"],
        "policy_category_names": ["books"],
    }
    customer = {"related_order_ids": []}
    payment = {
        "rows": [{"payment_value": "12.00"}],
        "payment_total_brl": 12.0,
        "freight_total_brl": 2.0,
        "reconciled": True,
    }
    delivery = {
        "late_delivery": False,
        "late_handoff_seller_ids": [],
    }
    return order_product, customer, payment, delivery


class PolicyAgentTests(unittest.TestCase):
    def test_unsupported_late_claim(self) -> None:
        reports = base_reports()
        decision = PolicyAgent().decide(*reports)
        self.assertEqual(decision["primary_issue"], "unsupported_late_claim")
        self.assertEqual(decision["recommended_refund_brl"], 0.0)
        self.assertEqual(decision["case_status"], "no_action")

    def test_canceled_has_priority_and_full_refund(self) -> None:
        order_product, customer, payment, delivery = base_reports()
        order_product["order"]["order_status"] = "canceled"
        delivery["late_delivery"] = True
        delivery["late_handoff_seller_ids"] = ["s1"]
        decision = PolicyAgent().decide(order_product, customer, payment, delivery)
        self.assertEqual(decision["primary_issue"], "canceled_order_paid")
        self.assertEqual(decision["recommended_refund_brl"], 12.0)

    def test_valid_split_payment_precedes_supported_rejection(self) -> None:
        order_product, customer, payment, delivery = base_reports()
        payment["rows"].append({"payment_value": "1.00"})
        decision = PolicyAgent().decide(order_product, customer, payment, delivery)
        self.assertEqual(decision["primary_issue"], "valid_split_payment")
        self.assertNotIn("verify_payment_allocation", decision["resolution_actions"])

    def test_model_review_is_attached_to_handoff(self) -> None:
        class FakeModel:
            def review(self, agent_name: str, task: str, facts: dict) -> dict:
                return {"status": "accepted", "summary": agent_name, "observations": []}

        decision = PolicyAgent(FakeModel()).decide(*base_reports())
        self.assertEqual(decision["model_review"]["status"], "accepted")
        self.assertEqual(decision["model_review"]["summary"], "policy_agent")


if __name__ == "__main__":
    unittest.main()
