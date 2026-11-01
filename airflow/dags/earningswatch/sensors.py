"""A deferrable sensor that waits politely for a file to appear on sec.gov.

The check itself runs in the task, through SecClient (declared User-Agent, rate limit,
the task's pool). Between checks the task defers with Airflow's built-in TimeDeltaTrigger,
so it holds no worker slot and no pool slot while it waits. A custom trigger would have
to be importable by the triggerer, which does not put the DAG folder on its import path.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from airflow.providers.standard.triggers.temporal import TimeDeltaTrigger
from airflow.sdk import BaseSensorOperator
from airflow.sdk.exceptions import AirflowSensorTimeout


class SecFileSensor(BaseSensorOperator):
    """Succeeds once `url` exists on sec.gov; checks every `poll_interval`, up to `max_wait`."""

    template_fields = ("url",)

    def __init__(
        self,
        *,
        url: str,
        poll_interval: dt.timedelta = dt.timedelta(hours=6),
        max_wait: dt.timedelta = dt.timedelta(days=45),
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.url = url
        self.poll_interval = poll_interval
        self.max_wait = max_wait

    def poke(self, context: Any) -> bool:
        from earningswatch.config import load_settings
        from earningswatch.sec_client import SecClient

        settings = load_settings()
        with SecClient(settings.sec_user_agent, settings.sec_rate_per_second) as sec:
            return sec.exists(self.url)

    def execute(self, context: Any, event: Any = None) -> None:
        """Check now; if the file is not there yet, sleep in the triggerer and check again."""
        if self.poke(context):
            self.log.info("Published: %s", self.url)
            return
        run_time = context.get("logical_date") or context["dag_run"].run_after
        if dt.datetime.now(dt.UTC) >= run_time + self.max_wait:
            raise AirflowSensorTimeout(f"{self.url} still not published after {self.max_wait}")
        self.log.info("Not published yet: %s. Checking again in %s.", self.url, self.poll_interval)
        self.defer(trigger=TimeDeltaTrigger(self.poll_interval), method_name="execute")
