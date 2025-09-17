import json
from pathlib import Path

from tools.run_summary_to_metrics import iter_metrics


def test_iter_metrics_includes_observability(tmp_path: Path) -> None:
    run_data = {
        "run_id": "RUN-TEST",
        "env": "dev",
        "tests": [],
        "criteria": [],
    }
    observability = {
        "auth": {"stage": "cua", "success": True},
        "exploration": {"coverage_percent": 0.85, "visited_count": 5, "skipped_count": 1},
        "crawl": {"visited_count": 4, "skipped_count": 2, "health_ratio": 0.6667},
        "guardrails": {"exploration": {"rate_limit": 1}, "crawl": {"blocklist": 2}},
    }

    metrics = list(iter_metrics(run_data, None, observability))

    metric_names = {name for name, *_ in metrics}
    assert "gazeqa_auth_success" in metric_names
    assert "gazeqa_exploration_coverage_percent" in metric_names
    assert "gazeqa_guardrail_events_total" in metric_names

    guardrail_metric = next(
        item for item in metrics if item[0] == "gazeqa_guardrail_events_total" and item[1]["type"] == "blocklist"
    )
    assert guardrail_metric[2] == 2.0
