# Refactor characterization baseline

These snapshots were captured before any production changes from main commit
`61375e66be256640d87e2a5e8eb3e67f231b7a52` (including PRs #1 and #2).
Do not regenerate them to make a refactor pass.

- `predictions.json`: 20 deterministic requests from `characterization_cases.py`,
  all feature columns in order, dtypes, category metadata, NaNs, hexadecimal
  floating-point values, raw model probabilities, complete prediction responses,
  five batch threshold variants, and the model's SHA-256 checksum.
- `data_contract.json`: normalized SQL, bound parameters, psycopg `Json` values,
  request conversion, demo output, cursor/connection lifetime and explicit commit
  order for both persistence paths. Only SQL whitespace is normalized.
- `openapi.json`: complete public API schema, including operation IDs, validation
  constraints, defaults, response schemas, and admin header parameters.

Captured with Python 3.10.0 and the exact runtime package versions in
`deliverable/requirements.txt`. The production Python 3.11.9 configuration is
unchanged. Database tests use recording connections; they do not connect to a
live PostgreSQL database.

Run from the repository root:

```sh
PYTHONPATH=deliverable/api python -m pytest -q deliverable/tests
```

In PowerShell, set `$env:PYTHONPATH='deliverable/api'` before invoking pytest.
Install the runtime requirements plus pytest and httpx for tests. The model
contract tests deliberately require the real model dependencies.
