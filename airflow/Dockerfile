# EarningsWatch Airflow image.
# Change AIRFLOW_VERSION here only; the constraints file follows it automatically.
ARG AIRFLOW_VERSION=3.3.2
ARG PYTHON_VERSION=3.12

# The slim image: Airflow and almost no providers. requirements.txt installs exactly what the
# pipeline uses; the full image preinstalled ~30 providers, and every one was attack surface.
FROM apache/airflow:slim-${AIRFLOW_VERSION}-python${PYTHON_VERSION}
ARG AIRFLOW_VERSION
ARG PYTHON_VERSION

# dbt in its own virtual environment, so its dependencies never clash with Airflow's.
USER root
# dbt-constraints.txt freezes every library in it, so every build installs the same versions.
COPY dbt-requirements.txt dbt-constraints.txt /tmp/
RUN python -m venv /opt/dbt_venv \
    && /opt/dbt_venv/bin/pip install --no-cache-dir \
      -r /tmp/dbt-requirements.txt --constraint /tmp/dbt-constraints.txt \
    && rm /tmp/dbt-requirements.txt /tmp/dbt-constraints.txt

# Airflow providers, pinned by Airflow's own tested constraints file, except for the few pins in
# constraint-overrides.txt (each fixes a published vulnerability). The overridden packages are
# also installed by name, so pip replaces the versions the base image already has.
USER airflow
COPY --chown=airflow:0 requirements.txt constraint-overrides.txt /tmp/
RUN curl -fsSL -o /tmp/constraints.txt \
      "https://raw.githubusercontent.com/apache/airflow/constraints-${AIRFLOW_VERSION}/constraints-${PYTHON_VERSION}.txt" \
    && grep -vE '^[[:space:]]*(#|$)' /tmp/constraint-overrides.txt > /tmp/overrides.txt \
    && cut -d= -f1 /tmp/overrides.txt | while read -r name; do sed -i "/^${name}==/Id" /tmp/constraints.txt; done \
    && cat /tmp/overrides.txt >> /tmp/constraints.txt \
    && pip install --no-cache-dir \
      "apache-airflow==${AIRFLOW_VERSION}" \
      -r /tmp/requirements.txt \
      -r /tmp/overrides.txt \
      --constraint /tmp/constraints.txt \
    && rm /tmp/requirements.txt /tmp/constraint-overrides.txt /tmp/overrides.txt /tmp/constraints.txt
