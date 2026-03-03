# Automated Testing and Coverage

This project now includes an automated pytest suite covering core services, web flows, and socket handlers.

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

## Notes for SonarQube

- Keep using the generated `coverage.xml` as the coverage report input for scanner runs.
- Re-run the coverage command after code changes to ensure SonarQube receives current metrics.
