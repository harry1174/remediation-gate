---
name: Apache Superset repository conventions
trigger: When working in the harry1174/superset repository
---

- The default branch is `master`.
- Python 3.11 or newer is required.
- Prefer the narrowest relevant test file, for example
  `pytest tests/unit_tests/path/to/test_file.py -q`.
- Run focused pre-commit checks on changed files rather than formatting the entire
  repository: `pre-commit run --files <changed files>`.
- Backend source lives under `superset/`; backend unit tests live under
  `tests/unit_tests/`.
- Preserve Apache license headers and the repository's existing typing style.
- Pull requests target `harry1174/superset`, not upstream `apache/superset`.
- The automation issues are demonstration contracts in a fork. Do not modify or
  comment on upstream Apache issues.
