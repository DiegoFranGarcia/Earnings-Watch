"""Import every module the DAG code can ever import, and fail if any is missing.

A smoke test that only loads the DAGs checks the imports that run at parse time. Imports inside
functions (snowflake.connector in the load tasks, for example) run only when a task runs, so a
missing library would pass the smoke test and fail at 1 AM. This reads every import statement in
the DAG code, top-level and nested, from its syntax tree, and imports each one in this environment.

Run inside the image, with the DAG folder on the Python path:
    python - < scripts/check_dag_imports.py
"""

import ast
import importlib
import os
import pathlib
import sys

DAG_FOLDER = pathlib.Path(os.environ.get("DAG_FOLDER", "/opt/airflow/dags"))


def imports_in(folder: pathlib.Path) -> tuple[set[str], set[tuple[str, str]]]:
    """Every module imported anywhere in the folder, and every (module, name) imported from one."""
    modules: set[str] = set()
    names: set[tuple[str, str]] = set()
    for path in sorted(folder.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                modules.add(node.module)
                names.update((node.module, alias.name) for alias in node.names if alias.name != "*")
    return modules, names


def missing(modules: set[str], names: set[tuple[str, str]]) -> list[str]:
    """What cannot be imported here: whole modules, or names a module does not provide."""
    problems = []
    for module in sorted(modules):
        try:
            importlib.import_module(module)
        except Exception as error:  # noqa: BLE001 - any failure to import is the finding
            problems.append(f"{module}: {type(error).__name__}: {error}")
    for module, name in sorted(names):
        if any(problem.startswith(f"{module}:") for problem in problems):
            continue
        parent = importlib.import_module(module)
        if hasattr(parent, name):
            continue
        try:
            importlib.import_module(f"{module}.{name}")
        except Exception as error:  # noqa: BLE001
            problems.append(f"from {module} import {name}: {type(error).__name__}: {error}")
    return problems


if __name__ == "__main__":
    modules, names = imports_in(DAG_FOLDER)
    problems = missing(modules, names)
    sys.stdout.write(f"{len(modules)} modules imported by the DAG code; {len(problems)} missing\n")
    for problem in problems:
        sys.stdout.write(f"  {problem}\n")
    sys.exit(1 if problems else 0)
