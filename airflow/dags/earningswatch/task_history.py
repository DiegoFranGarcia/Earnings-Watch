"""Every attempt of every task, read from Airflow's own records and kept in AUDIT.

Airflow's metadata database is the system of record for task runs: every try, failed or not,
with its state and times. Airflow 3 does not let task code query that database, so the
record_task_history DAG reads it through Airflow's REST API, as a user with the read-only
Viewer role, and merges each attempt into AUDIT.AIRFLOW_TASK_ATTEMPTS. A failure that a retry
recovered is kept as two rows (try 1 failed, try 2 succeeded): the honest reliability signal,
which a failure callback could not record. Reading Airflow, not writing from a callback, also
means nothing is lost when Snowflake is the thing that is down: the next run catches up.
"""

from __future__ import annotations

import datetime as dt
from urllib.parse import quote

TABLE = "AUDIT.AIRFLOW_TASK_ATTEMPTS"
TABLE_SQL = (
    f"CREATE TABLE IF NOT EXISTS {TABLE} ("
    "dag_id VARCHAR, run_id VARCHAR, run_type VARCHAR, task_id VARCHAR, map_index INTEGER, "
    "try_number INTEGER, state VARCHAR, started_at TIMESTAMP_NTZ, ended_at TIMESTAMP_NTZ, "
    "duration_seconds FLOAT, operator VARCHAR, recorded_at TIMESTAMP_NTZ)"
)
COLUMNS = (
    "dag_id", "run_id", "run_type", "task_id", "map_index", "try_number", "state",
    "started_at", "ended_at", "duration_seconds", "operator",
)  # fmt: skip
KEY = ("dag_id", "run_id", "task_id", "map_index", "try_number")

# States a try ends in. Anything else (queued, running, deferred, up_for_retry while it waits,
# ...) is still in progress: a later run records it once it has finished.
FINISHED = frozenset({"success", "failed", "skipped", "upstream_failed", "removed"})
# Where the task finds the API (the Compose service name) and whom it signs in as.
API_URL = "http://airflow-apiserver:8080"
USER = "task-history"
# The API's largest page (the [api] maximum_page_limit setting's default).
PAGE = 100
LOOKBACK = dt.timedelta(days=3)


class ApiError(RuntimeError):
    """The Airflow API refused or failed a request (the message never includes a password)."""


def _check(response, what: str):
    if response.status_code >= 400:
        raise ApiError(f"{what}: HTTP {response.status_code} {response.text[:200]}")
    return response.json()


def get_token(session, base_url: str, username: str, password: str) -> str:
    """A fresh, short-lived access token for this run; never stored anywhere."""
    response = session.post(
        f"{base_url}/auth/token",
        json={"username": username, "password": password},
        timeout=30,
    )
    return _check(response, f"signing in as {username}")["access_token"]


def _pages(session, url: str, params: dict, headers: dict, key: str):
    """Every item of a paged list, a page at a time, ordered so no item is skipped or repeated."""
    offset = 0
    while True:
        response = session.get(
            url, params={**params, "limit": PAGE, "offset": offset}, headers=headers, timeout=60
        )
        body = _check(response, f"listing {key}")
        items = body[key]
        yield from items
        offset += len(items)
        if not items or offset >= body["total_entries"]:
            return


def _time(value: str | None) -> dt.datetime | None:
    """An API time (ISO 8601, UTC) as a naive UTC datetime, as TIMESTAMP_NTZ stores it."""
    if not value:
        return None
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.astimezone(dt.UTC).replace(tzinfo=None)


def to_attempt(item: dict, run_type: str | None) -> dict:
    """One try, from a task instance or one entry of its tries, as a row of the table."""
    return {
        "dag_id": item["dag_id"],
        "run_id": item["dag_run_id"],
        "run_type": run_type,
        "task_id": item["task_id"],
        "map_index": int(item.get("map_index", -1)),
        "try_number": int(item.get("try_number") or 0),
        "state": item.get("state"),
        "started_at": _time(item.get("start_date")),
        "ended_at": _time(item.get("end_date")),
        "duration_seconds": item.get("duration"),
        "operator": item.get("operator"),
    }


def tries_path(base_url: str, ti: dict) -> str:
    """The API path listing every try of one task instance (mapped instances add their index)."""
    dag, run, task = (quote(str(ti[k]), safe="") for k in ("dag_id", "dag_run_id", "task_id"))
    mapped = f"/{ti['map_index']}" if int(ti.get("map_index", -1)) >= 0 else ""
    return f"{base_url}/api/v2/dags/{dag}/dagRuns/{run}/taskInstances/{task}{mapped}/tries"


def read_attempts(session, base_url: str, token: str, since: dt.datetime) -> list[dict]:
    """Every finished try of every task in runs from `since` on.

    A task that ran once is its own record. Only a task on a later try is asked for its tries,
    one request each: most tasks never retry, so a day of runs costs a few pages and a handful
    of requests, not one per task.
    """
    headers = {"Authorization": f"Bearer {token}"}
    window = {"run_after_gte": since.astimezone(dt.UTC).isoformat()}
    runs = {
        (run["dag_id"], run["dag_run_id"]): run.get("run_type")
        for run in _pages(session, f"{base_url}/api/v2/dags/~/dagRuns", window, headers, "dag_runs")
    }
    attempts = []
    for ti in _pages(
        session,
        f"{base_url}/api/v2/dags/~/dagRuns/~/taskInstances",
        {**window, "order_by": "id"},
        headers,
        "task_instances",
    ):
        run_type = runs.get((ti["dag_id"], ti["dag_run_id"]))
        if int(ti.get("try_number") or 0) > 1:
            tries = _check(
                session.get(tries_path(base_url, ti), headers=headers, timeout=60),
                f"listing the tries of {ti['dag_id']}.{ti['task_id']}",
            )["task_instances"]
        else:
            tries = [ti]
        attempts.extend(to_attempt(t, run_type) for t in tries if t.get("state") in FINISHED)
    return attempts


def merge_attempts(cursor, attempts: list[dict]) -> int:
    """Insert new tries and update ones seen before (a run read while it was still going).

    Keyed on DAG, run, task, map index and try, so reading the same days again changes nothing.
    """
    cursor.execute(TABLE_SQL)
    if not attempts:
        return 0
    cursor.execute(
        f"CREATE TEMPORARY TABLE ATTEMPTS_IN LIKE {TABLE}"  # noqa: S608 - constants only
    )
    names = ", ".join(COLUMNS)
    cursor.executemany(
        f"INSERT INTO ATTEMPTS_IN ({names}) VALUES ({', '.join(['%s'] * len(COLUMNS))})",  # noqa: S608
        [tuple(a[c] for c in COLUMNS) for a in attempts],
    )
    on = " AND ".join(f"t.{k} = s.{k}" for k in KEY)
    updates = ", ".join(f"{c} = s.{c}" for c in COLUMNS if c not in KEY)
    cursor.execute(
        f"MERGE INTO {TABLE} AS t USING ATTEMPTS_IN AS s ON {on} "  # noqa: S608 - constants only
        f"WHEN MATCHED THEN UPDATE SET {updates}, recorded_at = SYSDATE() "
        f"WHEN NOT MATCHED THEN INSERT ({names}, recorded_at) "
        f"VALUES ({', '.join('s.' + c for c in COLUMNS)}, SYSDATE())"
    )
    return len(attempts)


def summarize(attempts: list[dict]) -> dict[str, int]:
    """Counts for the task's log: tries, failed tries, and tasks a retry recovered."""
    failed = [a for a in attempts if a["state"] == "failed"]
    succeeded = {
        (a["dag_id"], a["run_id"], a["task_id"], a["map_index"])
        for a in attempts
        if a["state"] == "success"
    }
    recovered = {
        (a["dag_id"], a["run_id"], a["task_id"], a["map_index"])
        for a in failed
        if (a["dag_id"], a["run_id"], a["task_id"], a["map_index"]) in succeeded
    }
    return {"attempts": len(attempts), "failed_tries": len(failed), "recovered": len(recovered)}
