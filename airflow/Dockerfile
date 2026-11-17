# EarningsWatch Airflow image.
# Change AIRFLOW_VERSION here only; the constraints file follows it automatically.
ARG AIRFLOW_VERSION=3.3.2
ARG PYTHON_VERSION=3.12

# The slim image: Airflow and almost no providers. requirements.txt installs exactly what the
# pipeline uses; the full image preinstalled ~30 providers, and every one was attack surface.
# Pinned by digest: a tag can be rebuilt under the same name. Dependabot proposes Apache's
# rebuilds as pull requests (.github/dependabot.yml). An Airflow upgrade changes this line and
# AIRFLOW_VERSION together; the check below fails the build if they disagree.
FROM apache/airflow:slim-3.3.2-python3.12@sha256:a54e7bd6c4d7a17e55cd14b0ead257877b8f8111680d2692cbdba2ff32bd3ff3
ARG AIRFLOW_VERSION
ARG PYTHON_VERSION
RUN installed="$(python -c 'import importlib.metadata as m; print(m.version("apache-airflow"))')" \
    && if [ "$installed" != "$AIRFLOW_VERSION" ]; then \
      echo "base image check: Airflow $installed in the base image, but AIRFLOW_VERSION is $AIRFLOW_VERSION" >&2; \
      exit 1; \
    fi

USER root

# Packages nothing in the pipeline runs, removed. Each carried published vulnerabilities, and a
# tool that is not there cannot be used by an intruder either. Removing downloads nothing, so
# every build gives the same result. perl takes postgresql-client with it (pg_dump and psql run
# in the Postgres container), and libexpat1 takes git (no DAG bundle or dbt package uses git).
# Kept: apt (for a pinned snapshot upgrade, if one is ever needed), curl (the health checks) and
# perl-base (Essential in Debian). The check stops the build if a new base image would make the
# purge remove anything else, or has dropped one of these packages: update the list then.
ARG UNUSED_PACKAGES="apt-utils git libexpat1 liberror-perl libperl5.36 libsasl2-modules mariadb-client mariadb-client-core perl perl-modules-5.36 postgresql-client postgresql-client-18 postgresql-client-common rsync sasl2-bin"
RUN removing="$(apt-get -s purge ${UNUSED_PACKAGES} | awk '/^Purg/ {print $2}' | sort | tr '\n' ' ')" \
    && expected="$(printf '%s\n' ${UNUSED_PACKAGES} | sort | tr '\n' ' ')" \
    && if [ "$removing" != "$expected" ]; then \
      echo "package check: purging [${expected}] would remove [${removing}]; update UNUSED_PACKAGES" >&2; \
      exit 1; \
    fi \
    && DEBIAN_FRONTEND=noninteractive apt-get purge -y -q ${UNUSED_PACKAGES} \
    && for package in ${UNUSED_PACKAGES}; do \
      if dpkg-query -W -f='${Status}' "$package" 2>/dev/null | grep -q ' installed$'; then \
        echo "package check: $package is still installed" >&2; exit 1; \
      fi; \
    done

# dbt in its own virtual environment, so its dependencies never clash with Airflow's.
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
