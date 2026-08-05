"""Shared constants for the EC_POLICY_V2 pipeline."""

from __future__ import annotations

POLICY_VERSION = "EC_POLICY_V2"

# Model names belong in source code (not .env) so the evaluated runtime is clear.
MODEL_PROVIDER = "OpenAI"
MODEL_NAME = "gpt-4o-mini"
# OpenAI does not publish an official parameter count for this hosted model.
MODEL_PARAMETER_SIZE = "not publicly disclosed"
MODEL_API = "Responses API"
FRAMEWORK_NAME = "custom-python-multi-agent + OpenAI Responses API"

# Maximum array sizes from the output contract. Business rules can be stricter;
# for example, affected_entities.order_ids is assembled as the claimed order
# only, while customer history belongs in related_order_ids.
ARRAY_LIMITS = {
    "order_ids": 5,
    "item_ids": 5,
    "seller_ids": 3,
    "payment_ids": 5,
    "related_order_ids": 5,
    "product_ids": 5,
    "category_names": 5,
    "ranked_causes": 3,
    "responsible_parties": 3,
    "evidence_ids": 20,
    "resolution_actions": 5,
}

PRIMARY_POLICY = {
    "canceled_order_paid": {
        "cause": "ORDER_CANCELED_AFTER_PAYMENT",
        "party_type": "platform",
        "party_id": "OLIST_PLATFORM",
        "action": "issue_full_refund",
    },
    "unavailable_order_paid": {
        "cause": "ORDER_UNAVAILABLE_AFTER_PAYMENT",
        "party_type": "platform",
        "party_id": "OLIST_PLATFORM",
        "action": "issue_full_refund",
    },
    "late_delivery_seller": {
        "cause": "SELLER_HANDOFF_AFTER_LIMIT",
        "party_type": "seller",
        "action": "refund_freight",
    },
    "late_delivery_logistics": {
        "cause": "CARRIER_DELIVERED_AFTER_ESTIMATE",
        "party_type": "logistics_provider",
        "party_id": "LOGISTICS_PROVIDER",
        "action": "refund_freight",
    },
    "valid_split_payment": {
        "cause": "MULTIPLE_PAYMENTS_RECONCILED",
        "action": "explain_valid_split_payment",
    },
    "unsupported_late_claim": {
        "cause": "DELIVERY_WITHIN_ESTIMATE",
        "action": "reject_late_refund",
    },
}
