"""Read performance load test (STP TC-NF-001, requirement LAB-NF-001).

Drives the catalogue, availability and history read endpoints with 50 concurrent users, after a
warm-up, and reports request counts, response times and errors per endpoint. The case passes only if
the 95th percentile of every core read endpoint is at most 2 seconds and there are no errors. Slow
successful requests are never dropped, and a request that times out is counted as an error and its
time is kept.

    python scripts/load_test.py --base-url http://127.0.0.1:8000 \\
        --database-url postgresql://lab:lab@localhost:5432/lab_load \\
        --log docs/test-execution/load-test-logs/<file>.md

The tool reads user and equipment ids from the (synthetic) database and sends every request over HTTP
to the running application. Start the application with scripts/load_test_app.py until the auth module
can log users in. An endpoint that is not implemented yet is listed as not measured and the result is
INCOMPLETE rather than PASS. See docs/operations/load-test.md.
"""

from __future__ import annotations

import argparse
import http.client
import math
import os
import platform
import random
import shlex
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode, urlsplit

import psycopg

P95_LIMIT_SECONDS = 2.0
REQUIRED_USERS = 50
REQUIRED_RESERVATIONS = 1000
NOT_IMPLEMENTED = {404, 405, 501}
CLIENT_SATURATION_WARNING = 0.85  # share of one core the load generator may use before we warn

ENDPOINTS = {
    "catalogue": "GET /api/equipment",
    "availability": "GET /api/equipment/{id}/availability",
    "history": "GET /api/reservations?scope=mine",
}
DEFAULT_MIX = {"catalogue": 4, "availability": 4, "history": 2}


# --- statistics -----------------------------------------------------------------------------------


def percentile(sorted_values: list[float], p: float) -> float:
    """Nearest-rank percentile of an already sorted list (no interpolation, no trimming)."""
    if not sorted_values:
        raise ValueError("no samples")
    rank = math.ceil(p / 100 * len(sorted_values))
    return sorted_values[max(rank, 1) - 1]


@dataclass
class Sample:
    endpoint: str
    seconds: float
    status: int | None  # None: no HTTP response (connection error or timeout)
    error: str | None
    measured: bool

    @property
    def failed(self) -> bool:
        return self.status is None or not 200 <= self.status < 300


@dataclass
class EndpointStats:
    name: str
    requests: int
    errors: int
    p50: float
    p90: float
    p95: float
    p99: float
    worst: float
    mean: float
    passed: bool


def summarise(name: str, samples: list[Sample], limit: float = P95_LIMIT_SECONDS) -> EndpointStats:
    times = sorted(s.seconds for s in samples)
    errors = sum(1 for s in samples if s.failed)
    p95 = percentile(times, 95)
    return EndpointStats(
        name=name,
        requests=len(samples),
        errors=errors,
        p50=percentile(times, 50),
        p90=percentile(times, 90),
        p95=p95,
        p99=percentile(times, 99),
        worst=times[-1],
        mean=sum(times) / len(times),
        passed=p95 <= limit and errors == 0,
    )


def verdict(stats: list[EndpointStats], not_measured: dict[str, str], preconditions_met: bool) -> str:
    """PASS needs every core endpoint measured, within the limit, error free, on the stated dataset."""
    if any(not s.passed for s in stats) or not stats:
        return "FAIL"
    if not_measured or not preconditions_met:
        return "INCOMPLETE"
    return "PASS"


# --- what to request ------------------------------------------------------------------------------


@dataclass
class Context:
    users: list[dict]  # {"id": str, "lab_id": str}
    equipment_by_lab: dict[str, list[str]]
    equipment_codes: list[str]
    counts: dict[str, int]
    server_version: str


def load_context(database_url: str, users: int) -> Context:
    with psycopg.connect(database_url) as conn:
        rows = conn.execute(
            "SELECT user_id::text, lab_id::text FROM lab_memberships WHERE role = 'Student' "
            "ORDER BY user_id LIMIT %s",
            (users,),
        ).fetchall()
        equipment = conn.execute("SELECT id::text, lab_id::text, code FROM equipment WHERE active").fetchall()
        counts = {
            "reservations": conn.execute("SELECT count(*) FROM reservations").fetchone()[0],
            "students": conn.execute(
                "SELECT count(*) FROM lab_memberships WHERE role = 'Student'"
            ).fetchone()[0],
            "equipment": len(equipment),
            "labs": conn.execute("SELECT count(*) FROM labs").fetchone()[0],
        }
        version = conn.execute("SHOW server_version").fetchone()[0]
    by_lab: dict[str, list[str]] = {}
    for equipment_id, lab_id, _code in equipment:
        by_lab.setdefault(lab_id, []).append(equipment_id)
    return Context(
        users=[{"id": u, "lab_id": lab} for u, lab in rows],
        equipment_by_lab=by_lab,
        equipment_codes=[code for _i, _l, code in equipment],
        counts=counts,
        server_version=version,
    )


def build_request(endpoint: str, user: dict, ctx: Context, rng: random.Random) -> str:
    if endpoint == "catalogue":
        query: dict[str, object] = {"page": rng.randint(1, 3), "page_size": 20}
        roll = rng.random()
        if roll < 0.4:
            query["lab_id"] = user["lab_id"]
        elif roll < 0.7 and ctx.equipment_codes:
            query["name"] = rng.choice(ctx.equipment_codes)[-3:]
        return "/api/equipment?" + urlencode(query)
    if endpoint == "availability":
        equipment_id = rng.choice(
            ctx.equipment_by_lab.get(user["lab_id"]) or sum(ctx.equipment_by_lab.values(), [])
        )
        day = date.today() + timedelta(days=rng.randint(0, 6))
        return f"/api/equipment/{equipment_id}/availability?date={day.isoformat()}"
    if endpoint == "history":
        return "/api/reservations?scope=mine"
    raise ValueError(endpoint)


class Client:
    """One keep-alive HTTP connection, like a browser tab, logged in as one test user."""

    def __init__(self, base_url: str, header: str, user_id: str, timeout: float):
        parts = urlsplit(base_url)
        self.host, self.port = parts.hostname, parts.port or 80
        self.headers = {header: user_id, "Accept": "application/json"}
        self.timeout = timeout
        self.conn: http.client.HTTPConnection | None = None

    def get(self, path: str) -> tuple[int | None, str | None]:
        try:
            if self.conn is None:
                self.conn = http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)
            self.conn.request("GET", path, headers=self.headers)
            response = self.conn.getresponse()
            response.read()
            if response.will_close:
                self.close()
            return response.status, None
        except (OSError, http.client.HTTPException) as exc:
            self.close()
            return None, f"{type(exc).__name__}: {exc}"

    def close(self) -> None:
        if self.conn is not None:
            self.conn.close()
            self.conn = None


def probe(base_url: str, header: str, ctx: Context, mix: dict[str, int], timeout: float, seed: int):
    """Ask each endpoint once. Returns (endpoints to drive, {endpoint: reason it is not measured})."""
    rng = random.Random(seed)
    user = ctx.users[0]
    client = Client(base_url, header, user["id"], timeout)
    active: dict[str, int] = {}
    skipped: dict[str, str] = {}
    try:
        for name, weight in mix.items():
            if weight <= 0:
                skipped[name] = "weight set to 0"
                continue
            status, error = client.get(build_request(name, user, ctx, rng))
            if status == 401:
                raise SystemExit(
                    "The server answered 401 to the X-Test-User header. Start it with "
                    "scripts/load_test_app.py (LOAD_TEST_HEADER_AUTH=1), see docs/operations/load-test.md."
                )
            if status is None:
                raise SystemExit(f"Cannot reach {base_url}: {error}")
            if status in NOT_IMPLEMENTED:
                skipped[name] = f"not implemented yet (HTTP {status})"
            else:
                active[name] = weight
    finally:
        client.close()
    return active, skipped


# --- the run --------------------------------------------------------------------------------------


@dataclass
class RunResult:
    stats: list[EndpointStats]
    not_measured: dict[str, str]
    samples: list[Sample]
    warmup_requests: int
    warmup_errors: int
    measured_seconds: float
    users: int
    status_counts: dict[str, int]
    error_examples: list[str]
    client_cpu_share: float
    started_at: datetime
    context: Context
    preconditions: list[str] = field(default_factory=list)

    @property
    def verdict(self) -> str:
        return verdict(self.stats, self.not_measured, not self.preconditions)


def run_load(
    base_url: str,
    database_url: str,
    *,
    users: int = REQUIRED_USERS,
    warmup_seconds: float = 120,
    duration_seconds: float = 600,
    think_time: float = 0.0,
    timeout: float = 30.0,
    mix: dict[str, int] | None = None,
    header: str = "X-Test-User",
    seed: int = 16,
) -> RunResult:
    mix = dict(mix or DEFAULT_MIX)
    ctx = load_context(database_url, users)
    if not ctx.users:
        raise SystemExit("No student users in the database. Seed it with scripts/synthetic_data.py.")
    preconditions = []
    if len(ctx.users) < users:
        preconditions.append(f"only {len(ctx.users)} student users exist, {users} requested")
    if users < REQUIRED_USERS:
        preconditions.append(f"{users} virtual users, the case requires {REQUIRED_USERS}")
    if ctx.counts["reservations"] < REQUIRED_RESERVATIONS:
        preconditions.append(
            f"{ctx.counts['reservations']} reservations, the case requires {REQUIRED_RESERVATIONS}"
        )

    active, skipped = probe(base_url, header, ctx, mix, timeout, seed)
    if not active:
        raise SystemExit("None of the read endpoints is available; nothing to measure.")
    names = list(active)
    weights = [active[n] for n in names]

    started_at = datetime.now(timezone.utc)
    t_start = time.perf_counter()
    measure_from = t_start + warmup_seconds
    stop_at = measure_from + duration_seconds
    cpu_start = time.process_time()
    collected: list[list[Sample]] = [[] for _ in range(users)]

    def worker(index: int) -> None:
        user = ctx.users[index % len(ctx.users)]
        rng = random.Random(seed * 1000 + index)
        client = Client(base_url, header, user["id"], timeout)
        out = collected[index]
        try:
            while time.perf_counter() < stop_at:
                endpoint = rng.choices(names, weights)[0]
                path = build_request(endpoint, user, ctx, rng)
                began = time.perf_counter()
                status, error = client.get(path)
                seconds = time.perf_counter() - began
                out.append(Sample(endpoint, seconds, status, error, began >= measure_from))
                if think_time:
                    time.sleep(rng.uniform(0.5 * think_time, 1.5 * think_time))
        finally:
            client.close()

    threads = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(users)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    wall = time.perf_counter() - t_start
    cpu_share = (time.process_time() - cpu_start) / wall if wall else 0.0

    everything = [s for per_thread in collected for s in per_thread]
    measured = [s for s in everything if s.measured]
    warm = [s for s in everything if not s.measured]
    stats = [
        summarise(n, [s for s in measured if s.endpoint == n])
        for n in names
        if any(s.endpoint == n for s in measured)
    ]
    counts: dict[str, int] = {}
    for s in measured:
        key = str(s.status) if s.status is not None else "no response"
        counts[key] = counts.get(key, 0) + 1
    examples = sorted({s.error for s in measured if s.error})[:5]
    return RunResult(
        stats=stats,
        not_measured=skipped,
        samples=measured,
        warmup_requests=len(warm),
        warmup_errors=sum(1 for s in warm if s.failed),
        measured_seconds=duration_seconds,
        users=users,
        status_counts=counts,
        error_examples=examples,
        client_cpu_share=cpu_share,
        started_at=started_at,
        context=ctx,
        preconditions=preconditions,
    )


# --- the log --------------------------------------------------------------------------------------


def _ms(seconds: float) -> str:
    return f"{seconds * 1000:,.0f} ms"


def render_log(
    result: RunResult,
    command: str,
    *,
    warmup_seconds: float,
    think_time: float,
    timeout: float,
    run_type: str,
    where: str,
    server: str,
) -> str:
    total = len(result.samples)
    errors = sum(1 for s in result.samples if s.failed)
    ctx = result.context
    pause = f"about {think_time:g} s" if think_time else f"none, constant {result.users} requests in flight"
    rate = total / result.measured_seconds
    warm = f"{warmup_seconds:g} s ({result.warmup_requests:,} requests, {result.warmup_errors} errors)"
    rows = [
        ("Result", f"**{result.verdict}**"),
        ("Run type", run_type),
        ("Started", f"{result.started_at:%Y-%m-%d %H:%M:%S} UTC"),
        ("Tool", "`scripts/load_test.py` (Python threads, `http.client`, a keep-alive connection per user)"),
        ("Virtual users", f"{result.users} concurrent, each a different student (test-header login)"),
        ("Think time", pause),
        ("Warm-up", f"{warm}; not in the figures below"),
        ("Measured window", f"{result.measured_seconds:g} s"),
        ("Requests measured", f"{total:,} ({rate:,.1f} per second), {errors} errors"),
        ("Request timeout", f"{timeout:g} s (a timeout counts as an error and its time is kept)"),
        ("Command", f"`{command}`"),
    ]
    lines = [
        f"# TC-NF-001 Read response performance: {result.verdict}",
        "",
        "Team 16, Remote Laboratory Equipment Reservation System. Generated by `scripts/load_test.py` "
        "from a real run; do not edit by hand.",
        "",
        "| Item | Value |",
        "|---|---|",
        *[f"| {k} | {v} |" for k, v in rows],
        "",
        "## Response times per endpoint",
        "",
        f"Limit: 95th percentile at most {P95_LIMIT_SECONDS:g} s and no errors. Nearest-rank percentiles "
        "over every measured request; no slow request is excluded.",
        "",
        "| Endpoint | Requests | Errors | p50 | p90 | p95 | p99 | Slowest | Mean | Result |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for s in result.stats:
        cells = [
            ENDPOINTS[s.name],
            f"{s.requests:,}",
            str(s.errors),
            _ms(s.p50),
            _ms(s.p90),
            f"**{_ms(s.p95)}**",
            _ms(s.p99),
            _ms(s.worst),
            _ms(s.mean),
            "Pass" if s.passed else "**Fail**",
        ]
        lines.append("| " + " | ".join(cells) + " |")
    if result.not_measured:
        lines += ["", "## Not measured", "", "| Endpoint | Why |", "|---|---|"]
        lines += [f"| {ENDPOINTS[n]} | {why} |" for n, why in result.not_measured.items()]
    lines += ["", "## Responses", "", "| Status | Count |", "|---|---|"]
    lines += [f"| {k} | {v:,} |" for k, v in sorted(result.status_counts.items())]
    if result.error_examples:
        lines += ["", "Error examples: " + "; ".join(f"`{e}`" for e in result.error_examples)]

    c = ctx.counts
    environment = [
        ("Reservations", f"{c['reservations']:,} (the case requires {REQUIRED_RESERVATIONS:,})"),
        ("Student users / equipment / labs", f"{c['students']} / {c['equipment']} / {c['labs']}"),
        ("PostgreSQL", ctx.server_version),
        ("Application server", server or "not stated"),
        ("Where it ran", where or "not stated"),
        (
            "Load generator host",
            f"{platform.platform()}, {os.cpu_count()} CPUs, Python {platform.python_version()}",
        ),
        ("Load generator CPU use", f"{result.client_cpu_share * 100:.0f}% of one core"),
    ]
    lines += ["", "## Dataset and environment", "", "| Item | Value |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in environment]

    lines += ["", "## What this run does and does not show", ""]
    if result.client_cpu_share >= CLIENT_SATURATION_WARNING:
        lines.append(
            "- **The load generator used most of a core, so the times may be overstated.** "
            "Run it on a separate machine."
        )
    lines += [f"- Precondition not met: {p}." for p in result.preconditions]
    if result.not_measured:
        gaps = ", ".join(result.not_measured)
        lines.append(
            f"- The case lists catalogue, availability and history reads. {gaps} could not be measured, "
            "so the case cannot be marked executed from this run."
        )
    lines += [
        "- Users are logged in with the test-only `X-Test-User` header, which skips the real login. "
        "Re-run with real logins once the auth module is merged.",
        "- The data is synthetic (`scripts/synthetic_data.py`). If the load generator, the application and "
        "the database share one host they compete for the same CPUs, so a deployment-like run needs the "
        "application and database on their own hosts.",
        "- The case is complete only when it is run on the deployment-like environment with the full mix, "
        "and the register row links to that log.",
        "",
    ]
    return "\n".join(lines)


def parse_mix(text: str) -> dict[str, int]:
    mix = {}
    for part in text.split(","):
        name, _, weight = part.partition("=")
        if name not in ENDPOINTS:
            raise argparse.ArgumentTypeError(f"unknown endpoint {name!r}; choose from {', '.join(ENDPOINTS)}")
        mix[name] = int(weight)
    return mix


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read performance load test (TC-NF-001).")
    parser.add_argument("--base-url", required=True, help="Running application, e.g. http://127.0.0.1:8000")
    parser.add_argument(
        "--database-url", required=True, help="Synthetic database the application uses (read only)."
    )
    parser.add_argument("--users", type=int, default=REQUIRED_USERS)
    parser.add_argument("--warmup-seconds", type=float, default=120)
    parser.add_argument("--duration-seconds", type=float, default=600)
    parser.add_argument("--think-time", type=float, default=0.0, help="Mean pause between a user's requests.")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument(
        "--mix", type=parse_mix, default=DEFAULT_MIX, help="e.g. catalogue=4,availability=4,history=2"
    )
    parser.add_argument("--auth-header", default="X-Test-User")
    parser.add_argument("--seed", type=int, default=16)
    parser.add_argument("--log", help="Write the Markdown log here.")
    parser.add_argument("--run-type", default="Development run")
    parser.add_argument("--where", default="", help="Where it ran, stated in the log.")
    parser.add_argument("--server", default="", help="How the application was started, stated in the log.")
    args = parser.parse_args(argv)

    result = run_load(
        args.base_url,
        args.database_url,
        users=args.users,
        warmup_seconds=args.warmup_seconds,
        duration_seconds=args.duration_seconds,
        think_time=args.think_time,
        timeout=args.timeout,
        mix=args.mix,
        header=args.auth_header,
        seed=args.seed,
    )
    for s in result.stats:
        print(
            f"{s.name:<13} n={s.requests:<7} errors={s.errors:<4} p50={_ms(s.p50):>9} p95={_ms(s.p95):>9} "
            f"p99={_ms(s.p99):>9} max={_ms(s.worst):>9}  {'pass' if s.passed else 'FAIL'}"
        )
    for name, why in result.not_measured.items():
        print(f"{name:<13} not measured: {why}")
    print(f"TC-NF-001 load test: {result.verdict}")
    if args.log:
        given = list(argv if argv is not None else sys.argv[1:])
        # The database URL may carry a password; never print it into a log.
        shown = [
            "<database-url>" if i and given[i - 1] == "--database-url" else a for i, a in enumerate(given)
        ]
        text = render_log(
            result,
            shlex.join(["python", "scripts/load_test.py", *shown]),
            warmup_seconds=args.warmup_seconds,
            think_time=args.think_time,
            timeout=args.timeout,
            run_type=args.run_type,
            where=args.where,
            server=args.server,
        )
        Path(args.log).parent.mkdir(parents=True, exist_ok=True)
        Path(args.log).write_text(text)
        print(f"Log written to {args.log}")
    return 0 if result.verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
