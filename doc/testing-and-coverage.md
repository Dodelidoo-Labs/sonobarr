# Automated Testing and Coverage

This project includes an automated pytest suite covering core services, web flows, socket handlers, and edge-case helper branches.

## Prerequisites

Install dependencies in the required environment:

```bash
path/to/python-venv/bin/pip install -r requirements.txt
path/to/python-venv/bin/pip install pytest pytest-cov
```

## Run Tests

```bash
PYTHONPATH=src path/to/python-venv -m pytest
```

## Generate Coverage Reports

```bash
PYTHONPATH=src path/to/python-venv -m pytest \
  --cov=src/sonobarr_app \
  --cov-report=term-missing \
  --cov-report=xml
```

This command writes:

- `coverage.xml` for SonarQube ingestion
- `.coverage` for local coverage tooling

## CI Build Workflow

The GitHub build workflow runs the coverage command before SonarQube analysis in the same job. This keeps SonarQube metrics aligned with the latest tests without uploading build artifacts.

## Coverage Target

- The active target is 100% line coverage.
- Keep branch-focused regression tests when adding new helpers or error handling paths so the target remains stable.

## Notes for SonarQube

- Keep using the generated `coverage.xml` as the coverage report input for scanner runs.
- Re-run the coverage command after code changes to ensure SonarQube receives current metrics.
