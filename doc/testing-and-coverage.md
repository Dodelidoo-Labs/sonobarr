# Automated Testing and Coverage

This project includes an automated pytest suite covering core services, web flows, socket handlers, and edge-case helper branches.

## Prerequisites

Install dependencies in the required environment:

```bash
/Users/bedas/Developer/Python/global_venv/bin/pip install -r requirements.txt
/Users/bedas/Developer/Python/global_venv/bin/pip install pytest pytest-cov
```

## Run Tests

```bash
PYTHONPATH=src /Users/bedas/Developer/Python/global_venv/bin/python -m pytest
```

## Generate Coverage Reports

```bash
PYTHONPATH=src /Users/bedas/Developer/Python/global_venv/bin/python -m pytest \
  --cov=src/sonobarr_app \
  --cov-report=term-missing \
  --cov-report=xml
```

This command writes:

- `coverage.xml` for SonarQube ingestion
- `.coverage` for local coverage tooling

## Coverage Target

- The active target is 100% line coverage for `src/sonobarr_app`.
- Keep branch-focused regression tests when adding new helpers or error handling paths so the target remains stable.

## Notes for SonarQube

- Keep using the generated `coverage.xml` as the coverage report input for scanner runs.
- Re-run the coverage command after code changes to ensure SonarQube receives current metrics.
