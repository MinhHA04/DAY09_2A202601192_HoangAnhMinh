"""OpenAI Responses API adapter used by the specialist agents."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

from .config import MODEL_NAME


class ModelConfigurationError(RuntimeError):
    """Raised when the OpenAI client cannot be configured safely."""


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
        instructions = (
            f"You are {agent_name}, a specialist in an Olist e-commerce dispute "
            "investigation. Review only the supplied verified facts. Do not invent "
            "events, IDs, refunds, tracking data, or missing-delivery evidence. "
            "Arithmetic and EC_POLICY_V2 decisions are computed by deterministic "
            "code; identify inconsistencies but never replace source values. "
            "Return JSON only with this shape: "
            '{"status":"accepted|concern","summary":"brief Vietnamese summary",'
            '"observations":["zero or more concise observations"]}.'
        )
        model_input = json.dumps(
            {"task": task, "verified_facts": facts},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        response = self._client.responses.create(
            model=MODEL_NAME,
            instructions=instructions,
            input=model_input,
            max_output_tokens=300,
        )

        self.usage.request_count += 1
        response_usage = getattr(response, "usage", None)
        if response_usage is not None:
            self.usage.input_tokens += int(getattr(response_usage, "input_tokens", 0) or 0)
            self.usage.output_tokens += int(
                getattr(response_usage, "output_tokens", 0) or 0
            )

        text = response.output_text.strip()
        parsed = self._parse_json(text)
        return {
            "model": MODEL_NAME,
            "request_id": getattr(response, "_request_id", None),
            "status": parsed.get("status", "concern"),
            "summary": parsed.get("summary", text[:500]),
            "observations": parsed.get("observations", []),
        }

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
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}


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
