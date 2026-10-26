# EarningsWatch Airflow image.
# Change AIRFLOW_VERSION here only; the constraints file follows it automatically.
ARG AIRFLOW_VERSION=3.3.1
ARG PYTHON_VERSION=3.12

FROM apache/airflow:${AIRFLOW_VERSION}-python${PYTHON_VERSION}
ARG AIRFLOW_VERSION
ARG PYTHON_VERSION

# dbt in its own virtual environment, so its dependencies never clash with Airflow's.
USER root
COPY dbt-requirements.txt /tmp/dbt-requirements.txt
RUN python -m venv /opt/dbt_venv \
    && /opt/dbt_venv/bin/pip install --no-cache-dir -r /tmp/dbt-requirements.txt \
    && rm /tmp/dbt-requirements.txt

# Airflow providers, pinned by Airflow's own tested constraints file.
USER airflow
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir \
      "apache-airflow==${AIRFLOW_VERSION}" \
      -r /tmp/requirements.txt \
      --constraint "https://raw.githubusercontent.com/apache/airflow/constraints-${AIRFLOW_VERSION}/constraints-${PYTHON_VERSION}.txt"
