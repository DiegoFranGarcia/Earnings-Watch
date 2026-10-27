"""Settings read from the environment, so no email, bucket or account ID lives in code."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    sec_user_agent: str
    lake_bucket: str
    sec_rate_per_second: float


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(
            f"Environment variable {name} is not set. Add it to airflow/.env "
            "(see airflow/.env.example)."
        )
    return value


def load_settings() -> Settings:
    """Read settings at call time, never at import time, so DAG parsing stays cheap."""
    return Settings(
        sec_user_agent=_required("SEC_USER_AGENT"),
        lake_bucket=_required("LAKE_BUCKET"),
        sec_rate_per_second=float(os.environ.get("SEC_RATE_PER_SECOND", "5")),
    )
