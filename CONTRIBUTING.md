# Contributing to brainbox-backend

These are the same rules as the `brainbox-mobile` repo.

## Branches

| Branch | Purpose |
|---|---|
| `main` | Released code only. Merged from `develop` by the team lead. |
| `develop` | Integration branch. Every feature PR targets `develop`. |
| `feature/<module>` | Long-lived branch for one module, e.g. `feature/quizzes`, `feature/ai-notes` |
| `feature/<module>/BRN-xx-name` | One Jira task, e.g. `feature/quizzes/BRN-42-submit-responses` |

```bash
git checkout develop && git pull
git checkout -b feature/quizzes/BRN-42-submit-responses
```

Never push directly to `main` or `develop`.

## Commits: Conventional Commits

```
<type>(<scope>): <short summary in the imperative>

feat(quizzes): submit responses and grade MCQs
fix(auth): return 401 for expired Firebase tokens
chore(ci): cache pip downloads
docs(rag): explain how to add a source document
test(evaluation): cover keyword matching with synonyms
refactor(content): move library queries to repository
```

Types: `feat`, `fix`, `docs`, `test`, `refactor`, `chore`, `perf`, `ci`. The scope is the module or folder name.
Put the Jira key in the body or the PR title (`BRN-42`).

## Pull requests

- PRs target `develop` and need **one reviewer** approval (CODEOWNERS assigns one automatically).
- CI (`backend-ci`) must be green: ruff, format, tests, `alembic upgrade head` + `alembic check`, Docker builds.
- Keep PRs small. One Jira task per PR is ideal.
- Fill in the PR template checklist.

### PR checklist (short version)

- [ ] `ruff check .`, `ruff format --check .` and `pytest` pass locally
- [ ] Layering rule: router → service → repository; other modules only through their **service**
- [ ] New endpoint has a tag, summary and response model, and shows up in `/docs`
- [ ] Errors use `AppError` → `{"error": {"code", "message"}}`
- [ ] DB change has a reviewed Alembic migration
- [ ] AI change: new prompt version file, schema-validated output, works with the fakes
- [ ] No secrets committed

## Definition of Done

A task is **done** when:

1. **Tests pass.** New code has tests, `pytest` is green locally and in CI, and nothing is skipped without a reason.
2. **The endpoint is visible in `/docs`.** It has the right tag, a summary, request/response models, and the right role check (admin routes under `/api/v1/admin`).
3. **The prompt is versioned if AI is involved.** The template lives in `ai_service/prompts/<feature>/<name>.vN.j2`, the output is validated with a Pydantic schema, it runs with `USE_FAKE_AI=true`, and grounded features use the RAG retriever.
4. The module `README.md` is updated (endpoints, tables).
5. The PR is reviewed by one teammate and merged into `develop`.

## Code style

- Simple, commented, beginner-readable code. Prefer clear names over clever tricks.
- Async everywhere for I/O (`async def`, `await session.execute(...)`).
- Type hints on public functions. `mypy` runs in CI (non-blocking for now).
- Leave `# TODO(<owner>): ...` for work that is planned but not done.
