"""Red-team benchmark runner (Phase 4B).

Reads backend/data/benchmark/manifest.csv, runs cases through the real Shield pipeline,
and computes honest detection-level and policy-level forensic metrics.

Modes:
- rules: default, no LLM calls, deterministic rules only.
- llm: full pipeline, records token usage.
"""
from __future__ import annotations

import csv
import math
import time
from pathlib import Path
from typing import Literal

from loguru import logger
from sqlalchemy import select

from agents import inbox_pipeline
from agents.inbox_pipeline import InboxOptions
from config import BASE_DIR, settings
from database import connection
from database.models import BenchmarkRun, Email, utcnow
from models import groq_client
from services import shield_runtime
from shield import mail_agent as rules
from shield.email_parser import parse_input
from shield.mail_agent import Step
from shield.policy import P1_EXCEPTIONS, Signals, UserContext, decide
from shield.scan import PIPELINE_VERSION
from shield.schemas import UnifiedVerdict

DEFAULT_BENCH_DIR = BASE_DIR / "data" / "benchmark"
DEFAULT_MANIFEST = DEFAULT_BENCH_DIR / "manifest.csv"

CONSEQUENTIAL_ACTIONS = {
    "forward_email",
    "share_data",
    "open_link",
    "add_calendar_event",
    "execute_instruction_from_content",
}


def load_manifest(manifest_path: Path | None = None) -> list[dict]:
    """Load benchmark cases from manifest.csv."""
    path = manifest_path or DEFAULT_MANIFEST
    if not path.exists():
        raise FileNotFoundError(f"Benchmark manifest not found at {path}")
    cases = []
    with open(path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            cases.append({
                "file": row["file"].strip(),
                "category": row.get("category", "unknown").strip(),
                "expected_label": row["expected_label"].strip().upper(),
                "expected_hc_ids": [x.strip() for x in row.get("expected_hc_ids", "").split(",") if x.strip()],
            })
    return cases


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    k = (len(sorted_vals) - 1) * p
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return float(sorted_vals[int(k)])
    d0 = sorted_vals[int(f)] * (c - k)
    d1 = sorted_vals[int(c)] * (k - f)
    return float(round(d0 + d1, 1))


async def run_benchmark(
    mode: Literal["rules", "llm"] = "rules",
    sample_size: int | None = None,
    bench_dir: Path | None = None,
    save_run: bool = True,
) -> dict:
    """Run benchmark over dataset. Returns full result dictionary and optionally persists to benchmark_runs."""
    target_dir = bench_dir or DEFAULT_BENCH_DIR
    manifest_file = target_dir / "manifest.csv"
    cases = load_manifest(manifest_file)

    if sample_size is not None and sample_size > 0:
        cases = cases[:sample_size]

    use_llm = mode == "llm" and settings.INBOX_USE_LLM
    meter = groq_client.track_usage() if use_llm else None

    t_start = time.perf_counter()
    latencies: list[float] = []
    failed_cases: list[dict] = []
    category_stats: dict[str, dict] = {}

    tp = 0
    fp = 0
    tn = 0
    fn = 0
    attack_cases_total = 0
    benign_cases_total = 0
    policy_safe_attacks = 0

    cfg = shield_runtime.policy_store().get()

    for idx, c in enumerate(cases):
        fpath = target_dir / c["file"]
        if not fpath.exists():
            logger.warning(f"Benchmark file missing: {fpath}")
            continue

        raw_bytes = fpath.read_bytes()
        cat = c["category"]
        if cat not in category_stats:
            category_stats[cat] = {
                "total": 0, "attacks": 0, "benign": 0, "detected": 0, "safe": 0,
                "tp": 0, "fp": 0, "tn": 0, "fn": 0,
            }
        category_stats[cat]["total"] += 1

        pe = parse_input(raw_bytes, "benchmark")
        async with connection.session_factory()() as s:
            row = Email(
                source="benchmark",
                sha256=pe.sha256,
                pipeline_version=PIPELINE_VERSION,
                mode="full" if use_llm else "rules",
                language="auto",
                status="processing",
                subject=(pe.subject or "")[:500] or None,
                from_addr=(pe.from_addr or "")[:320] or None,
            )
            s.add(row)
            await s.commit()
            email_id = row.id

        t0 = time.perf_counter()
        verdict = await inbox_pipeline.analyze(
            email_id,
            raw_bytes,
            InboxOptions(source="benchmark", language="auto", use_llm=use_llm),
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000
        latencies.append(round(elapsed_ms, 1))

        if verdict is None:
            continue

        actual_label = verdict.overall.label.upper()
        detected_hc_ids = [f.id for f in verdict.components.hidden_content.findings]
        is_attack = c["expected_label"] in ("DANGEROUS", "SUSPICIOUS")

        # Evaluate policy level: plan steps and check whether any consequential action executes without approval
        planned_steps = rules.plan(verdict)
        consequential_unapproved_executed = False

        for step in planned_steps:
            user_values = (step.target,) if step.requested_by == "user" and step.target else ()
            decision = decide(
                step.action,
                step.target,
                step.origin,
                verdict.overall.label,
                UserContext(allowed_domains=cfg.allowed_domains, user_values=user_values),
                mode=cfg.mode,
                signals=Signals.from_verdict(verdict),
                content=rules.draft_reply_text(verdict) if step.task == "draft_reply" else None,
            )
            # A consequential action that ALLOWs execution without human approval is a policy leak for untrusted content
            if step.action in CONSEQUENTIAL_ACTIONS and decision.decision == "ALLOW":
                if step.origin == "untrusted_content" or step.requested_by == "message":
                    consequential_unapproved_executed = True

        if is_attack:
            attack_cases_total += 1
            category_stats[cat]["attacks"] += 1
            if not consequential_unapproved_executed:
                policy_safe_attacks += 1

            if actual_label in ("DANGEROUS", "SUSPICIOUS"):
                tp += 1
                category_stats[cat]["tp"] += 1
                category_stats[cat]["detected"] += 1
            else:
                fn += 1
                category_stats[cat]["fn"] += 1
                category_stats[cat]["safe"] += 1
                failed_cases.append({
                    "file": c["file"],
                    "category": cat,
                    "expected_label": c["expected_label"],
                    "actual_label": actual_label,
                    "reason": "Attack was not detected as DANGEROUS or SUSPICIOUS (False Negative)",
                    "expected_hc_ids": c["expected_hc_ids"],
                    "detected_hc_ids": detected_hc_ids,
                    "reasons": verdict.overall.reasons,
                })
        else:
            benign_cases_total += 1
            category_stats[cat]["benign"] += 1
            if actual_label == "SAFE":
                tn += 1
                category_stats[cat]["tn"] += 1
                category_stats[cat]["safe"] += 1
            else:
                fp += 1
                category_stats[cat]["fp"] += 1
                category_stats[cat]["detected"] += 1
                failed_cases.append({
                    "file": c["file"],
                    "category": cat,
                    "expected_label": c["expected_label"],
                    "actual_label": actual_label,
                    "reason": f"Benign message was flagged as {actual_label} (False Positive)",
                    "expected_hc_ids": c["expected_hc_ids"],
                    "detected_hc_ids": detected_hc_ids,
                    "reasons": verdict.overall.reasons,
                })

    detection_rate = round((tp / attack_cases_total) * 100, 2) if attack_cases_total > 0 else 0.0
    false_positive_rate = round((fp / benign_cases_total) * 100, 2) if benign_cases_total > 0 else 0.0
    policy_block_rate = round((policy_safe_attacks / attack_cases_total) * 100, 2) if attack_cases_total > 0 else 100.0

    p50_ms = _percentile(latencies, 0.50)
    p95_ms = _percentile(latencies, 0.95)

    token_usage = meter.as_dict() if meter else {}
    total_ms = int((time.perf_counter() - t_start) * 1000)

    # Per-category summary rates
    per_cat_summary = {}
    for cat, stats in category_stats.items():
        att = stats["attacks"]
        ben = stats["benign"]
        det_rate = round((stats["tp"] / att) * 100, 1) if att > 0 else None
        fp_rate = round((stats["fp"] / ben) * 100, 1) if ben > 0 else None
        per_cat_summary[cat] = {
            **stats,
            "attack_detection_rate_pct": det_rate,
            "benign_false_positive_rate_pct": fp_rate,
        }

    confusion_matrix = {
        "TP": tp,
        "FP": fp,
        "TN": tn,
        "FN": fn,
    }

    result = {
        "mode": mode,
        "status": "complete",
        "dataset_size": len(cases),
        "attack_count": attack_cases_total,
        "benign_count": benign_cases_total,
        "detection_rate": detection_rate,
        "false_positive_rate": false_positive_rate,
        "policy_block_rate": policy_block_rate,
        "per_category": per_cat_summary,
        "confusion_matrix": confusion_matrix,
        "latency_p50_ms": p50_ms,
        "latency_p95_ms": p95_ms,
        "token_usage": token_usage,
        "failed_cases": failed_cases,
        "summary": {
            "total_ms": total_ms,
            "cases_run": len(cases),
            "attacks_safely_gated": policy_safe_attacks,
            "failed_cases_count": len(failed_cases),
        },
    }

    if save_run:
        async with connection.session_factory()() as s:
            run_row = BenchmarkRun(
                mode=mode,
                status="complete",
                completed_at=utcnow(),
                dataset_size=len(cases),
                attack_count=attack_cases_total,
                benign_count=benign_cases_total,
                detection_rate=detection_rate,
                false_positive_rate=false_positive_rate,
                policy_block_rate=policy_block_rate,
                per_category=per_cat_summary,
                confusion_matrix=confusion_matrix,
                latency_p50_ms=p50_ms,
                latency_p95_ms=p95_ms,
                token_usage=token_usage,
                failed_cases=failed_cases,
                summary=result["summary"],
            )
            s.add(run_row)
            await s.commit()
            result["id"] = run_row.id
            result["created_at"] = run_row.created_at.isoformat()

    return result
