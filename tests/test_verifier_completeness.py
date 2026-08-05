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
        "order_delivered_carrier_date": "2018-01-02 08:00:00",
        "order_delivered_customer_date": "2018-01-03 08:00:00",
        "order_estimated_delivery_date": "2018-01-04 00:00:00",
    }
    item_rows = [{
        "order_id": "o1", "order_item_id": "1", "product_id": "p1",
        "seller_id": "s1", "shipping_limit_date": "2018-01-02 12:00:00",
        "price": "10.00", "freight_value": "2.00",
    }]
    payment_rows = [{
        "order_id": "o1", "payment_sequential": "1",
        "payment_type": "credit_card", "payment_value": "12.00",
    }]

    def order(self, order_id: str) -> dict[str, str]:
        return dict(self.order_row)

    def order_items(self, order_id: str) -> list[dict[str, str]]:
        return [dict(row) for row in self.item_rows]

    def order_payments(self, order_id: str) -> list[dict[str, str]]:
        return [dict(row) for row in self.payment_rows]

    def customer_for_order(self, order_id: str) -> dict[str, str]:
        return {"customer_unique_id": "cu1"}

    def related_order_ids(self, order_id: str) -> list[str]:
        return ["o0"]

    def product(self, product_id: str) -> dict[str, str]:
        return {"product_category_name": "books"}


class VerifierCompletenessTests(unittest.TestCase):
    def setUp(self) -> None:
        repository = FakeRepository()
        customer = CustomerAgent(repository).investigate("o1", True)
        order_product = OrderProductAgent(repository).investigate("o1", True)
        payment = PaymentAgent(repository).reconcile("o1", order_product["items"])
        delivery = DeliveryAgent().analyze(order_product["order"], order_product["items"])
        decision = PolicyAgent().decide(order_product, customer, payment, delivery)
        self.result = CoordinatorAgent._assemble(
            "EC_TEST", "o1", customer, order_product, payment, delivery, decision
        )
        self.verifier = VerifierAgent(repository)
        self.scope = {"include_customer_history": True, "include_product_context": True}

    def test_complete_result_passes(self) -> None:
        self.assertTrue(self.verifier.verify(self.result, "o1", self.scope)["verified"])

    def test_missing_item_is_rejected(self) -> None:
        result = copy.deepcopy(self.result)
        result["affected_entities"]["item_ids"] = []
        with self.assertRaises(VerificationError):
            self.verifier.verify(result, "o1", self.scope)

    def test_missing_evidence_is_rejected(self) -> None:
        result = copy.deepcopy(self.result)
        result["evidence_ids"] = []
        with self.assertRaises(VerificationError):
            self.verifier.verify(result, "o1", self.scope)


if __name__ == "__main__":
    unittest.main()
