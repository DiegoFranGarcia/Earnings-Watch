"""A small local Spark session shared by every Spark test (starting Spark takes seconds)."""

from __future__ import annotations

import os
import shutil

import pytest


@pytest.fixture(scope="session")
def spark():
    if not (os.environ.get("JAVA_HOME") or shutil.which("java")):
        message = "Spark tests need Java 17 (set JAVA_HOME)"
        if os.environ.get("REQUIRE_SPARK_TESTS"):  # CI sets this: a silent skip would hide bugs
            pytest.fail(message)
        pytest.skip(message)
    from pyspark.sql import SparkSession

    session = (
        SparkSession.builder.master("local[2]")
        .appName("earningswatch-tests")
        .config("spark.ui.enabled", "false")
        .config("spark.sql.shuffle.partitions", "2")  # tiny data: 200 partitions is waste
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.sql.sources.partitionOverwriteMode", "dynamic")
        .config("spark.sql.parquet.compression.codec", "zstd")
        .getOrCreate()
    )
    session.sparkContext.setLogLevel("ERROR")
    yield session
    session.stop()
