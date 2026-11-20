"""Unit tests for reading task attempts from Airflow's API and merging them into AUDIT.

The API is faked with the responses a real Airflow 3.3.2 (FAB auth manager) returned for a task
that failed once and then succeeded, one that always failed, and a mapped task, checked against
a running Airflow while this was written. Snowflake is a recording cursor.
"""

from __future__ import annotations

import datetime as dt

import pytest

from earningswatch import task_history as th

BASE = "http://airflow-apiserver:8080"
RUN = "scheduled__2026-11-20T06:00:00+00:00"


def ti(task_id: str, state: str, try_number: int = 1, map_index: int = -1, **over) -> dict:
    return {
        "dag_id": "sec_daily_index",
        "dag_run_id": RUN,
        "task_id": task_id,
        "map_index": map_index,
        "state": state,
        "try_number": try_number,
        "start_date": "2026-11-20T06:00:05.123456Z",
        "end_date": "2026-11-20T06:01:05.123456Z",
        "duration": 60.0,
        "operator": "_PythonDecoratedOperator",
        **over,
    }


class Response:
    def __init__(self, status: int, body: dict) -> None:
        self.status_code, self._body, self.text = status, body, str(body)

    def json(self) -> dict:
        return self._body


class FakeApi:
    """Answers the four requests the recorder makes; records each one."""

    def __init__(self, task_instances: list[dict], tries: dict[str, list[dict]]) -> None:
        self.task_instances, self.tries, self.calls = task_instances, tries, []

    def post(self, url, json=None, timeout=None):
        self.calls.append(("POST", url, json))
        if json["password"] != "right":  # noqa: S105 - the fake API's test password
            return Response(401, {"detail": "Invalid credentials"})
        return Response(201, {"access_token": "token-1"})

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append(("GET", url, params))
        assert headers == {"Authorization": "Bearer token-1"}
        if url.endswith("/dagRuns"):
            runs = [{"dag_id": "sec_daily_index", "dag_run_id": RUN, "run_type": "scheduled"}]
            return Response(200, {"dag_runs": runs, "total_entries": 1})
        if url.endswith("/taskInstances"):
            page = self.task_instances[params["offset"] : params["offset"] + params["limit"]]
            return Response(
                200, {"task_instances": page, "total_entries": len(self.task_instances)}
            )
        if url.endswith("/tries"):
            return Response(200, {"task_instances": self.tries[url], "total_entries": 2})
        raise AssertionError(url)


def test_a_fresh_token_each_run_and_a_refusal_that_never_repeats_the_password() -> None:
    api = FakeApi([], {})
    assert th.get_token(api, BASE, "task-history", "right") == "token-1"
    with pytest.raises(th.ApiError, match="signing in as task-history: HTTP 401") as error:
        th.get_token(api, BASE, "task-history", "wrong")
    assert "wrong" not in str(error.value)
    assert api.calls[0] == (
        "POST", f"{BASE}/auth/token", {"username": "task-history", "password": "right"}
    )  # fmt: skip


def test_retried_tasks_bring_every_try_and_unfinished_ones_wait() -> None:
    retried = ti("fetch_index", "success", try_number=2)
    tries_url = th.tries_path(BASE, retried)
    api = FakeApi(
        [ti("land", "success"), retried, ti("load", "failed"), ti("later", "running")],
        {tries_url: [ti("fetch_index", "failed", 1), ti("fetch_index", "success", 2)]},
    )
    attempts = th.read_attempts(api, BASE, "token-1", dt.datetime(2026, 11, 17, tzinfo=dt.UTC))
    assert [(a["task_id"], a["try_number"], a["state"]) for a in attempts] == [
        ("land", 1, "success"),
        ("fetch_index", 1, "failed"),
        ("fetch_index", 2, "success"),
        ("load", 1, "failed"),
    ]
    assert {a["run_type"] for a in attempts} == {"scheduled"}
    # Stored as naive UTC (TIMESTAMP_NTZ).
    started = dt.datetime(2026, 11, 20, 6, 0, 5, 123456, tzinfo=dt.UTC).replace(tzinfo=None)
    assert attempts[0]["started_at"] == started
    # Only the retried task is asked for its tries.
    assert [c[1] for c in api.calls if c[1].endswith("/tries")] == [tries_url]
    assert th.summarize(attempts) == {"attempts": 4, "failed_tries": 2, "recovered": 1}


def test_every_page_is_read_in_a_fixed_order_from_the_window_on() -> None:
    api = FakeApi([ti(f"t{n}", "success") for n in range(th.PAGE * 2 + 5)], {})
    attempts = th.read_attempts(api, BASE, "token-1", dt.datetime(2026, 11, 17, tzinfo=dt.UTC))
    assert len(attempts) == th.PAGE * 2 + 5
    pages = [c[2] for c in api.calls if c[1].endswith("/taskInstances")]
    assert [p["offset"] for p in pages] == [0, th.PAGE, th.PAGE * 2]
    assert all(p["order_by"] == "id" for p in pages)
    assert pages[0]["run_after_gte"] == "2026-11-17T00:00:00+00:00"


def test_run_ids_are_quoted_and_mapped_tasks_name_their_index() -> None:
    assert th.tries_path(BASE, ti("load", "success")) == (
        f"{BASE}/api/v2/dags/sec_daily_index/dagRuns/"
        "scheduled__2026-11-20T06%3A00%3A00%2B00%3A00/taskInstances/load/tries"
    )
    assert th.tries_path(BASE, ti("each", "success", map_index=7)).endswith(
        "/taskInstances/each/7/tries"
    )


def test_a_task_that_never_ran_is_kept_without_times() -> None:
    never = ti("publish", "upstream_failed", 0, start_date=None, end_date=None)
    row = th.to_attempt(never, None)
    assert (row["try_number"], row["started_at"], row["ended_at"]) == (0, None, None)


class Cursor:
    def __init__(self) -> None:
        self.statements, self.rows = [], []

    def execute(self, sql, params=None):
        self.statements.append(" ".join(sql.split()))

    def executemany(self, sql, rows):
        self.statements.append(" ".join(sql.split()))
        self.rows.extend(rows)


def test_attempts_are_merged_on_their_key_so_reading_a_day_again_changes_nothing() -> None:
    cursor = Cursor()
    attempt = th.to_attempt(ti("load", "failed"), "scheduled")
    assert th.merge_attempts(cursor, [attempt]) == 1
    create, temp, insert, merge = cursor.statements
    assert create.startswith("CREATE TABLE IF NOT EXISTS AUDIT.AIRFLOW_TASK_ATTEMPTS")
    assert temp == "CREATE TEMPORARY TABLE ATTEMPTS_IN LIKE AUDIT.AIRFLOW_TASK_ATTEMPTS"
    assert insert.startswith("INSERT INTO ATTEMPTS_IN (dag_id, run_id, run_type, task_id")
    assert (
        "ON t.dag_id = s.dag_id AND t.run_id = s.run_id AND t.task_id = s.task_id "
        "AND t.map_index = s.map_index AND t.try_number = s.try_number"
    ) in merge
    assert "WHEN MATCHED THEN UPDATE SET run_type = s.run_type, state = s.state" in merge
    assert cursor.rows[0][:7] == (
        "sec_daily_index", RUN, "scheduled", "load", -1, 1, "failed"
    )  # fmt: skip


def test_no_attempts_only_makes_sure_the_table_exists() -> None:
    cursor = Cursor()
    assert th.merge_attempts(cursor, []) == 0
    assert len(cursor.statements) == 1
