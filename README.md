# EduPredict

FastAPI service for student risk prediction using the committed LightGBM model.

| Module | Responsibility |
| --- | --- |
| `deliverable/api/main.py` | Application lifecycle, existing routes and orchestration |
| `deliverable/api/api_support.py` | Admin authentication and sanitized HTTP errors |
| `deliverable/api/db.py` | PostgreSQL connections |
| `deliverable/api/student_data.py` | Student evidence queries, due-date lookup and single-result transaction |
| `deliverable/api/admin_data.py` | Academic clocks, admin queries and demo batch transaction |
| `deliverable/api/prediction_inputs.py` | Shared demographic, evidence and request conversion |
| `deliverable/api/prediction_store.py` | Shared prediction upsert using a caller-owned cursor |
| `deliverable/api/scenario_data.py` | Hypothetical evidence overlay in memory |
| `deliverable/api/predictor.py` | Frozen feature engineering, model inference and result interpretation |
| `deliverable/api/schemas.py` | Request and response validation |

Actual student predictions load evidence, invoke the model, and save the result.
Demo predictions retain one transaction for the entire batch. The shared upsert
does not open connections or commit. Scenario predictions load real evidence,
apply a hypothetical overlay, and invoke the same model without saving results
or modifying academic records.

Install the runtime dependencies with
`python -m pip install -r deliverable/requirements.txt`.
The existing deployment command remains:

```sh
cd deliverable/api
uvicorn main:app --host 0.0.0.0 --port "$PORT"
```

The environment variables remain `DATABASE_URL`, `ADMIN_API_KEY`, and the
deployment `PORT`. `/health` checks model liveness; `/ready` additionally performs
the existing minimal database check. The database schema is managed outside this
repository; this repository contains no migrations.

Install pytest and httpx alongside the runtime dependencies to run tests from the
repository root:

```sh
PYTHONPATH=deliverable/api python -m pytest -q deliverable/tests
```

PowerShell equivalent:

```powershell
$env:PYTHONPATH = 'deliverable/api'
python -m pytest -q deliverable/tests
```

Tests include the real model, complete API and prediction snapshots, demographic
fallbacks, SQL and transaction traces, and scenario isolation. Database tests use
recording connections and require no production credentials. See
[`deliverable/tests/fixtures/README.md`](deliverable/tests/fixtures/README.md)
for baseline provenance and exact comparison details.

For the additional refactor audit against the original Git revision, run:

```sh
python deliverable/tests/verify_refactor_equivalence.py
```

That audit requires the original commit in local Git history and compares 120
requests and a batch, all predictor function syntax trees (excluding annotations
and docstrings), and SQL literals. It is intentionally separate from the normal
test suite because later intentional behavior changes may supersede that baseline.
