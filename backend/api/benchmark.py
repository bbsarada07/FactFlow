"""Benchmark API routes (Phase 4B): run red-team benchmark and fetch results.

Protected by OPERATOR_TOKEN and rate limited. One run at a time under an asyncio.Lock.
"""
import asyncio
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from api.verify import RateLimiter
from database import connection
from database.models import BenchmarkRun
from services.operator_auth import require_operator
from shield import benchmark

router = APIRouter(prefix="/api/benchmark", tags=["benchmark"])
bench_limiter = RateLimiter(10, noun="Benchmark runs")
_run_lock = asyncio.Lock()


class BenchmarkRunRequest(BaseModel):
    mode: Literal["rules", "llm"] = "rules"
    sample_size: int | None = Field(default=None, ge=1, le=1000)


@router.post("/run")
async def run_benchmark(
    request: Request,
    body: BenchmarkRunRequest | None = None,
    _actor: str = Depends(require_operator),
):
    """Trigger a benchmark run over the benchmark dataset.

    Modes:
    - rules (default): rules-only analysis, deterministic, no external LLM quota used.
    - llm: full pipeline evaluation with token counting.
    Only one benchmark can run at a time.
    """
    bench_limiter.check(request.client.host if request.client else "unknown")

    if _run_lock.locked():
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "A benchmark is already currently running. Please wait for it to complete.",
        )

    req = body or BenchmarkRunRequest()
    async with _run_lock:
        try:
            res = await benchmark.run_benchmark(mode=req.mode, sample_size=req.sample_size)
        except Exception as exc:
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"Benchmark failed: {exc}") from exc

    return res


@router.get("/runs")
async def list_benchmark_runs(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    _actor: str = Depends(require_operator),
):
    """List historical benchmark runs."""
    async with connection.session_factory()() as s:
        rows = (
            await s.scalars(
                select(BenchmarkRun)
                .order_by(BenchmarkRun.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
        ).all()
        return {"count": len(rows), "runs": [r.to_dict() for r in rows]}


@router.get("/latest")
async def get_latest_benchmark_run(_actor: str = Depends(require_operator)):
    """Fetch the latest completed benchmark run."""
    async with connection.session_factory()() as s:
        row = (
            await s.scalars(
                select(BenchmarkRun)
                .where(BenchmarkRun.status == "complete")
                .order_by(BenchmarkRun.created_at.desc())
                .limit(1)
            )
        ).first()
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No benchmark runs found yet.")
        return row.to_dict()


@router.get("/runs/{run_id}")
async def get_benchmark_run(run_id: str, _actor: str = Depends(require_operator)):
    """Fetch a specific benchmark run by ID."""
    async with connection.session_factory()() as s:
        row = await s.get(BenchmarkRun, run_id)
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Benchmark run {run_id} not found.")
        return row.to_dict()
