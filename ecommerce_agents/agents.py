"""Specialist agents and their structured handoff contracts."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Any

from .config import ARRAY_LIMITS, PRIMARY_POLICY
from .llm import OpenAIModelClient, OfflineModelClient
from .repository import OlistRepository
from .utils import TOLERANCE, decimal_value, money, parse_timestamp, stable_unique, variance_hours


class PolicyDecisionError(RuntimeError):
    """Raised when a case does not match any EC_POLICY_V2 rule."""


ModelClient = OpenAIModelClient | OfflineModelClient


class ModelBackedAgent:
    name = "model_backed_agent"

    def __init__(self, model: ModelClient | None = None):
        self.model = model

    def _with_model_review(self, task: str, report: dict[str, Any]) -> dict[str, Any]:
        if self.model is not None:
            report["model_review"] = self.model.review(self.name, task, report)
        return report


class CustomerAgent(ModelBackedAgent):
    name = "customer_agent"

    def __init__(self, repository: OlistRepository, model: ModelClient | None = None):
        super().__init__(model)
        self.repository = repository

    def investigate(self, order_id: str, include_history: bool) -> dict[str, Any]:
        customer = self.repository.customer_for_order(order_id)
        related = self.repository.related_order_ids(order_id) if include_history else []
        return self._with_model_review("Review customer identity and order history.", {
            "customer_unique_id": customer["customer_unique_id"],
            "related_order_ids": related,
        })


class OrderProductAgent(ModelBackedAgent):
    name = "order_product_agent"

    def __init__(self, repository: OlistRepository, model: ModelClient | None = None):
        super().__init__(model)
        self.repository = repository

    def investigate(self, order_id: str, include_product_context: bool) -> dict[str, Any]:
        order = self.repository.order(order_id)
        items = self.repository.order_items(order_id)
        seller_ids = stable_unique(row["seller_id"] for row in items)
        product_ids = stable_unique(row["product_id"] for row in items)
        categories = stable_unique(
            self.repository.product(product_id).get("product_category_name", "")
            for product_id in product_ids
        )
        categories = [category for category in categories if category]
        return self._with_model_review("Review order, item, seller and product facts.", {
            "order": order,
            "items": items,
            "item_ids": [f'{order_id}:{row["order_item_id"]}' for row in items],
            "seller_ids": seller_ids,
            "product_ids": product_ids if include_product_context else [],
            "category_names": categories if include_product_context else [],
            # Policy facts remain available even if display context is disabled.
            "policy_category_names": categories,
        })


class PaymentAgent(ModelBackedAgent):
    name = "payment_agent"

    def __init__(self, repository: OlistRepository, model: ModelClient | None = None):
        super().__init__(model)
        self.repository = repository

    def reconcile(self, order_id: str, items: list[dict[str, str]]) -> dict[str, Any]:
        payments = self.repository.order_payments(order_id)
        item_total = sum((decimal_value(row["price"]) for row in items), Decimal("0"))
        freight_total = sum(
            (decimal_value(row["freight_value"]) for row in items), Decimal("0")
        )
        payment_total = sum(
            (decimal_value(row["payment_value"]) for row in payments), Decimal("0")
        )

        expected_total: Decimal | None = item_total + freight_total if items else None
        difference: Decimal | None = (
            payment_total - expected_total if expected_total is not None else None
        )
        reconciled: bool | None = (
            abs(difference) <= TOLERANCE if difference is not None else None
        )
        return self._with_model_review("Review payment reconciliation facts.", {
            "rows": payments,
            "currency": "BRL",
            "item_total_brl": money(item_total),
            "freight_total_brl": money(freight_total),
            "expected_total_brl": money(expected_total),
            "payment_total_brl": money(payment_total),
            "difference_brl": money(difference),
            "reconciled": reconciled,
            "payment_types": stable_unique(row["payment_type"] for row in payments),
            "payment_ids": [
                f'{order_id}:{row["payment_sequential"]}' for row in payments
            ],
        })


class DeliveryAgent(ModelBackedAgent):
    name = "delivery_agent"

    def analyze(self, order: dict[str, str], items: list[dict[str, str]]) -> dict[str, Any]:
        delivered_at = order.get("order_delivered_customer_date") or None
        estimated_at = order.get("order_estimated_delivery_date") or None
        carrier_at = order.get("order_delivered_carrier_date") or None

        limits_by_seller: dict[str, list[str]] = defaultdict(list)
        seller_order: list[str] = []
        for item in items:
            seller_id = item["seller_id"]
            if seller_id not in limits_by_seller:
                seller_order.append(seller_id)
            if item.get("shipping_limit_date"):
                limits_by_seller[seller_id].append(item["shipping_limit_date"])

        seller_analysis: list[dict[str, Any]] = []
        for seller_id in seller_order:
            shipping_limit_at = min(limits_by_seller[seller_id], default=None)
            handoff_variance = variance_hours(carrier_at, shipping_limit_at)
            late_handoff = False
            if carrier_at and shipping_limit_at:
                late_handoff = parse_timestamp(carrier_at) > parse_timestamp(shipping_limit_at)
            seller_analysis.append(
                {
                    "seller_id": seller_id,
                    "shipping_limit_at": shipping_limit_at,
                    "handoff_variance_hours": handoff_variance,
                    "late_handoff": late_handoff,
                }
            )

        # Missing timestamps mean "unknown", not "on time".  Keeping this as a
        # tri-state fact prevents lower-priority payment rules from winning when
        # the pipeline cannot first rule out a late-delivery case.
        delivery_timing_complete = bool(delivered_at and estimated_at)
        late_delivery: bool | None = None
        if delivery_timing_complete:
            late_delivery = parse_timestamp(delivered_at) > parse_timestamp(estimated_at)

        # A late order can only be attributed to logistics after every seller
        # handoff can be checked.  This flag stays internal to the handoff; the
        # required output schema remains unchanged.
        handoff_timing_complete = bool(items) and bool(carrier_at) and all(
            item.get("shipping_limit_date") for item in items
        )

        return self._with_model_review("Review delivery and seller handoff timing.", {
            "order_status": order.get("order_status"),
            "delivered_at": delivered_at,
            "estimated_delivery_at": estimated_at,
            "carrier_handoff_at": carrier_at,
            "delivery_variance_hours": variance_hours(delivered_at, estimated_at),
            "seller_handoff_analysis": seller_analysis,
            "late_handoff_seller_ids": [
                row["seller_id"] for row in seller_analysis if row["late_handoff"]
            ],
            "late_delivery": late_delivery,
            "delivery_timing_complete": delivery_timing_complete,
            "handoff_timing_complete": handoff_timing_complete,
        })


class PolicyAgent(ModelBackedAgent):
    name = "policy_agent"

    def decide(
        self,
        order_product: dict[str, Any],
        customer: dict[str, Any],
        payment: dict[str, Any],
        delivery: dict[str, Any],
    ) -> dict[str, Any]:
        order = order_product["order"]
        items = order_product["items"]
        payments = payment["rows"]
        payment_total = decimal_value(payment["payment_total_brl"])

        primary_issue: str | None = None
        if order["order_status"] == "canceled" and payment_total > 0:
            primary_issue = "canceled_order_paid"
        elif order["order_status"] == "unavailable" and payment_total > 0:
            primary_issue = "unavailable_order_paid"
        elif (
            delivery["late_delivery"] is True
            and delivery.get("handoff_timing_complete", False)
            and delivery["late_handoff_seller_ids"]
        ):
            primary_issue = "late_delivery_seller"
        elif (
            delivery["late_delivery"] is True
            and delivery.get("handoff_timing_complete", False)
        ):
            primary_issue = "late_delivery_logistics"
        elif (
            delivery["late_delivery"] is False
            and len(payments) >= 2
            and payment["reconciled"] is True
        ):
            primary_issue = "valid_split_payment"
        elif delivery["late_delivery"] is False and payment["reconciled"] is True:
            primary_issue = "unsupported_late_claim"

        if primary_issue is None:
            if delivery["late_delivery"] is None:
                reason = "missing delivered/estimated timestamps"
            elif (
                delivery["late_delivery"] is True
                and not delivery.get("handoff_timing_complete", False)
            ):
                reason = "missing carrier/shipping-limit timestamps"
            else:
                reason = "no primary rule matched"
            raise PolicyDecisionError(
                f'Order {order["order_id"]} cannot be decided under EC_POLICY_V2: '
                f"{reason}"
            )

        secondary: list[str] = []
        if len(items) >= 2:
            secondary.append("multi_item_order")
        if len(order_product["seller_ids"]) >= 2:
            secondary.append("multi_seller_order")
        if len(payments) >= 2:
            secondary.append("split_payment")
        if customer["related_order_ids"]:
            secondary.append("repeat_customer")
        if len(order_product["policy_category_names"]) >= 2:
            secondary.append("multiple_categories")

        policy = PRIMARY_POLICY[primary_issue]
        responsible: list[dict[str, str]] = []
        if primary_issue == "late_delivery_seller":
            responsible = [
                {"party_type": "seller", "party_id": seller_id}
                for seller_id in delivery["late_handoff_seller_ids"][
                    : ARRAY_LIMITS["responsible_parties"]
                ]
            ]
        elif "party_type" in policy:
            responsible = [
                {"party_type": policy["party_type"], "party_id": policy["party_id"]}
            ]

        if primary_issue in {"canceled_order_paid", "unavailable_order_paid"}:
            refund = payment["payment_total_brl"]
        elif primary_issue in {"late_delivery_seller", "late_delivery_logistics"}:
            refund = payment["freight_total_brl"]
        else:
            refund = 0.0

        actions = [policy["action"]]
        if primary_issue == "late_delivery_seller":
            actions.append("review_seller_handoff")
        elif primary_issue == "late_delivery_logistics":
            actions.append("review_carrier_delay")
        if primary_issue in {"canceled_order_paid", "unavailable_order_paid"}:
            actions.append("verify_refund_completion")
        if "multi_seller_order" in secondary:
            actions.append("coordinate_multi_seller_case")
        if "split_payment" in secondary and primary_issue != "valid_split_payment":
            actions.append("verify_payment_allocation")

        return self._with_model_review("Review the EC_POLICY_V2 decision.", {
            "primary_issue": primary_issue,
            "secondary_issues": secondary,
            "case_status": "action_required" if decimal_value(refund) > 0 else "no_action",
            "confidence": 1.0,
            "cause_code": policy["cause"],
            "responsible_parties": responsible,
            "recommended_refund_brl": money(decimal_value(refund)),
            "resolution_actions": actions[: ARRAY_LIMITS["resolution_actions"]],
        })
