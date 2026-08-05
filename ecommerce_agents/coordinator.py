"""Coordinator that routes one case through specialist agents and verifier."""

from __future__ import annotations

from typing import Any

from .agents import (
    CustomerAgent,
    DeliveryAgent,
    OrderProductAgent,
    PaymentAgent,
    PolicyAgent,
)
from .config import ARRAY_LIMITS, POLICY_VERSION
from .llm import OfflineModelClient, OpenAIModelClient
from .repository import OlistRepository
from .tracing import TraceWriter
from .verifier import VerifierAgent


class CoordinatorAgent:
    name = "coordinator_agent"

    def __init__(
        self,
        repository: OlistRepository,
        trace: TraceWriter,
        model: OpenAIModelClient | OfflineModelClient,
    ):
        self.repository = repository
        self.trace = trace
        self.customer_agent = CustomerAgent(repository, model)
        self.order_product_agent = OrderProductAgent(repository, model)
        self.payment_agent = PaymentAgent(repository, model)
        self.delivery_agent = DeliveryAgent(model)
        self.policy_agent = PolicyAgent(model)
        self.verifier_agent = VerifierAgent(repository)

    def process(self, case: dict[str, Any]) -> dict[str, Any]:
        case_id = case["case_id"]
        policy_version = case["policy_version"]
        if policy_version != POLICY_VERSION:
            raise ValueError(f"{case_id}: unsupported policy_version {policy_version}")

        order_id = case["customer_request"]["claimed_order_id"]
        scope = case["investigation_scope"]
        self.trace.emit(
            case_id,
            "main",
            self.name,
            "case_received",
            {
                "order_id": order_id,
                "policy_version": policy_version,
                "scope": scope,
                "claim_handling": "untrusted_context_only",
                "customer_message_used_as_evidence": False,
                "decision_basis": "claimed_order_id_joined_to_verified_csv_rows",
                "required_verification": [
                    "order",
                    "customer",
                    "items",
                    "payments",
                    "delivery",
                    "policy",
                ],
            },
        )

        customer = self.customer_agent.investigate(
            order_id, bool(scope["include_customer_history"])
        )
        self._handoff(case_id, self.customer_agent.name, customer)

        order_product = self.order_product_agent.investigate(
            order_id, bool(scope["include_product_context"])
        )
        self._handoff(case_id, self.order_product_agent.name, order_product)

        payment = self.payment_agent.reconcile(order_id, order_product["items"])
        self._handoff(case_id, self.payment_agent.name, payment)

        delivery = self.delivery_agent.analyze(
            order_product["order"], order_product["items"]
        )
        self._handoff(case_id, self.delivery_agent.name, delivery)

        decision = self.policy_agent.decide(order_product, customer, payment, delivery)
        self._handoff(case_id, self.policy_agent.name, decision)

        result = self._assemble(
            case_id, order_id, customer, order_product, payment, delivery, decision
        )
        verification = self.verifier_agent.verify(
            result, order_id, scope, expected_case_id=case_id
        )
        self.trace.emit(
            case_id,
            self.verifier_agent.name,
            self.name,
            "verification_passed",
            verification,
        )
        self.trace.emit(
            case_id,
            self.name,
            "main",
            "case_completed",
            {
                "primary_issue": decision["primary_issue"],
                "refund_brl": decision["recommended_refund_brl"],
                "verification": "passed",
                "action_mode": "recommendation_only",
                "external_action_executed": False,
            },
        )
        return result

    def _handoff(self, case_id: str, sender: str, payload: dict[str, Any]) -> None:
        self.trace.emit(case_id, sender, self.name, "analysis_handoff", payload)

    @staticmethod
    def _assemble(
        case_id: str,
        order_id: str,
        customer: dict[str, Any],
        order_product: dict[str, Any],
        payment: dict[str, Any],
        delivery: dict[str, Any],
        decision: dict[str, Any],
    ) -> dict[str, Any]:
        item_ids = order_product["item_ids"][: ARRAY_LIMITS["item_ids"]]
        payment_ids = payment["payment_ids"][: ARRAY_LIMITS["payment_ids"]]
        seller_ids = order_product["seller_ids"][: ARRAY_LIMITS["seller_ids"]]
        cause_code = decision["cause_code"]

        evidence = [f"order:{order_id}"]
        evidence.extend(f"item:{item_id}" for item_id in item_ids)
        evidence.extend(f"payment:{payment_id}" for payment_id in payment_ids)
        evidence.extend(
            f'seller:{party["party_id"]}'
            for party in decision["responsible_parties"]
            if party["party_type"] == "seller"
        )
        evidence.append(f"policy:{cause_code}")

        return {
            "case_id": case_id,
            "case_assessment": {
                "primary_issue": decision["primary_issue"],
                "secondary_issues": decision["secondary_issues"],
                "case_status": decision["case_status"],
                "confidence": decision["confidence"],
            },
            "affected_entities": {
                "order_ids": [order_id],
                "item_ids": item_ids,
                "seller_ids": seller_ids,
                "payment_ids": payment_ids,
            },
            "customer_context": {
                "customer_unique_id": customer["customer_unique_id"],
                "related_order_ids": customer["related_order_ids"][
                    : ARRAY_LIMITS["related_order_ids"]
                ],
            },
            "product_context": {
                "product_ids": order_product["product_ids"][: ARRAY_LIMITS["product_ids"]],
                "category_names": order_product["category_names"][
                    : ARRAY_LIMITS["category_names"]
                ],
            },
            "delivery_analysis": {
                "delivered_at": delivery["delivered_at"],
                "estimated_delivery_at": delivery["estimated_delivery_at"],
                "carrier_handoff_at": delivery["carrier_handoff_at"],
                "delivery_variance_hours": delivery["delivery_variance_hours"],
                "seller_handoff_analysis": delivery["seller_handoff_analysis"][
                    : ARRAY_LIMITS["seller_ids"]
                ],
                "late_handoff_seller_ids": delivery["late_handoff_seller_ids"][
                    : ARRAY_LIMITS["seller_ids"]
                ],
            },
            "payment_reconciliation": {
                key: payment[key]
                for key in (
                    "currency",
                    "item_total_brl",
                    "freight_total_brl",
                    "expected_total_brl",
                    "payment_total_brl",
                    "difference_brl",
                    "reconciled",
                    "payment_types",
                )
            },
            "root_cause_analysis": {
                "ranked_causes": [{"cause_code": cause_code, "rank": 1}],
                "responsible_parties": decision["responsible_parties"],
            },
            "evidence_ids": evidence[: ARRAY_LIMITS["evidence_ids"]],
            "financial_resolution": {
                "currency": "BRL",
                "recommended_refund_brl": decision["recommended_refund_brl"],
            },
            "resolution_actions": decision["resolution_actions"],
        }
