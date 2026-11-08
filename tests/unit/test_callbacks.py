"""Unit tests for the Discord alerts: messages, delivery, and never failing the task."""

from __future__ import annotations

import asyncio
import inspect

import pytest

from earningswatch import callbacks


def test_failure_message_names_the_task_the_reason_and_the_log() -> None:
    text = callbacks.failure_message(
        "snowflake_load", "load", "manual__2026", 3, "http://localhost:8080/x",
        ValueError("not a quarter: '2026q5'\nmore detail"),
    )  # fmt: skip

    assert "**snowflake_load** › `load` failed (try 3)" in text
    assert "error: not a quarter: '2026q5'" in text and "more detail" not in text
    assert text.endswith("log: http://localhost:8080/x")


def test_messages_fit_discords_limit() -> None:
    text = callbacks.failure_message("d", "t", "r" * 3000, 1, "u", "e")
    assert len(text) <= callbacks.DISCORD_LIMIT


def test_without_a_webhook_an_alert_is_logged_not_raised(monkeypatch) -> None:
    monkeypatch.delenv(callbacks.WEBHOOK_ENV, raising=False)
    assert callbacks.post("hello") is False


def test_a_failing_webhook_never_raises(monkeypatch) -> None:
    import requests

    def broken(*args, **kwargs):
        raise requests.ConnectionError("discord is down")

    monkeypatch.setattr(requests, "post", broken)
    assert callbacks.post("hello", url="https://example.invalid/hook") is False


def test_notify_failure_reads_the_task_instance(monkeypatch) -> None:
    sent: list[str] = []
    monkeypatch.setattr(callbacks, "post", sent.append)

    class TaskInstance:
        dag_id, task_id, run_id, try_number = "dbt_build", "build.dim_company.run", "r1", 2
        log_url = "http://localhost:8080/log"

    callbacks.notify_failure({"ti": TaskInstance(), "exception": RuntimeError("boom")})

    assert len(sent) == 1 and "`build.dim_company.run` failed (try 2)" in sent[0]


def test_deadline_callback_is_awaitable_and_accepts_the_context(monkeypatch) -> None:
    sent: list[str] = []
    monkeypatch.setattr(callbacks, "post", sent.append)
    callback = callbacks.notify_deadline_missed

    # How Airflow's triggerer calls it: awaited, with the kwargs and a context.
    assert inspect.iscoroutinefunction(callback)
    assert "context" in inspect.signature(callback).parameters
    context = {"dag_run": {"run_id": "r9"}}
    asyncio.run(callback(dag_id="sec_daily_index", deadline="12:00 UTC", context=context))

    assert sent == [callbacks.deadline_message("sec_daily_index", "12:00 UTC", "r9")]
    assert "had not finished by 12:00 UTC" in sent[0] and "`r9`" in sent[0]


@pytest.mark.parametrize("context", [None, {}, {"dag_run": "not-a-dict"}])
def test_deadline_callback_tolerates_a_sparse_context(monkeypatch, context) -> None:
    sent: list[str] = []
    monkeypatch.setattr(callbacks, "post", sent.append)
    asyncio.run(callbacks.notify_deadline_missed("sec_daily_index", "12:00 UTC", context=context))
    assert "run: `unknown`" in sent[0]
