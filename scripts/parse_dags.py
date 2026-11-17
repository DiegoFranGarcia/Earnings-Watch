"""Parse the DAG folder the way Airflow's DAG processor does, and print the result as one line.

Deterministic, unlike asking the running DAG processor (which parses in the background), and
immune to warnings Airflow prints: the result is the single line starting with PARSE_RESULT,
followed by JSON: {"dags": [...], "errors": {file: last line of the error}}.

Run inside the image:
    python - < scripts/parse_dags.py
"""

import inspect
import json
import os
import sys

# Airflow's example DAGs are off, through configuration, which every Airflow version reads. (The
# include_examples argument exists in some versions of DagBag and not in others.)
os.environ["AIRFLOW__CORE__LOAD_EXAMPLES"] = "False"

try:  # where DagBag lives in recent Airflow 3 releases
    from airflow.dag_processing.dagbag import DagBag  # noqa: E402
except ImportError:  # earlier releases
    from airflow.models.dagbag import DagBag  # noqa: E402

arguments = {"dag_folder": os.environ.get("DAG_FOLDER", "/opt/airflow/dags")}
if "include_examples" in inspect.signature(DagBag.__init__).parameters:
    arguments["include_examples"] = False
bag = DagBag(**arguments)
result = {
    "dags": sorted(bag.dag_ids),
    "errors": {
        str(path): (str(error).strip().splitlines() or ["(no message)"])[-1]
        for path, error in bag.import_errors.items()
    },
}
sys.stdout.write("PARSE_RESULT " + json.dumps(result) + "\n")
