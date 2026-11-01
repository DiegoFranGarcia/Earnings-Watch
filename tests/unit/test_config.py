"""Unit tests for reading settings from the environment."""

from __future__ import annotations

import pytest

from earningswatch.config import load_settings


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    monkeypatch.setenv("SEC_USER_AGENT", "EarningsWatch test@example.com")
    monkeypatch.setenv("LAKE_BUCKET", "earnings-watch-test")
    monkeypatch.delenv("SEC_RATE_PER_SECOND", raising=False)
    monkeypatch.delenv("FSDS_BASE_URL", raising=False)
    monkeypatch.delenv("COMPANY_TICKERS_URL", raising=False)
    return monkeypatch


def test_reads_settings(env: pytest.MonkeyPatch) -> None:
    settings = load_settings()

    assert settings.sec_user_agent == "EarningsWatch test@example.com"
    assert settings.lake_bucket == "earnings-watch-test"
    assert settings.sec_rate_per_second == 5.0
    assert settings.fsds_base_url.startswith("https://www.sec.gov/")
    assert settings.company_tickers_url.endswith("/company_tickers_exchange.json")


def test_missing_setting_names_the_variable(env: pytest.MonkeyPatch) -> None:
    env.delenv("LAKE_BUCKET")

    with pytest.raises(RuntimeError, match="LAKE_BUCKET"):
        load_settings()


def test_blank_counts_as_missing(env: pytest.MonkeyPatch) -> None:
    env.setenv("SEC_USER_AGENT", "   ")

    with pytest.raises(RuntimeError, match="SEC_USER_AGENT"):
        load_settings()
