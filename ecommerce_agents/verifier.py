"""Independent hard-gate verifier for final case artifacts."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from .config import ARRAY_LIMITS
from .repository import OlistRepository
from .utils import TOLERANCE, decimal_value


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

    def verify(self, result: dict[str, Any], expected_order_id: str) -> dict[str, Any]:
        errors: list[str] = []
        if set(result) != self.TOP_LEVEL_KEYS:
            errors.append("top-level schema keys do not match the required contract")

        confidence = result["case_assessment"]["confidence"]
        if not 0 <= confidence <= 1:
            errors.append("confidence must be in [0, 1]")

        entities = result["affected_entities"]
        if entities["order_ids"] != [expected_order_id]:
            errors.append("affected order must be exactly the claimed order")

        items = self.repository.order_items(expected_order_id)
        payments = self.repository.order_payments(expected_order_id)
        valid_item_ids = {
            f'{expected_order_id}:{row["order_item_id"]}' for row in items
        }
        valid_payment_ids = {
            f'{expected_order_id}:{row["payment_sequential"]}' for row in payments
        }
        valid_sellers = {row["seller_id"] for row in items}
        valid_products = {row["product_id"] for row in items}

        if not set(entities["item_ids"]).issubset(valid_item_ids):
            errors.append("affected item_ids contain an ID absent from order_items")
        if not set(entities["payment_ids"]).issubset(valid_payment_ids):
            errors.append("affected payment_ids contain an ID absent from payments")
        if not set(entities["seller_ids"]).issubset(valid_sellers):
            errors.append("affected seller_ids contain an ID absent from order_items")
        if not set(result["product_context"]["product_ids"]).issubset(valid_products):
            errors.append("product_context contains an ID absent from order_items")

        self._verify_limits(result, errors)
        self._verify_payment(result, items, payments, errors)
        self._verify_evidence(result, expected_order_id, valid_item_ids, valid_payment_ids, errors)

        refund = decimal_value(result["financial_resolution"]["recommended_refund_brl"])
        status = result["case_assessment"]["case_status"]
        if (refund > 0) != (status == "action_required"):
            errors.append("case_status is inconsistent with recommended refund")

        if errors:
            raise VerificationError(f'{result["case_id"]}: ' + "; ".join(errors))
        return {"verified": True, "checks": 10, "errors": []}

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
    def _verify_payment(
        result: dict[str, Any],
        items: list[dict[str, str]],
        payments: list[dict[str, str]],
        errors: list[str],
    ) -> None:
        reconciliation = result["payment_reconciliation"]
        item_total = sum((decimal_value(row["price"]) for row in items), Decimal("0"))
        freight_total = sum(
            (decimal_value(row["freight_value"]) for row in items), Decimal("0")
        )
        payment_total = sum(
            (decimal_value(row["payment_value"]) for row in payments), Decimal("0")
        )
        if decimal_value(reconciliation["item_total_brl"]) != item_total:
            errors.append("item total does not match source rows")
        if decimal_value(reconciliation["freight_total_brl"]) != freight_total:
            errors.append("freight total does not match source rows")
        if decimal_value(reconciliation["payment_total_brl"]) != payment_total:
            errors.append("payment total does not match source rows")
        if items:
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
    def _verify_evidence(
        result: dict[str, Any],
        order_id: str,
        item_ids: set[str],
        payment_ids: set[str],
        errors: list[str],
    ) -> None:
        valid = {f"order:{order_id}"}
        valid.update(f"item:{item_id}" for item_id in item_ids)
        valid.update(f"payment:{payment_id}" for payment_id in payment_ids)
        valid.update(
            f'seller:{party["party_id"]}'
            for party in result["root_cause_analysis"]["responsible_parties"]
            if party["party_type"] == "seller"
        )
        valid.update(
            f'policy:{cause["cause_code"]}'
            for cause in result["root_cause_analysis"]["ranked_causes"]
        )
        if not set(result["evidence_ids"]).issubset(valid):
            errors.append("evidence contains unsupported or malformed IDs")
