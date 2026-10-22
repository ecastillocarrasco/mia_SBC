"""Métricas globales agregadas del sistema de diagnóstico."""

from __future__ import annotations

from typing import Any


def compute_metrics(traces: list[Any]) -> dict[str, Any]:
    """Calcula métricas globales a partir de una ventana de trazas."""
    if not traces:
        return _empty_metrics()

    completed = [t for t in traces if t.status == "completed"]
    errors = [t for t in traces if t.status == "error"]
    running = [t for t in traces if t.status == "running"]

    latencies = sorted(t.elapsed_ms for t in completed if t.elapsed_ms is not None)
    avg_latency = int(sum(latencies) / len(latencies)) if latencies else None
    p95_latency = latencies[int(len(latencies) * 0.95)] if latencies else None

    total_input = sum(t.tokens_input for t in completed)
    total_output = sum(t.tokens_output for t in completed)
    total_cached = sum(t.tokens_cached for t in completed)
    avg_tokens = int((total_input + total_output) / len(completed)) if completed else None
    cache_hit_rate = round(total_cached / total_input, 3) if total_input else None

    tools_per_trace = [len(t.tools_called) for t in completed]
    avg_tools = round(sum(tools_per_trace) / len(tools_per_trace), 1) if tools_per_trace else None

    # Breakdown por dominio
    domain_counts: dict[str, int] = {}
    for t in traces:
        d = t.domain or "unknown"
        domain_counts[d] = domain_counts.get(d, 0) + 1

    # Tasa de warnings
    warning_traces = sum(1 for t in traces if t.warning_count > 0)
    capability_gaps = sum(
        1 for t in traces for issue in (t.issues or []) if issue.type == "CAPABILITY_MISSING"
    )

    return {
        "total_requests": len(traces),
        "completed": len(completed),
        "errors": len(errors),
        "running": len(running),
        "success_rate": round(len(completed) / len(traces), 3) if traces else 1.0,
        "error_rate": round(len(errors) / len(traces), 3) if traces else 0.0,
        "avg_latency_ms": avg_latency,
        "p95_latency_ms": p95_latency,
        "avg_tokens": avg_tokens,
        "total_input_tokens": total_input,
        "total_cached_tokens": total_cached,
        "cache_hit_rate": cache_hit_rate,
        "avg_tools_per_request": avg_tools,
        "warning_traces": warning_traces,
        "capability_gaps": capability_gaps,
        "by_domain": domain_counts,
    }


def _empty_metrics() -> dict[str, Any]:
    return {
        "total_requests": 0,
        "completed": 0,
        "errors": 0,
        "running": 0,
        "success_rate": 1.0,
        "error_rate": 0.0,
        "avg_latency_ms": None,
        "p95_latency_ms": None,
        "avg_tokens": None,
        "total_input_tokens": 0,
        "total_cached_tokens": 0,
        "cache_hit_rate": None,
        "avg_tools_per_request": None,
        "warning_traces": 0,
        "capability_gaps": 0,
        "by_domain": {},
    }
