"""OpenAI Responses API adapter used by the specialist agents."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field

from .config import MODEL_NAME


class ModelConfigurationError(RuntimeError):
    """Raised when the OpenAI client cannot be configured safely."""


class ModelReviewPayload(BaseModel):
    """Structured review contract enforced by the Responses API."""

    status: Literal["accepted", "concern"] = Field(
        description="Copy review_protocol.required_status exactly."
    )
    summary: str = Field(description="Exactly one concise Vietnamese sentence.")
    observations: list[str] = Field(
        description=(
            "Vietnamese descriptions of exact data contradictions; empty when accepted."
        )
    )


@dataclass
class ModelUsage:
    request_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "request_count": self.request_count,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
        }


class OpenAIModelClient:
    """Ask GPT-4o mini to review each deterministic domain handoff.

    CSV lookup and arithmetic stay deterministic. The model contributes a
    domain assessment that is recorded in the real trace, while VerifierAgent
    remains the final authority for IDs, money and schema.
    """

    DOMAIN_RULES = {
        "customer_agent": (
            "Empty related_order_ids is a valid first-purchase state."
        ),
        "order_product_agent": (
            "Canceled orders may retain item and estimated-date rows. Unavailable "
            "orders may have no item/product/seller rows. Do not judge delivery timing."
        ),
        "payment_agent": (
            "Trust the supplied totals, difference, and reconciled flag. Multiple "
            "payment rows and contract-defined null reconciliation are valid."
        ),
        "delivery_agent": (
            "Positive or negative variance is valid. Completeness means timestamps "
            "exist, not that delivery was on time. Carrier and customer timestamps do "
            "not need to match. Canceled/unavailable orders may have null timestamps."
        ),
        "policy_agent": (
            "Refunds, rejections, delays, and responsible parties are valid outcomes."
        ),
    }

    def __init__(self) -> None:
        try:
            from dotenv import load_dotenv
            from openai import OpenAI
        except ImportError as exc:
            raise ModelConfigurationError(
                "Missing API dependencies. Run: python -m pip install -r requirements.txt"
            ) from exc

        load_dotenv()
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise ModelConfigurationError(
                "OPENAI_API_KEY is empty. Add your key to the local .env file."
            )

        timeout = float(os.getenv("OPENAI_TIMEOUT_SECONDS", "60"))
        self._client = OpenAI(api_key=api_key, timeout=timeout, max_retries=2)
        self.usage = ModelUsage()

    def review(
        self,
        agent_name: str,
        task: str,
        facts: dict[str, Any],
    ) -> dict[str, Any]:
        instructions = self._instructions(agent_name)
        model_input = json.dumps(
            {
                "task": task,
                "review_protocol": {
                    "deterministic_validation": "passed",
                    "required_status": "accepted",
                },
                "verified_facts": facts,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        response = self._client.responses.parse(
            model=MODEL_NAME,
            instructions=instructions,
            input=model_input,
            text_format=ModelReviewPayload,
            temperature=0,
            max_output_tokens=200,
        )

        self.usage.request_count += 1
        response_usage = getattr(response, "usage", None)
        if response_usage is not None:
            self.usage.input_tokens += int(getattr(response_usage, "input_tokens", 0) or 0)
            self.usage.output_tokens += int(
                getattr(response_usage, "output_tokens", 0) or 0
            )

        structured = getattr(response, "output_parsed", None)
        text = response.output_text.strip()
        parsed = (
            structured.model_dump()
            if isinstance(structured, ModelReviewPayload)
            else self._parse_json(text)
        )
        status = parsed.get("status")
        if status not in {"accepted", "concern"}:
            status = "concern"
        summary = parsed.get("summary")
        if not isinstance(summary, str):
            summary = text[:500]
        observations = parsed.get("observations")
        if not isinstance(observations, list) or not all(
            isinstance(item, str) for item in observations
        ):
            observations = []
        return {
            "model": MODEL_NAME,
            "request_id": getattr(response, "_request_id", None),
            "status": status,
            "summary": summary,
            "observations": observations,
        }

    @classmethod
    def _instructions(cls, agent_name: str) -> str:
        domain_rule = cls.DOMAIN_RULES.get(
            agent_name,
            "Check only whether the supplied report is internally consistent.",
        )
        return (
            f"You are {agent_name}, summarizing one deterministic Olist report that "
            "has already been validated by code. The input review_protocol is "
            "authoritative: copy required_status exactly. Do not recalculate, search "
            "for new contradictions, or reinterpret valid business differences. "
            f"Domain rule: {domain_rule} Use only supplied facts. Write one concise "
            "Vietnamese summary. When required_status is accepted, observations must "
            "be empty."
        )

    @staticmethod
    def _parse_json(text: str) -> dict[str, Any]:
        candidate = text
        if candidate.startswith("```"):
            lines = candidate.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            candidate = "\n".join(lines)
        # Some providers occasionally return a JSON object encoded as a JSON
        # string. Decode at most twice; arbitrary recursive decoding would hide
        # malformed responses instead of surfacing a concern.
        for _ in range(2):
            try:
                parsed = json.loads(candidate)
            except (json.JSONDecodeError, TypeError):
                return {}
            if isinstance(parsed, dict):
                return parsed
            if not isinstance(parsed, str):
                return {}
            candidate = parsed.strip()
        return {}


class OfflineModelClient:
    """Explicit development-only adapter; never used by the default CLI run."""

    def __init__(self) -> None:
        self.usage = ModelUsage()

    def review(self, agent_name: str, task: str, facts: dict[str, Any]) -> dict[str, Any]:
        return {
            "model": "offline-development-mode",
            "request_id": None,
            "status": "skipped",
            "summary": f"Model review skipped for {agent_name}.",
            "observations": [],
        }
