"""CLI entry point for the 50-case Olist dispute investigation run."""

from __future__ import annotations

import argparse
import json
import platform
import sys
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ecommerce_agents import CoordinatorAgent, OlistRepository
from ecommerce_agents.config import (
    FRAMEWORK_NAME,
    MODEL_API,
    MODEL_NAME,
    MODEL_PARAMETER_SIZE,
    MODEL_PROVIDER,
    POLICY_VERSION,
)
from ecommerce_agents.llm import OfflineModelClient, OpenAIModelClient
from ecommerce_agents.tracing import TraceWriter


def load_cases(input_dir: Path) -> list[tuple[Path, dict[str, Any]]]:
    paths = sorted(input_dir.glob("EC_*.json"))
    if not paths:
        raise FileNotFoundError(f"No EC_*.json cases found in {input_dir}")

    cases: list[tuple[Path, dict[str, Any]]] = []
    seen_case_ids: set[str] = set()
    for path in paths:
        with path.open("r", encoding="utf-8-sig") as handle:
            case = json.load(handle)
        case_id = case.get("case_id")
        if not isinstance(case_id, str) or not case_id:
            raise ValueError(f"{path}: missing case_id")
        if case_id in seen_case_ids:
            raise ValueError(f"Duplicate case_id: {case_id}")
        if path.stem != case_id:
            raise ValueError(f"Filename {path.name} does not match case_id {case_id}")
        seen_case_ids.add(case_id)
        cases.append((path, case))
    return cases


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    temporary.replace(path)


def write_output_zip(zip_path: Path, output_dir: Path, names: set[str]) -> None:
    temporary = zip_path.with_suffix(zip_path.suffix + ".tmp")
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(names):
            archive.write(output_dir / name, arcname=name)
    temporary.replace(zip_path)


def run_pipeline(
    data_dir: Path,
    input_dir: Path,
    output_dir: Path,
    trace_file: Path,
    metadata_file: Path,
    zip_file: Path,
    require_50: bool = True,
    offline: bool = False,
) -> dict[str, Any]:
    cases = load_cases(input_dir)
    if require_50 and len(cases) != 50:
        raise ValueError(f"Expected exactly 50 cases, found {len(cases)}")

    target_order_ids = [
        case["customer_request"]["claimed_order_id"] for _, case in cases
    ]
    model = OfflineModelClient() if offline else OpenAIModelClient()
    repository = OlistRepository(data_dir, target_order_ids)
    output_dir.mkdir(parents=True, exist_ok=True)

    issue_counts: Counter[str] = Counter()
    with TraceWriter(trace_file) as trace:
        coordinator = CoordinatorAgent(repository, trace, model)
        for input_path, case in cases:
            result = coordinator.process(case)
            write_json(output_dir / input_path.name, result)
            issue_counts[result["case_assessment"]["primary_issue"]] += 1

    expected_names = {path.name for path, _ in cases}
    actual_names = {path.name for path in output_dir.glob("EC_*.json")}
    if actual_names != expected_names:
        raise RuntimeError(
            "Output case files do not match input case files: "
            f"missing={sorted(expected_names - actual_names)}, "
            f"extra={sorted(actual_names - expected_names)}"
        )
    write_output_zip(zip_file, output_dir, expected_names)

    metadata = {
        "model": {
            "provider": MODEL_PROVIDER,
            "name": MODEL_NAME,
            "parameter_size": MODEL_PARAMETER_SIZE,
            "api": MODEL_API,
            "execution_mode": "offline-development" if offline else "openai-api",
            "usage": model.usage.as_dict(),
            "role": (
                "Specialist domain review; verified CSV arithmetic and final hard gate "
                "remain deterministic."
            ),
        },
        "framework": FRAMEWORK_NAME,
        "runtime": {
            "language": "Python",
            "python_version": platform.python_version(),
            "platform": platform.platform(),
        },
        "policy_version": POLICY_VERSION,
        "latest_run": {
            "completed_at_utc": datetime.now(timezone.utc).isoformat(),
            "case_count": len(cases),
            "output_count": len(actual_names),
            "primary_issue_counts": dict(sorted(issue_counts.items())),
            "trace_file": str(trace_file),
            "zip_file": str(zip_file),
            "status": "completed_and_verified",
        },
    }
    write_json(metadata_file, metadata)
    return metadata


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run GPT-4o-mini-assisted multi-agent EC_POLICY_V2 investigations"
    )
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--input-dir", type=Path, default=Path("input"))
    parser.add_argument("--output-dir", type=Path, default=Path("output"))
    parser.add_argument("--trace-file", type=Path, default=Path("trace.jsonl"))
    parser.add_argument("--metadata-file", type=Path, default=Path("metadata.json"))
    parser.add_argument("--zip-file", type=Path, default=Path("output.zip"))
    parser.add_argument(
        "--allow-partial",
        action="store_true",
        help="Allow a non-50 case set (intended only for development tests)",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Skip OpenAI calls for local development only; not for the submitted trace",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        metadata = run_pipeline(
            data_dir=args.data_dir,
            input_dir=args.input_dir,
            output_dir=args.output_dir,
            trace_file=args.trace_file,
            metadata_file=args.metadata_file,
            zip_file=args.zip_file,
            require_50=not args.allow_partial,
            offline=args.offline,
        )
    except Exception as exc:  # CLI boundary: show a concise hard-gate failure.
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    run = metadata["latest_run"]
    print(
        f'Processed and verified {run["case_count"]} cases; '
        f'outputs={run["output_count"]}; trace={run["trace_file"]}'
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
