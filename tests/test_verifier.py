from __future__ import annotations

import copy
import unittest

from ecommerce_agents.agents import (
    CustomerAgent,
    DeliveryAgent,
    OrderProductAgent,
    PaymentAgent,
    PolicyAgent,
)
from ecommerce_agents.coordinator import CoordinatorAgent
from ecommerce_agents.verifier import VerificationError, VerifierAgent


class FakeRepository:
    order_row = {
        "order_id": "o1",
        "customer_id": "c1",
        "order_status": "delivered",
        "order_purchase_timestamp": "2018-01-01 08:00:00",
        "order_approved_at": "2018-01-01 09:00:00",
        "order_delivered_carrier_date": "2018-01-02 08:00:00",
        "order_delivered_customer_date": "2018-01-03 08:00:00",
        "order_estimated_delivery_date": "2018-01-04 00:00:00",
    }
    item_rows = [
        {
            "order_id": "o1",
            "order_item_id": "1",
            "product_id": "p1",
            "seller_id": "s1",
            "shipping_limit_date": "2018-01-02 12:00:00",
            "price": "10.00",
            "freight_value": "2.00",
        }
    ]
    payment_rows = [
        {
            "order_id": "o1",
            "payment_sequential": "1",
            "payment_type": "credit_card",
            "payment_installments": "1",
            "payment_value": "12.00",
        }
    ]

    def order(self, order_id: str) -> dict[str, str]:
        return dict(self.order_row)

    def order_items(self, order_id: str) -> list[dict[str, str]]:
        return [dict(row) for row in self.item_rows]

    def order_payments(self, order_id: str) -> list[dict[str, str]]:
        return [dict(row) for row in self.payment_rows]

    def customer_for_order(self, order_id: str) -> dict[str, str]:
        return {"customer_id": "c1", "customer_unique_id": "cu1"}

    def related_order_ids(self, order_id: str) -> list[str]:
        return []

    def product(self, product_id: str) -> dict[str, str]:
        return {"product_id": product_id, "product_category_name": "books"}

    def product_category_name(self, product_id: str) -> str:
        return "books"


class VerifierAgentTests(unittest.TestCase):
    scope = {
        "include_customer_history": True,
        "include_product_context": True,
    }

    def setUp(self) -> None:
        self.repository = FakeRepository()
        customer = CustomerAgent(self.repository).investigate("o1", True)
        order_product = OrderProductAgent(self.repository).investigate("o1", True)
        payment = PaymentAgent(self.repository).reconcile(
            "o1", order_product["items"]
        )
        delivery = DeliveryAgent().analyze(
            order_product["order"], order_product["items"]
        )
        decision = PolicyAgent().decide(
            order_product, customer, payment, delivery
        )
        self.result = CoordinatorAgent._assemble(
            "EC_TEST",
            "o1",
            customer,
            order_product,
            payment,
            delivery,
            decision,
        )
        self.verifier = VerifierAgent(self.repository)

    def verify(self, result: dict) -> dict:
        return self.verifier.verify(
            result,
            expected_order_id="o1",
            scope=self.scope,
            expected_case_id="EC_TEST",
        )

    def test_correct_complete_result_passes(self) -> None:
        self.assertTrue(self.verify(self.result)["verified"])

    def test_wrong_policy_fields_are_rejected(self) -> None:
        mutations = {
            "primary issue": lambda value: value["case_assessment"].update(
                primary_issue="canceled_order_paid"
            ),
            "secondary issues": lambda value: value["case_assessment"].update(
                secondary_issues=["split_payment"]
            ),
            "delivery variance": lambda value: value["delivery_analysis"].update(
                delivery_variance_hours=999999.0
            ),
            "root cause": lambda value: value["root_cause_analysis"].update(
                ranked_causes=[{"cause_code": "BOGUS_CAUSE", "rank": 1}]
            ),
            "refund": lambda value: value["financial_resolution"].update(
                recommended_refund_brl=999.0
            ),
            "actions": lambda value: value.update(
                resolution_actions=["issue_full_refund"]
            ),
            "confidence": lambda value: value["case_assessment"].update(
                confidence=2.0
            ),
            "missing evidence": lambda value: value.update(evidence_ids=[]),
            "case id": lambda value: value.update(case_id="EC_WRONG"),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                result = copy.deepcopy(self.result)
                mutate(result)
                with self.assertRaises(VerificationError):
                    self.verify(result)


if __name__ == "__main__":
    unittest.main()
