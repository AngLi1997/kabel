# Repository Guidelines

## Project Structure & Module Organization

Kabel is split into two independent workspaces:

- `kabel-back/` contains the Python 3.11 FastAPI service. Code in `kabel-back/kabel/` is organized into domain models, application services, adapters, and common infrastructure. Alembic revisions are under `kabel/alembic_kabel/versions/`; tests mirror the source layout in `kabel/tests/`.
- `kabel-front/` is a pnpm monorepo. `apps/frontend/` is the main UI, `apps/website/` is the component showcase, and reusable annotation libraries live in `packages/`. Shared diagrams and branding assets are in `images/`.

Keep changes within the relevant workspace; avoid coupling reusable packages to an app.

## Build, Test, and Development Commands

Run commands from the indicated workspace:

```bash
cd kabel-back && uv sync --group test
uv run kabel --host 0.0.0.0 --port 8002 --media-host http://localhost:8002
uv run pytest kabel/tests -v
uv run black kabel && uv run flake8 kabel

cd kabel-front && pnpm install
pnpm dev                 # build packages and start the UI on port 3004
pnpm build               # build reusable packages
pnpm build:frontend      # create the production frontend bundle
pnpm lint:frontend       # lint and fix the main application
pnpm lint:packages       # lint and fix shared packages
```

Copy `kabel-back/.env.example` to `.env` before backend development. Apply migrations with `uv run alembic -c kabel/alembic_kabel/alembic.ini upgrade head`.

## Coding Style & Naming Conventions

Frontend files use UTF-8, LF endings, two-space indentation, single quotes, and a 120-column Prettier limit. Use PascalCase for React components and camelCase for functions and variables. Run ESLint, Prettier, and Stylelint before committing.

Backend code follows Black formatting and Flake8 checks. Use four-space indentation, snake_case for modules/functions, and PascalCase for classes. Keep route handlers thin; place business logic in application services and database access in persistence adapters.

## Testing Guidelines

Name Python tests `test_*.py` and place them under the corresponding layer in `kabel-back/kabel/tests/`. Run the full pytest suite for backend changes; use `--cov=kabel` when checking coverage. Frontend Jest tests exist only in selected packages; for example, run `pnpm --filter @kabel/formatter test`. Add regression tests for bug fixes.

## Commit & Pull Request Guidelines

Use Conventional Commits, matching repository history: `feat: add export filter`, `fix: handle expired token`, or `chore: update dependencies`. Keep commits scoped and independently buildable.

Pull requests should explain the problem and solution, list verification commands, and link related issues. Include screenshots or recordings for UI changes and call out migrations, environment changes, or API compatibility impacts.
