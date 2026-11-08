"""Alerts to Discord: task failures, and deadlines the daily pipeline misses.

The webhook URL comes from DISCORD_WEBHOOK_URL, a secret kept out of git. Posting never raises:
an alert must not fail the task it reports on, so any problem is logged instead.
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)

WEBHOOK_ENV = "DISCORD_WEBHOOK_URL"
DISCORD_LIMIT = 2000  # characters per message


def failure_message(
    dag_id: str, task_id: str, run_id: str, try_number: int, log_url: str, error: object
) -> str:
    """One readable message: what failed, where, the first line of why, and the log link."""
    lines = str(error).strip().splitlines() if error is not None else []
    reason = lines[0][:300] if lines else "(no exception recorded)"
    text = (
        f"❌ **{dag_id}** › `{task_id}` failed (try {try_number})\n"
        f"run: `{run_id}`\n"
        f"error: {reason}\n"
        f"log: {log_url}"
    )
    return text[:DISCORD_LIMIT]


def deadline_message(dag_id: str, deadline: str, run_id: str | None) -> str:
    return (
        f"⏰ **{dag_id}** had not finished by {deadline}\n"
        f"run: `{run_id or 'unknown'}`\n"
        "Nothing may have failed: check for a run that is stuck or never started."
    )


def post(text: str, url: str | None = None) -> bool:
    """Post a message to the Discord webhook. Returns whether it was delivered."""
    url = url or os.environ.get(WEBHOOK_ENV)
    if not url:
        log.warning("%s is not set; alert not sent: %s", WEBHOOK_ENV, text)
        return False
    try:
        import requests

        response = requests.post(url, json={"content": text}, timeout=10)
        response.raise_for_status()
    except Exception:  # noqa: BLE001 - an alert must never fail the task it reports on
        log.exception("Discord alert could not be delivered: %s", text)
        return False
    return True


def notify_failure(context) -> None:
    """on_failure_callback: runs once a task has failed for good (after its retries)."""
    ti = context["ti"]
    post(
        failure_message(
            ti.dag_id, ti.task_id, ti.run_id, ti.try_number, ti.log_url, context.get("exception")
        )
    )


async def notify_deadline_missed(dag_id: str, deadline: str, context=None) -> None:
    """Deadline Alert callback. Airflow awaits it in the triggerer, passing the context."""
    import asyncio

    run_id = None
    if isinstance(context, dict):
        dag_run = context.get("dag_run") or {}
        run_id = dag_run.get("run_id") if isinstance(dag_run, dict) else None
    await asyncio.to_thread(post, deadline_message(dag_id, deadline, run_id))
