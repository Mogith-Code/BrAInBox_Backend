## What does this PR do?

<!-- One or two sentences. Link the Jira issue: BRN-xx -->

Jira: BRN-

## Type

- [ ] feat
- [ ] fix
- [ ] refactor / chore
- [ ] docs / tests

## Checklist

- [ ] Branch name is `feature/<module>/BRN-xx-short-name` and targets `develop`
- [ ] Commits follow Conventional Commits (`feat(quizzes): ...`)
- [ ] `ruff check .` and `ruff format --check .` pass
- [ ] `pytest` passes, and new code has tests
- [ ] New endpoints appear in `/docs` with a tag, summary and response model
- [ ] Layering rule followed (router → service → repository; other modules only via their service)
- [ ] DB change? Migration added with `alembic revision --autogenerate`, reviewed, and `alembic check` is clean
- [ ] AI change? Prompt is a new versioned file (`*.vN.j2`), output validated with a schema, and it works with the fakes
- [ ] No secrets, `.env` or service-account JSON committed
- [ ] Module `README.md` updated (endpoints / tables)

## How to test

<!-- curl commands, /docs steps, or test names -->
