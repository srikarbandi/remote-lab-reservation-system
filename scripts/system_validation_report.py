"""Generate the System Validation Report from the execution register and the run logs.

    python scripts/system_validation_report.py            # writes docs/reports/system-validation-report.md
    python scripts/system_validation_report.py --check    # exit 1 if the committed report is out of date

Everything in the report comes from files in the repository:

- ``docs/test-execution/execution-register.csv`` for every case status, build, tester and date;
- the run logs the register links to, for the deviations from the STP that each executed case recorded;
- the drill and load-test logs, listed as partial evidence that does *not* mark a case executed.

Nothing is typed in by hand, so the report cannot claim more than the register does. A case counts as
executed only when its status is Pass or Fail.
"""

import argparse
import csv
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTER = ROOT / "docs" / "test-execution" / "execution-register.csv"
REPORT = ROOT / "docs" / "reports" / "system-validation-report.md"
PARTIAL_EVIDENCE_DIRS = ("drill-logs", "load-test-logs")
STATUSES = ("Pass", "Fail", "Blocked", "Not executed")
EXECUTED = {"Pass", "Fail"}
DEFERRED = "Deferred"  # an approved deferral is a separate disposition (STP 13)
DEVIATIONS_HEADING = "## Deviations from the STP"


def load_register(path: Path = REGISTER) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def status_counts(rows: list[dict]) -> Counter:
    return Counter(row["status"] for row in rows)


def _cell(text: str) -> str:
    """Make text safe inside a Markdown table cell."""
    return " ".join(text.split()).replace("|", "\\|")


def _requirements(row: dict) -> list[str]:
    return [item.strip() for item in row["requirements"].split(";") if item.strip()]


def incomplete_records(rows: list[dict]) -> list[str]:
    """Executed or blocked rows that lack the fields the STP says a result must carry."""
    problems = []
    for row in rows:
        if row["status"] == "Not executed":
            continue
        missing = [
            name
            for name in ("build_commit", "tester", "executed_at", "actual_result", "evidence_link")
            if not row[name].strip()
        ]
        if missing:
            problems.append(f"{row['case_id']} ({row['status']}) has no {', '.join(missing)}")
    return problems


def requirement_status(rows: list[dict]) -> list[tuple[str, list[str], str]]:
    """For each requirement: its cases and whether they all passed, some did, or none did."""
    cases: dict[str, list[dict]] = {}
    for row in rows:
        for requirement in _requirements(row):
            cases.setdefault(requirement, []).append(row)
    result = []
    for requirement in sorted(cases):
        linked = cases[requirement]
        passed = sum(1 for row in linked if row["status"] == "Pass")
        if passed == len(linked):
            state = "Validated"
        elif passed:
            state = "Partly validated"
        else:
            state = "Not validated"
        result.append((requirement, [row["case_id"] for row in linked], state))
    return result


def _percent(part: int, whole: int) -> str:
    return f"{100 * part / whole:.1f}%" if whole else "undefined"


def stp_metrics(rows: list[dict]) -> list[tuple[str, str, str]]:
    """The STP section 14 metrics that the register can answer: (name, value, how it was worked out)."""
    counts = status_counts(rows)
    planned = [row for row in rows if row["status"] != DEFERRED]
    executed = sum(counts[s] for s in EXECUTED)
    requirements = requirement_status(planned)
    validated = sum(1 for _, _, state in requirements if state == "Validated")
    return [
        (
            "Execution coverage",
            _percent(executed, len(planned)),
            f"{executed} cases with Pass or Fail of {len(planned)} non-deferred planned cases; "
            f"{counts['Blocked']} Blocked reported separately",
        ),
        (
            "Pass rate",
            _percent(counts["Pass"], executed),
            f"{counts['Pass']} passed of {executed} executed",
        ),
        (
            "Requirement coverage",
            _percent(validated, len(requirements)),
            f"{validated} of {len(requirements)} requirements have every mapped case passed; "
            f"{counts[DEFERRED]} deferred cases reported separately",
        ),
    ]


def exit_criteria(rows: list[dict]) -> list[tuple[str, int, int]]:
    """STP 5.2 criteria the register can answer: (criterion, cases met, cases in scope)."""

    def passed(selected: list[dict]) -> tuple[int, int]:
        return sum(1 for row in selected if row["status"] == "Pass"), len(selected)

    planned = [row for row in rows if row["status"] != DEFERRED]
    functional = [row for row in rows if row["case_id"].startswith("TC-F-")]
    high = [row for row in functional if row["priority"] == "High"]
    medium = [row for row in functional if row["priority"] == "Medium"]
    nonfunctional = [row for row in rows if row["case_id"].startswith("TC-NF-")]
    security = [row for row in rows if row["case_id"].startswith("TC-SR-")]
    executed = sum(1 for row in planned if row["status"] in EXECUTED)
    return [
        ("Every non-deferred case is executed (Pass or Fail)", executed, len(planned)),
        ("Every High-priority functional case passes", *passed(high)),
        ("Every non-functional case passes", *passed(nonfunctional)),
        ("Every security case passes", *passed(security)),
        ("Medium-priority functional cases pass (or have an approved deferral)", *passed(medium)),
    ]


def deviations_by_text(rows: list[dict], root: Path = ROOT) -> dict[str, list[str]]:
    """Deviations written in each case's run log, with the cases that share each one."""
    found: dict[str, list[str]] = {}
    for row in rows:
        link = row["evidence_link"].strip()
        if row["status"] == "Not executed" or not link.endswith(".md"):
            continue
        log = root / link
        if not log.is_file():
            continue
        in_section = False
        for line in log.read_text(encoding="utf-8").splitlines():
            if line.strip() == DEVIATIONS_HEADING:
                in_section = True
            elif in_section and line.startswith("- "):
                found.setdefault(line[2:].strip(), []).append(row["case_id"])
            elif in_section and line.strip() and not line.startswith("- "):
                break
    return found


def partial_evidence(rows: list[dict], root: Path = ROOT) -> list[dict]:
    """Drill and load-test logs: real runs that are not the formal execution of their case."""
    status_of = {row["case_id"]: row["status"] for row in rows}
    found = []
    for directory in PARTIAL_EVIDENCE_DIRS:
        for log in sorted((root / "docs" / "test-execution" / directory).glob("*.md")):
            text = log.read_text(encoding="utf-8")
            heading = text.splitlines()[0].lstrip("# ").strip() if text else log.name
            run_type = re.search(r"^\| Run type \| (.+) \|$", text, re.MULTILINE)
            case_id = re.match(r"(TC-[A-Z]+-\d+)", heading)
            found.append(
                {
                    "path": log.relative_to(root).as_posix(),
                    "heading": heading,
                    "run_type": run_type.group(1) if run_type else "not stated",
                    "case_id": case_id.group(1) if case_id else "",
                    "register_status": status_of.get(case_id.group(1), "not in register") if case_id else "",
                }
            )
    return found


def build_identity(root: Path = ROOT) -> str:
    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=root, capture_output=True, text=True, check=True
        ).stdout.strip()

    try:
        branch = git("rev-parse", "--abbrev-ref", "HEAD")
        commit = git("rev-parse", "--short", "HEAD")
    except (OSError, subprocess.CalledProcessError):
        return "not a git checkout"
    return f"`{branch}` @ `{commit}`"


def render(rows: list[dict], generated: str, build: str, root: Path = ROOT) -> str:
    counts = status_counts(rows)
    total = len(rows)
    problems = incomplete_records(rows)
    out: list[str] = []
    add = out.append

    add("# System Validation Report")
    add("")
    add(
        "Team 16, Remote Laboratory Equipment Reservation System. Generated by "
        "`scripts/system_validation_report.py` from `docs/test-execution/execution-register.csv` and the "
        "run logs it links to; do not edit by hand."
    )
    add("")
    if total == 0:
        add("> **No cases.** The execution register has no rows, so nothing has been validated.")
    elif counts["Pass"] == total:
        add(f"> **Complete.** All {total} STP cases have a recorded Pass.")
    else:
        add(
            f"> **Interim report. System validation is not complete.** {counts['Pass']} of {total} STP cases "
            f"have a recorded Pass, {counts['Fail']} Fail, {counts['Blocked']} are Blocked and "
            f"{counts['Not executed']} are not executed. Regenerate this report after the remaining "
            "modules are merged and the cases are run."
        )
    add("")
    add("| Item | Value |")
    add("|---|---|")
    add(f"| Generated | {generated} |")
    add(f"| Branch and commit | {build} |")
    add("| Source | `docs/test-execution/execution-register.csv` |")
    add("")

    add("## Summary")
    add("")
    add("| Status | Cases |")
    add("|---|---|")
    for status in STATUSES:
        add(f"| {status} | {counts[status]} |")
    for status in sorted(set(counts) - set(STATUSES)):
        add(f"| {_cell(status)} | {counts[status]} |")
    add(f"| **Total** | **{total}** |")
    add("")
    add(f"Executed (Pass or Fail): {sum(counts[s] for s in EXECUTED)} of {total}.")
    add("")
    add(
        "A case is executed only when its steps were run as written and the result recorded in the register "
        "(Pass or Fail). Blocked means a step needs something that does not exist yet; it is neither a "
        "pass nor a fail. Automated unit and integration tests support a case but do not mark it executed."
    )
    add("")
    levels = sorted({row["level"] for row in rows})
    add("| Level | Pass | Fail | Blocked | Not executed | Total |")
    add("|---|---|---|---|---|---|")
    for level in levels:
        here = status_counts([row for row in rows if row["level"] == level])
        add(
            f"| {level} | {here['Pass']} | {here['Fail']} | {here['Blocked']} | {here['Not executed']} | "
            f"{sum(here.values())} |"
        )
    add("")
    if problems:
        add("**Register problems.** These rows are marked as run but are missing fields the STP requires:")
        add("")
        for problem in problems:
            add(f"- {problem}")
        add("")

    add("## STP metrics (section 14)")
    add("")
    add("| Metric | Value | Worked out from |")
    add("|---|---|---|")
    for name, value, basis in stp_metrics(rows):
        add(f"| {name} | {value} | {_cell(basis)} |")
    add("")
    add(
        "Requirements under acceptance are taken to be every requirement that an STP case lists. Defect "
        "metrics (aging, open defects by severity, density) come from the defect register, not from this "
        "report."
    )
    add("")
    add("## Exit criteria (STP 5.2)")
    add("")
    add("| Criterion | Cases | Met |")
    add("|---|---|---|")
    criteria = exit_criteria(rows)
    for criterion, met, scope in criteria:
        add(f"| {criterion} | {met} of {scope} | {'Yes' if scope and met == scope else 'No'} |")
    add("")
    if all(scope and met == scope for _, met, scope in criteria):
        add(
            "The case-based exit criteria are met. Defects and the review of evidence are assessed "
            "outside this report."
        )
    else:
        add(
            "**The exit criteria are not met.** The criteria about critical and major defects and about the "
            "review of evidence are assessed outside this report."
        )
    add("")
    add("## Result for every STP case")
    add("")
    add("| Case | Title | Level | Status | Build | Tester | Date | Evidence |")
    add("|---|---|---|---|---|---|---|---|")
    for row in rows:
        evidence = f"[log]({row['evidence_link']})" if row["evidence_link"].strip() else ""
        # Links are relative to docs/reports/.
        evidence = evidence.replace("](docs/", "](../")
        build_cell = f"`{row['build_commit']}`" if row["build_commit"].strip() else ""
        add(
            f"| {row['case_id']} | {_cell(row['title'])} | {row['level']} | {row['status']} | {build_cell} | "
            f"{_cell(row['tester'])} | {row['executed_at']} | {evidence} |"
        )
    add("")

    run_rows = [row for row in rows if row["status"] != "Not executed"]
    if run_rows:
        add("## What the executed and blocked cases showed")
        add("")
        add("| Case | Status | Observed |")
        add("|---|---|---|")
        for row in run_rows:
            add(f"| {row['case_id']} | {row['status']} | {_cell(row['actual_result'])} |")
        add("")
        deviations = deviations_by_text(rows, root)
        if deviations:
            add("### Deviations from the STP recorded in those runs")
            add("")
            add("Quote these whenever a result above is quoted.")
            add("")
            add("| Deviation | Cases |")
            add("|---|---|")
            for text, cases in deviations.items():
                add(f"| {_cell(text)} | {', '.join(cases)} |")
            add("")

    waiting = [row for row in rows if row["status"] == "Not executed"]
    if waiting:
        add("## Not executed")
        add("")
        add(
            "No run has been recorded in the execution register for these cases. The partial evidence "
            "below, if any, does not change that."
        )
        add("")
        for level in levels:
            ids = [row["case_id"] for row in waiting if row["level"] == level]
            if ids:
                add(f"- **{level} ({len(ids)}):** {', '.join(ids)}")
        add("")

    partial = partial_evidence(rows, root)
    if partial:
        add("## Partial evidence (does not mark a case executed)")
        add("")
        add(
            "These are real runs, kept as logs, but they were not the formal execution the STP describes, so "
            "the register status of their case is unchanged."
        )
        add("")
        add("| Log | Result in the log | Run type | Case status in the register |")
        add("|---|---|---|---|")
        for item in partial:
            link = "../" + item["path"].removeprefix("docs/")
            add(
                f"| [{Path(item['path']).name}]({link}) | {_cell(item['heading'])} | "
                f"{_cell(item['run_type'])} | {item['register_status']} |"
            )
        add("")

    add("## Requirements")
    add("")
    add(
        "A requirement is Validated only when every STP case that lists it has a recorded Pass. This table "
        "is a reading of the register, not a separate judgement."
    )
    add("")
    add("| Requirement | STP cases | State |")
    add("|---|---|---|")
    for requirement, case_ids, state in requirement_status(rows):
        add(f"| {requirement} | {', '.join(case_ids)} | {state} |")
    add("")

    reports = root / "docs" / "reports"
    related = [
        (name, label)
        for name, label in (
            ("unit-test-report.md", "Unit Test Report"),
            ("code-coverage-report.md", "Code Coverage Report"),
            ("branch-coverage-report.md", "Branch Coverage Report"),
        )
        if (reports / name).is_file()
    ]
    if related:
        add("## Related reports")
        add("")
        for name, label in related:
            add(f"- [{label}]({name})")
        add("")

    add("## Regenerating")
    add("")
    add("```bash")
    add("python scripts/system_validation_report.py")
    add("```")
    add("")
    return "\n".join(out)


def generate(root: Path = ROOT, now: datetime | None = None) -> str:
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M UTC")
    register = root / "docs" / "test-execution" / "execution-register.csv"
    return render(load_register(register), stamp, build_identity(root), root)


def _without_volatile_lines(text: str) -> str:
    """Drop the generation time and the commit, which change on every run."""
    return "\n".join(
        line for line in text.splitlines() if not line.startswith(("| Generated |", "| Branch and commit |"))
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=REPORT)
    parser.add_argument("--check", action="store_true", help="Fail if the report on disk is out of date.")
    args = parser.parse_args(argv)

    text = generate()
    if args.check:
        current = args.out.read_text(encoding="utf-8") if args.out.is_file() else ""
        if _without_volatile_lines(current) != _without_volatile_lines(text):
            print(
                f"{args.out} is out of date; run python scripts/system_validation_report.py", file=sys.stderr
            )
            return 1
        print(f"{args.out} is up to date")
        return 0
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
