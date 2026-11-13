"""The System Validation Report is generated from the execution register; it must not claim more than
the register does. These tests need no database."""

import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import system_validation_report as svr  # noqa: E402

HEADER = [
    "case_id",
    "title",
    "requirements",
    "level",
    "priority",
    "status",
    "build_commit",
    "tester",
    "executed_at",
    "actual_result",
    "evidence_link",
    "defect_id",
]


def row(case_id, status="Not executed", requirements="LAB-F-001", level="System", **extra):
    base = dict.fromkeys(HEADER, "")
    base.update(
        case_id=case_id,
        title=f"Title of {case_id}",
        requirements=requirements,
        level=level,
        priority="High",
        status=status,
    )
    base.update(extra)
    return base


def executed(case_id, status="Pass", **extra):
    values = dict(
        build_commit="abc1234",
        tester="Sreekar Bandi",
        executed_at="2026-11-11",
        actual_result="all steps passed",
        evidence_link=f"docs/test-execution/runs/2026-11-11/{case_id.lower()}.md",
    )
    values.update(extra)
    return row(case_id, status, **values)


def render(rows, root):
    return svr.render(rows, "2026-11-11 06:00 UTC", "`main` @ `abc1234`", root)


def write_log(root, case_id, deviations):
    path = root / "docs" / "test-execution" / "runs" / "2026-11-11" / f"{case_id.lower()}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(f"- {d}" for d in deviations)
    path.write_text(
        f"# {case_id}\n\n## Steps\n\nx\n\n{svr.DEVIATIONS_HEADING}\n\n{body}\n\nFooter sentence.\n\n## Later section\n\n- Not a deviation.\n"
    )


# --- headline numbers --------------------------------------------------------------------------


def test_status_counts_and_interim_banner(tmp_path):
    rows = [executed("TC-A-1"), row("TC-A-2", "Blocked"), row("TC-A-3"), row("TC-A-4")]

    text = render(rows, tmp_path)

    assert "Interim report. System validation is not complete." in text
    assert "1 of 4 STP cases have a recorded Pass, 0 Fail, 1 are Blocked and 2 are not executed" in text
    assert "| Pass | 1 |" in text and "| Blocked | 1 |" in text and "| Not executed | 2 |" in text
    assert "Executed (Pass or Fail): 1 of 4." in text


def test_complete_only_when_every_case_passes(tmp_path):
    text = render([executed("TC-A-1"), executed("TC-A-2")], tmp_path)

    assert "**Complete.** All 2 STP cases have a recorded Pass." in text
    assert "Interim report" not in text


def test_a_fail_keeps_the_report_interim(tmp_path):
    text = render([executed("TC-A-1"), executed("TC-A-2", "Fail")], tmp_path)

    assert "Interim report" in text
    assert "1 Fail" in text


def test_blocked_is_not_counted_as_executed(tmp_path):
    text = render([row("TC-A-1", "Blocked", actual_result="endpoint missing")], tmp_path)

    assert "Executed (Pass or Fail): 0 of 1." in text


# --- requirements ------------------------------------------------------------------------------


def test_requirement_is_validated_only_when_all_its_cases_pass():
    rows = [
        executed("TC-A-1", requirements="LAB-F-001"),
        executed("TC-A-2", requirements="LAB-F-001; LAB-F-002"),
        row("TC-A-3", requirements="LAB-F-002; LAB-F-003"),
    ]

    states = {req: state for req, _, state in svr.requirement_status(rows)}

    assert states == {
        "LAB-F-001": "Validated",
        "LAB-F-002": "Partly validated",
        "LAB-F-003": "Not validated",
    }


def test_a_blocked_case_does_not_validate_its_requirement():
    states = {req: s for req, _, s in svr.requirement_status([row("TC-A-1", "Blocked")])}

    assert states["LAB-F-001"] == "Not validated"


# --- the register must carry what the STP requires ---------------------------------------------


def test_pass_without_evidence_is_reported_as_a_register_problem(tmp_path):
    rows = [executed("TC-A-1", evidence_link="", build_commit="")]

    text = render(rows, tmp_path)

    assert "TC-A-1 (Pass) has no build_commit, evidence_link" in text


def test_complete_records_and_unexecuted_rows_raise_no_problem(tmp_path):
    rows = [executed("TC-A-1"), row("TC-A-2")]

    assert svr.incomplete_records(rows) == []
    assert "Register problems" not in render(rows, tmp_path)


# --- deviations come from the run logs ---------------------------------------------------------


def test_shared_deviations_are_listed_once_with_every_case(tmp_path):
    write_log(tmp_path, "TC-A-1", ["Header login.", "Only for A1."])
    write_log(tmp_path, "TC-A-2", ["Header login."])
    rows = [executed("TC-A-1"), executed("TC-A-2")]

    found = svr.deviations_by_text(rows, tmp_path)

    assert found == {"Header login.": ["TC-A-1", "TC-A-2"], "Only for A1.": ["TC-A-1"]}
    text = render(rows, tmp_path)
    assert "| Header login. | TC-A-1, TC-A-2 |" in text


def test_deviation_reading_stops_at_the_end_of_the_list(tmp_path):
    write_log(tmp_path, "TC-A-1", ["Only deviation."])

    found = svr.deviations_by_text([executed("TC-A-1")], tmp_path)

    assert list(found) == ["Only deviation."]


def test_missing_log_file_is_skipped_not_invented(tmp_path):
    assert svr.deviations_by_text([executed("TC-A-1")], tmp_path) == {}


def test_not_executed_case_never_contributes_deviations(tmp_path):
    write_log(tmp_path, "TC-A-1", ["Should not appear."])
    rows = [row("TC-A-1", evidence_link="docs/test-execution/runs/2026-11-11/tc-a-1.md")]

    assert svr.deviations_by_text(rows, tmp_path) == {}


# --- partial evidence --------------------------------------------------------------------------


def test_drill_log_is_listed_without_changing_the_case_status(tmp_path):
    drills = tmp_path / "docs" / "test-execution" / "drill-logs"
    drills.mkdir(parents=True)
    (drills / "dry-run.md").write_text(
        "# TC-NF-005 Backup and restore drill: PASS\n\n| Item | Value |\n|---|---|\n"
        "| Run type | Dry run in a development environment |\n"
    )
    rows = [row("TC-NF-005", level="Recovery")]

    items = svr.partial_evidence(rows, tmp_path)
    text = render(rows, tmp_path)

    assert items[0]["register_status"] == "Not executed"
    assert items[0]["run_type"] == "Dry run in a development environment"
    assert "Dry run in a development environment | Not executed |" in text
    assert "| Recovery | 0 | 0 | 0 | 1 | 1 |" in text


def test_no_partial_evidence_section_when_there_are_no_logs(tmp_path):
    assert "Partial evidence" not in render([row("TC-A-1")], tmp_path)


# --- formatting --------------------------------------------------------------------------------


def test_pipes_and_newlines_in_results_do_not_break_the_table(tmp_path):
    rows = [executed("TC-A-1", actual_result="saw a | pipe\nand a newline")]

    text = render(rows, tmp_path)

    assert "| TC-A-1 | Pass | saw a \\| pipe and a newline |" in text


def test_evidence_links_are_relative_to_the_report_folder(tmp_path):
    text = render([executed("TC-A-1")], tmp_path)

    assert "[log](../test-execution/runs/2026-11-11/tc-a-1.md)" in text


def test_empty_register_still_renders(tmp_path):
    text = render([], tmp_path)

    assert "**Complete.**" not in text  # nothing to validate is not a pass
    assert "no cases" in text.lower()
    assert "| **Total** | **0** |" in text


# --- file round trip ---------------------------------------------------------------------------


def test_register_file_round_trip_and_check_mode(tmp_path):
    register = tmp_path / "docs" / "test-execution" / "execution-register.csv"
    register.parent.mkdir(parents=True)
    with register.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=HEADER)
        writer.writeheader()
        writer.writerow(executed("TC-A-1"))
        writer.writerow(row("TC-A-2"))
    write_log(tmp_path, "TC-A-1", ["Header login."])
    out = tmp_path / "docs" / "reports" / "system-validation-report.md"
    now = datetime(2026, 11, 11, 6, 0, tzinfo=timezone.utc)

    out.parent.mkdir(parents=True)
    out.write_text(svr.generate(tmp_path, now))

    # Same register, a later time: still up to date.
    later = svr._without_volatile_lines(svr.generate(tmp_path, now.replace(hour=9)))
    assert later == svr._without_volatile_lines(out.read_text())

    # A changed register makes the committed report stale.
    with register.open("a", newline="") as handle:
        csv.DictWriter(handle, fieldnames=HEADER).writerow(row("TC-A-3"))
    stale = svr._without_volatile_lines(svr.generate(tmp_path, now))
    assert stale != svr._without_volatile_lines(out.read_text())


@pytest.mark.parametrize("status", ["Deferred", "Pass (retest)"])
def test_unknown_status_is_shown_not_dropped(status, tmp_path):
    text = render([row("TC-A-1", status)], tmp_path)

    assert f"| {status} | 1 |" in text


# --- STP section 14 metrics and 5.2 exit criteria -------------------------------------------------


def metric(rows, name):
    return next(value for n, value, _ in svr.stp_metrics(rows) if n == name)


def test_metrics_follow_the_stp_definitions():
    rows = [
        executed("TC-A-1", requirements="R1"),
        executed("TC-A-2", requirements="R2"),
        executed("TC-A-3", "Fail", requirements="R3"),
        row("TC-A-4", "Blocked", requirements="R4"),
        row("TC-A-5", requirements="R5"),
        row("TC-A-6", requirements="R6"),
        row("TC-A-7", requirements="R7"),
        row("TC-A-8", requirements="R8"),
        row("TC-A-9", "Deferred", requirements="R9"),
    ]

    # 3 executed of 8 non-deferred; 2 passed of 3 executed; 2 of 8 requirements (the deferred one is excluded).
    assert metric(rows, "Execution coverage") == "37.5%"
    assert metric(rows, "Pass rate") == "66.7%"
    assert metric(rows, "Requirement coverage") == "25.0%"


def test_pass_rate_is_undefined_when_nothing_has_been_executed():
    rows = [row("TC-A-1"), row("TC-A-2", "Blocked")]

    assert metric(rows, "Pass rate") == "undefined"
    assert metric(rows, "Execution coverage") == "0.0%"


def test_blocked_cases_do_not_raise_execution_coverage():
    assert metric([row("TC-A-1", "Blocked"), executed("TC-A-2")], "Execution coverage") == "50.0%"


def exit_rows():
    return [
        executed("TC-F-001", priority="High") | {"priority": "High"},
        row("TC-F-002", priority="High") | {"priority": "High"},
        executed("TC-F-003") | {"priority": "Medium"},
        executed("TC-NF-001"),
        executed("TC-SR-001"),
        row("TC-SR-002"),
    ]


def test_exit_criteria_count_the_right_cases():
    got = {name: (met, scope) for name, met, scope in svr.exit_criteria(exit_rows())}

    assert got["Every non-deferred case is executed (Pass or Fail)"] == (4, 6)
    assert got["Every High-priority functional case passes"] == (1, 2)
    assert got["Every non-functional case passes"] == (1, 1)
    assert got["Every security case passes"] == (1, 2)
    assert got["Medium-priority functional cases pass (or have an approved deferral)"] == (1, 1)


def test_exit_criteria_report_says_not_met_until_everything_passes(tmp_path):
    text = render(exit_rows(), tmp_path)

    assert "**The exit criteria are not met.**" in text
    assert "| Every High-priority functional case passes | 1 of 2 | No |" in text
    assert "| Every non-functional case passes | 1 of 1 | Yes |" in text


def test_a_criterion_with_no_cases_is_not_reported_as_met(tmp_path):
    rows = [executed("TC-F-001") | {"priority": "High"}]

    text = render(rows, tmp_path)

    assert "| Every security case passes | 0 of 0 | No |" in text
    assert "**The exit criteria are not met.**" in text


def test_exit_criteria_met_when_every_case_in_scope_passes(tmp_path):
    rows = [
        executed("TC-F-001") | {"priority": "High"},
        executed("TC-F-002") | {"priority": "Medium"},
        executed("TC-NF-001"),
        executed("TC-SR-001"),
    ]

    text = render(rows, tmp_path)

    assert "The case-based exit criteria are met." in text
    assert "not met" not in text
