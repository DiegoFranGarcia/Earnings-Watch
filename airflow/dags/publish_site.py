"""Publish the public site's data after every good dbt build.

Triggered by the marts asset, which dbt_build updates only after its volume gate, every model and
every test passed: the site can never show data the circuit breaker held back (ADR 10).

1. export: generate the dbt docs (one static HTML file, with the production catalog) and publish
   them as this run's export: the run's folder, its manifest, then exports/site/current.json
   (earningswatch.site_export). Stage 9 adds the dashboard's Parquet files to the same export.
2. trigger_site_deploy: start .github/workflows/site.yml, which builds the site from that export
   and deploys it to GitHub Pages. If this fails, the export is still published and the
   workflow's daily schedule deploys it; the failure alerts anyway, because an expired token
   must not go unnoticed.

Unpaused on creation, unlike the project's default: it only ever runs after a good dbt build, and
the host is awake only in the early morning, when nobody is there to unpause it.
"""

from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

import pendulum
from airflow.sdk import Asset, dag, task
from airflow.sdk.exceptions import AirflowFailException

from earningswatch.callbacks import notify_failure

MARTS = Asset("marts")

DBT_PROJECT = Path(os.environ.get("DBT_PROJECT_DIR", "/opt/airflow/dbt"))
DBT_EXECUTABLE = os.environ.get("DBT_EXECUTABLE", "/opt/dbt_venv/bin/dbt")


@dag(
    schedule=[MARTS],
    start_date=pendulum.datetime(2026, 11, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    is_paused_upon_creation=False,
    default_args={
        "owner": "earningswatch",
        "on_failure_callback": notify_failure,
        "retries": 2,
        "retry_delay": timedelta(minutes=2),
        "retry_exponential_backoff": True,
        "max_retry_delay": timedelta(minutes=20),
        "execution_timeout": timedelta(minutes=15),
    },
    tags=["site", "serving"],
    doc_md=__doc__,
)
def publish_site():
    @task(pool="snowflake", execution_timeout=timedelta(minutes=20))
    def export(**context) -> dict:
        """The dbt docs, published as this run's export; the pointer is written last."""
        import tempfile

        import boto3

        from earningswatch import site_export
        from earningswatch.config import load_settings

        settings = load_settings()
        with tempfile.TemporaryDirectory(prefix="earningswatch-site-") as tmp:
            docs = site_export.generate_dbt_docs(
                DBT_EXECUTABLE, DBT_PROJECT, Path(tmp), context["run_id"]
            )
            manifest = site_export.publish(
                boto3.client("s3"),
                settings.lake_bucket,
                context["run_id"],
                [docs],
                release=os.environ.get("AIRFLOW_IMAGE", "unknown"),
            )
        for entry in manifest["files"]:
            print(f"{entry['key']}: {entry['bytes']:,} bytes, sha256 {entry['sha256']}")
        print(f"{site_export.POINTER_KEY} now points at {manifest['folder']}")
        return {"folder": manifest["folder"], "exported_at": manifest["exported_at"]}

    @task(retries=3, execution_timeout=timedelta(minutes=5))
    def trigger_site_deploy(published: dict) -> None:
        """Start the site workflow; the export is already published whether or not this works."""
        import boto3

        from earningswatch import site_export
        from earningswatch.config import load_settings

        settings = load_settings()
        if not (settings.site_dispatch_secret_id and settings.site_github_repository):
            raise AirflowFailException(  # configuration: retrying cannot help
                "SITE_DISPATCH_SECRET_ID and SITE_GITHUB_REPOSITORY must be set "
                "(deploy/compose.yaml)"
            )
        token = site_export.read_token(
            boto3.client("secretsmanager", region_name="us-east-1"),
            settings.site_dispatch_secret_id,
        )
        site_export.dispatch_site_workflow(
            token, settings.site_github_repository, published["folder"]
        )
        print(f"started {site_export.SITE_WORKFLOW} for {published['folder']}")

    trigger_site_deploy(export())


publish_site()
