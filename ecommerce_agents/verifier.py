"""Independent hard-gate verifier for final case artifacts."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Any

from .config import ARRAY_LIMITS, PRIMARY_POLICY
from .repository import OlistRepository
from .utils import (
    TOLERANCE,
    decimal_value,
    money,
    parse_timestamp,
    stable_unique,
    variance_hours,
)


class VerificationError(RuntimeError):
    """Raised when the final artifact is not directly supported by source data."""


class VerifierAgent:
    name = "verifier_agent"

    TOP_LEVEL_KEYS = {
        "case_id",
        "case_assessment",
        "affected_entities",
        "customer_context",
        "product_context",
        "delivery_analysis",
        "payment_reconciliation",
        "root_cause_analysis",
        "evidence_ids",
        "financial_resolution",
        "resolution_actions",
    }

    def __init__(self, repository: OlistRepository):
        self.repository = repository

    def verify(
        self,
        result: dict[str, Any],
        expected_order_id: str,
        scope: dict[str, Any] | None = None,
        expected_case_id: str | None = None,
    ) -> dict[str, Any]:
        errors: list[str] = []
        if set(result) != self.TOP_LEVEL_KEYS:
            errors.append("top-level schema keys do not match the required contract")
        if expected_case_id is not None and result["case_id"] != expected_case_id:
            errors.append("case_id does not match input case_id")

        confidence = result["case_assessment"]["confidence"]
        if not 0 <= confidence <= 1:
            errors.append("confidence must be in [0, 1]")

        entities = result["affected_entities"]
        if entities["order_ids"] != [expected_order_id]:
            errors.append("affected order must be exactly the claimed order")

        items = self.repository.order_items(expected_order_id)
        payments = self.repository.order_payments(expected_order_id)
        expected_item_ids = [
            f'{expected_order_id}:{row["order_item_id"]}' for row in items
        ][: ARRAY_LIMITS["item_ids"]]
        expected_payment_ids = [
            f'{expected_order_id}:{row["payment_sequential"]}' for row in payments
        ][: ARRAY_LIMITS["payment_ids"]]
        expected_sellers = stable_unique(row["seller_id"] for row in items)[
            : ARRAY_LIMITS["seller_ids"]
        ]
        product_ids = stable_unique(row["product_id"] for row in items)
        categories = stable_unique(
            self.repository.product(product_id).get("product_category_name", "")
            for product_id in product_ids
        )
        categories = [category for category in categories if category]
        include_history = True if scope is None else bool(
            scope.get("include_customer_history")
        )
        include_products = True if scope is None else bool(
            scope.get("include_product_context")
        )

        if entities["item_ids"] != expected_item_ids:
            errors.append("affected item_ids are incomplete or out of source order")
        if entities["payment_ids"] != expected_payment_ids:
            errors.append("affected payment_ids are incomplete or out of source order")
        if entities["seller_ids"] != expected_sellers:
            errors.append("affected seller_ids are incomplete or out of source order")

        customer = self.repository.customer_for_order(expected_order_id)
        context = result["customer_context"]
        expected_related = (
            self.repository.related_order_ids(expected_order_id)
            if include_history
            else []
        )[: ARRAY_LIMITS["related_order_ids"]]
        if context["customer_unique_id"] != customer["customer_unique_id"]:
            errors.append("customer_unique_id does not match the claimed order")
        if context["related_order_ids"] != expected_related:
            errors.append("related_order_ids are incomplete or out of source order")

        expected_products = (
            product_ids[: ARRAY_LIMITS["product_ids"]] if include_products else []
        )
        expected_categories = (
            categories[: ARRAY_LIMITS["category_names"]] if include_products else []
        )
        product_context = result["product_context"]
        if product_context["product_ids"] != expected_products:
            errors.append("product_ids are incomplete or out of source order")
        if product_context["category_names"] != expected_categories:
            errors.append("category_names are incomplete or out of source order")

        order = self.repository.order(expected_order_id)
        self._verify_limits(result, errors)
        self._verify_delivery(result, order, items, errors)
        self._verify_payment(result, items, payments, errors)
        self._verify_policy(
            result,
            order,
            items,
            payments,
            expected_sellers,
            categories,
            expected_related,
            errors,
        )
        self._verify_evidence(result, expected_order_id, errors)

        refund = decimal_value(result["financial_resolution"]["recommended_refund_brl"])
        status = result["case_assessment"]["case_status"]
        if (refund > 0) != (status == "action_required"):
            errors.append("case_status is inconsistent with recommended refund")

        if errors:
            raise VerificationError(f'{result["case_id"]}: ' + "; ".join(errors))
        return {"verified": True, "checks": 15, "errors": []}

    @staticmethod
    def _verify_limits(result: dict[str, Any], errors: list[str]) -> None:
        paths = {
            "order_ids": result["affected_entities"]["order_ids"],
            "item_ids": result["affected_entities"]["item_ids"],
            "seller_ids": result["affected_entities"]["seller_ids"],
            "payment_ids": result["affected_entities"]["payment_ids"],
            "related_order_ids": result["customer_context"]["related_order_ids"],
            "product_ids": result["product_context"]["product_ids"],
            "category_names": result["product_context"]["category_names"],
            "ranked_causes": result["root_cause_analysis"]["ranked_causes"],
            "responsible_parties": result["root_cause_analysis"]["responsible_parties"],
            "evidence_ids": result["evidence_ids"],
            "resolution_actions": result["resolution_actions"],
        }
        for name, values in paths.items():
            if len(values) > ARRAY_LIMITS[name]:
                errors.append(f"{name} exceeds limit {ARRAY_LIMITS[name]}")

    @staticmethod
    def _verify_delivery(
        result: dict[str, Any],
        order: dict[str, str],
        items: list[dict[str, str]],
        errors: list[str],
    ) -> None:
        delivery = result["delivery_analysis"]
        delivered_at = order.get("order_delivered_customer_date") or None
        estimated_at = order.get("order_estimated_delivery_date") or None
        carrier_at = order.get("order_delivered_carrier_date") or None

        expected_timestamps = {
            "delivered_at": delivered_at,
            "estimated_delivery_at": estimated_at,
            "carrier_handoff_at": carrier_at,
            "delivery_variance_hours": variance_hours(delivered_at, estimated_at),
        }
        for key, expected in expected_timestamps.items():
            if delivery[key] != expected:
                errors.append(f"{key} does not match source timestamps")

        limits_by_seller: dict[str, list[str]] = defaultdict(list)
        seller_order: list[str] = []
        for item in items:
            seller_id = item["seller_id"]
            if seller_id not in limits_by_seller:
                seller_order.append(seller_id)
            if item.get("shipping_limit_date"):
                limits_by_seller[seller_id].append(item["shipping_limit_date"])

        expected_analysis: list[dict[str, Any]] = []
        for seller_id in seller_order:
            shipping_limit_at = min(limits_by_seller[seller_id], default=None)
            late_handoff = False
            if carrier_at and shipping_limit_at:
                late_handoff = parse_timestamp(carrier_at) > parse_timestamp(
                    shipping_limit_at
                )
            expected_analysis.append(
                {
                    "seller_id": seller_id,
                    "shipping_limit_at": shipping_limit_at,
                    "handoff_variance_hours": variance_hours(
                        carrier_at, shipping_limit_at
                    ),
                    "late_handoff": late_handoff,
                }
            )

        expected_analysis = expected_analysis[: ARRAY_LIMITS["seller_ids"]]
        expected_late_sellers = [
            row["seller_id"] for row in expected_analysis if row["late_handoff"]
        ][: ARRAY_LIMITS["seller_ids"]]
        if delivery["seller_handoff_analysis"] != expected_analysis:
            errors.append("seller_handoff_analysis does not match source timestamps")
        if delivery["late_handoff_seller_ids"] != expected_late_sellers:
            errors.append("late_handoff_seller_ids do not match source timestamps")

    @staticmethod
    def _verify_payment(
        result: dict[str, Any],
        items: list[dict[str, str]],
        payments: list[dict[str, str]],
        errors: list[str],
    ) -> None:
        reconciliation = result["payment_reconciliation"]
        if reconciliation["currency"] != "BRL":
            errors.append("payment currency must be BRL")
        item_total = sum((decimal_value(row["price"]) for row in items), Decimal("0"))
        freight_total = sum(
            (decimal_value(row["freight_value"]) for row in items), Decimal("0")
        )
        payment_total = sum(
            (decimal_value(row["payment_value"]) for row in payments), Decimal("0")
        )
        expected_total = item_total + freight_total if items else None
        if decimal_value(reconciliation["item_total_brl"]) != item_total:
            errors.append("item total does not match source rows")
        if decimal_value(reconciliation["freight_total_brl"]) != freight_total:
            errors.append("freight total does not match source rows")
        if decimal_value(reconciliation["payment_total_brl"]) != payment_total:
            errors.append("payment total does not match source rows")
        if reconciliation["payment_types"] != stable_unique(
            row["payment_type"] for row in payments
        ):
            errors.append("payment_types are incomplete or out of source order")
        if items:
            if decimal_value(reconciliation["expected_total_brl"]) != expected_total:
                errors.append("expected total does not match item plus freight")
            difference = payment_total - item_total - freight_total
            if decimal_value(reconciliation["difference_brl"]) != difference:
                errors.append("payment difference is incorrect")
            if reconciliation["reconciled"] != (abs(difference) <= TOLERANCE):
                errors.append("reconciled flag is incorrect")
        elif any(
            reconciliation[key] is not None
            for key in ("expected_total_brl", "difference_brl", "reconciled")
        ):
            errors.append("no-item order must use null expected/difference/reconciled")

    @staticmethod
    def _verify_policy(
        result: dict[str, Any],
        order: dict[str, str],
        items: list[dict[str, str]],
        payments: list[dict[str, str]],
        seller_ids: list[str],
        category_names: list[str],
        related_order_ids: list[str],
        errors: list[str],
    ) -> None:
        payment_total = sum(
            (decimal_value(row["payment_value"]) for row in payments), Decimal("0")
        )
        freight_total = sum(
            (decimal_value(row["freight_value"]) for row in items), Decimal("0")
        )

        delivered_at = order.get("order_delivered_customer_date") or None
        estimated_at = order.get("order_estimated_delivery_date") or None
        late_delivery: bool | None = None
        if delivered_at and estimated_at:
            late_delivery = parse_timestamp(delivered_at) > parse_timestamp(estimated_at)
        carrier_at = order.get("order_delivered_carrier_date") or None
        handoff_timing_complete = bool(items) and bool(carrier_at) and all(
            item.get("shipping_limit_date") for item in items
        )
        late_seller_ids = result["delivery_analysis"]["late_handoff_seller_ids"]
        reconciled = result["payment_reconciliation"]["reconciled"]

        primary_issue: str | None = None
        if order["order_status"] == "canceled" and payment_total > 0:
            primary_issue = "canceled_order_paid"
        elif order["order_status"] == "unavailable" and payment_total > 0:
            primary_issue = "unavailable_order_paid"
        elif late_delivery is True and handoff_timing_complete and late_seller_ids:
            primary_issue = "late_delivery_seller"
        elif late_delivery is True and handoff_timing_complete:
            primary_issue = "late_delivery_logistics"
        elif late_delivery is False and len(payments) >= 2 and reconciled is True:
            primary_issue = "valid_split_payment"
        elif late_delivery is False and reconciled is True:
            primary_issue = "unsupported_late_claim"

        if primary_issue is None:
            if late_delivery is None:
                errors.append(
                    "missing delivered/estimated timestamps required by policy priority"
                )
            elif late_delivery is True and not handoff_timing_complete:
                errors.append(
                    "missing carrier/shipping-limit timestamps required for responsibility"
                )
            else:
                errors.append("case does not match an EC_POLICY_V2 primary rule")
            return

        secondary: list[str] = []
        if len(items) >= 2:
            secondary.append("multi_item_order")
        if len(seller_ids) >= 2:
            secondary.append("multi_seller_order")
        if len(payments) >= 2:
            secondary.append("split_payment")
        if related_order_ids:
            secondary.append("repeat_customer")
        if len(category_names) >= 2:
            secondary.append("multiple_categories")

        policy = PRIMARY_POLICY[primary_issue]
        responsible: list[dict[str, str]] = []
        if primary_issue == "late_delivery_seller":
            responsible = [
                {"party_type": "seller", "party_id": seller_id}
                for seller_id in late_seller_ids[: ARRAY_LIMITS["responsible_parties"]]
            ]
        elif "party_type" in policy:
            responsible = [
                {"party_type": policy["party_type"], "party_id": policy["party_id"]}
            ]

        if primary_issue in {"canceled_order_paid", "unavailable_order_paid"}:
            refund = money(payment_total)
        elif primary_issue in {"late_delivery_seller", "late_delivery_logistics"}:
            refund = money(freight_total)
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
        actions = actions[: ARRAY_LIMITS["resolution_actions"]]

        assessment = result["case_assessment"]
        if assessment["primary_issue"] != primary_issue:
            errors.append("primary_issue does not match EC_POLICY_V2")
        if assessment["secondary_issues"] != secondary:
            errors.append("secondary_issues do not match EC_POLICY_V2")
        expected_status = "action_required" if decimal_value(refund) > 0 else "no_action"
        if assessment["case_status"] != expected_status:
            errors.append("case_status does not match refund policy")
        if result["root_cause_analysis"]["ranked_causes"] != [
            {"cause_code": policy["cause"], "rank": 1}
        ]:
            errors.append("ranked_causes do not match primary issue")
        if result["root_cause_analysis"]["responsible_parties"] != responsible:
            errors.append("responsible_parties do not match primary issue")

        financial = result["financial_resolution"]
        if financial["currency"] != "BRL":
            errors.append("financial currency must be BRL")
        if decimal_value(financial["recommended_refund_brl"]) != decimal_value(refund):
            errors.append("recommended refund does not match EC_POLICY_V2")
        if result["resolution_actions"] != actions:
            errors.append("resolution_actions do not match EC_POLICY_V2")

    @staticmethod
    def _verify_evidence(
        result: dict[str, Any],
        order_id: str,
        errors: list[str],
    ) -> None:
        entities = result["affected_entities"]
        expected = [f"order:{order_id}"]
        expected.extend(f'item:{item_id}' for item_id in entities["item_ids"])
        expected.extend(f'payment:{payment_id}' for payment_id in entities["payment_ids"])
        expected.extend(
            f'seller:{party["party_id"]}'
            for party in result["root_cause_analysis"]["responsible_parties"]
            if party["party_type"] == "seller"
        )
        expected.extend(
            f'policy:{cause["cause_code"]}'
            for cause in result["root_cause_analysis"]["ranked_causes"]
        )
        expected = expected[: ARRAY_LIMITS["evidence_ids"]]
        if result["evidence_ids"] != expected:
            errors.append("evidence is incomplete, unsupported, or out of order")
