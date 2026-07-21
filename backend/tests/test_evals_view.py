"""summarize_traces — the pure aggregation behind the admin eval dashboard (no DB).

Pins the shape the UI reads and the tolerance the trace store needs: half-populated rows
(missing totals, null latency, unknown status) must never throw, and identity is never in
the output.
"""
from app.evals_view import summarize_traces


def _r(status="ok", source="prod", latency=1000, model="claude-haiku-4-5",
       cost=0.02, inp=10000, out=200, **extra):
    return {
        "status": status, "source": source, "latency_ms": latency, "model": model,
        "totals": {"cost_usd_est": cost, "input_tokens": inp, "output_tokens": out},
        **extra,
    }


def test_empty_summary_is_all_zeros_not_a_crash():
    s = summarize_traces([])
    assert s["traces"] == 0
    assert s["ok_rate"] is None
    assert s["cost_usd"] == 0
    assert s["latency_p50_ms"] is None


def test_aggregates_counts_cost_tokens_and_status():
    rows = [_r(status="ok"), _r(status="ok"), _r(status="error", cost=0.05)]
    s = summarize_traces(rows)
    assert s["traces"] == 3
    assert s["by_status"] == {"ok": 2, "error": 1}
    assert s["ok_rate"] == round(100 * 2 / 3, 1)
    assert s["cost_usd"] == round(0.02 + 0.02 + 0.05, 4)
    assert s["tokens"] == 3 * (10000 + 200)
    assert s["by_model"] == {"claude-haiku-4-5": 3}


def test_latency_percentiles_ignore_nulls():
    rows = [_r(latency=100), _r(latency=None), _r(latency=900)]
    s = summarize_traces(rows)
    # only the two non-null latencies count
    assert s["latency_max_ms"] == 900
    assert s["latency_p50_ms"] in (100, 900)  # midpoint of a 2-element sorted list


def test_tolerates_missing_totals_and_unknown_status():
    rows = [{"status": None, "source": None, "latency_ms": None, "model": None, "totals": None}]
    s = summarize_traces(rows)  # must not raise
    assert s["traces"] == 1
    assert s["by_status"] == {"unknown": 1}
    assert s["by_source"] == {"prod": 1}
    assert s["cost_usd"] == 0


def test_source_split_separates_prod_from_eval():
    rows = [_r(source="prod"), _r(source="eval"), _r(source="eval")]
    assert summarize_traces(rows)["by_source"] == {"prod": 1, "eval": 2}
