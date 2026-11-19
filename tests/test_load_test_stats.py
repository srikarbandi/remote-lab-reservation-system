"""Statistics and verdict rules of the TC-NF-001 load test tool (scripts/load_test.py).

The tool decides whether LAB-NF-001 is met, so its arithmetic is tested directly: nearest-rank
percentiles, nothing excluded, errors and timeouts counted, and PASS only for a complete run.
"""

import argparse
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import load_test  # noqa: E402


def _sample(seconds, status=200, endpoint="catalogue"):
    return load_test.Sample(endpoint, seconds, status, None if status else "TimeoutError", True)


def _stats(name="catalogue", passed=True):
    return load_test.EndpointStats(name, 100, 0 if passed else 1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, passed)


def test_tc_nf_001_percentile_uses_nearest_rank():
    values = [float(n) for n in range(1, 101)]

    assert load_test.percentile(values, 50) == 50
    assert load_test.percentile(values, 95) == 95
    assert load_test.percentile(values, 99) == 99
    assert load_test.percentile([7.0], 95) == 7.0
    # With 10 samples the 95th percentile is the 10th value, not the 9th (rank rounds up).
    assert load_test.percentile([float(n) for n in range(1, 11)], 95) == 10.0
    assert load_test.percentile([float(n) for n in range(1, 11)], 50) == 5.0


def test_tc_nf_001_slow_successful_requests_are_not_excluded():
    # 6 of 100 requests are slow but successful: they push the 95th percentile over the limit.
    samples = [_sample(0.1)] * 94 + [_sample(3.0)] * 6

    stats = load_test.summarise("catalogue", samples)

    assert stats.p95 == 3.0
    assert stats.worst == 3.0
    assert not stats.passed


def test_tc_nf_001_five_percent_slow_requests_still_meet_the_limit():
    samples = [_sample(0.1)] * 95 + [_sample(3.0)] * 5

    stats = load_test.summarise("catalogue", samples)

    assert stats.p95 == 0.1
    assert stats.passed


def test_tc_nf_001_one_server_error_fails_the_endpoint():
    samples = [_sample(0.1)] * 99 + [_sample(0.1, status=500)]

    stats = load_test.summarise("catalogue", samples)

    assert stats.errors == 1
    assert not stats.passed


def test_tc_nf_001_a_timeout_is_an_error_and_its_time_is_kept():
    samples = [_sample(0.1)] * 99 + [_sample(30.0, status=None)]

    stats = load_test.summarise("catalogue", samples)

    assert stats.errors == 1
    assert stats.worst == 30.0
    assert not stats.passed


def test_tc_nf_001_client_errors_on_valid_requests_also_fail():
    samples = [_sample(0.1)] * 99 + [_sample(0.1, status=422)]

    assert load_test.summarise("catalogue", samples).errors == 1


def test_tc_nf_001_complete_error_free_run_within_the_limit_passes():
    stats = [_stats("catalogue"), _stats("availability"), _stats("history")]

    assert load_test.verdict(stats, not_measured={}, preconditions_met=True) == "PASS"


def test_tc_nf_001_run_missing_an_endpoint_is_incomplete_not_a_pass():
    stats = [_stats("catalogue"), _stats("availability")]

    result = load_test.verdict(
        stats, not_measured={"history": "not implemented yet (HTTP 404)"}, preconditions_met=True
    )

    assert result == "INCOMPLETE"


def test_tc_nf_001_run_below_the_required_dataset_is_incomplete_not_a_pass():
    stats = [_stats("catalogue"), _stats("availability"), _stats("history")]

    assert load_test.verdict(stats, not_measured={}, preconditions_met=False) == "INCOMPLETE"


def test_tc_nf_001_a_failing_endpoint_fails_the_run_even_when_another_is_missing():
    stats = [_stats("catalogue", passed=False)]

    assert load_test.verdict(stats, {"history": "not implemented yet (HTTP 404)"}, True) == "FAIL"


def test_tc_nf_001_mix_rejects_unknown_endpoints():
    assert load_test.parse_mix("catalogue=3,history=1") == {"catalogue": 3, "history": 1}
    with pytest.raises(argparse.ArgumentTypeError):
        load_test.parse_mix("login=1")
