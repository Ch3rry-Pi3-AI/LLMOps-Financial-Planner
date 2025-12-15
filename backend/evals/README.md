# Local Evals (Golden Portfolios)

This folder contains a small, deterministic “golden portfolio” evaluation harness.

It intentionally avoids AWS resources and focuses on agent helper functions that can be validated locally.

## What it does (simple)

1. Loads a few small example portfolios from `backend/evals/fixtures/*.json`
2. Runs local checks:
   - **Charter eval**: builds a Charter summary string from the portfolio and checks basic invariants
   - **Retirement eval**: runs the deterministic retirement math (value, allocation, Monte Carlo sanity bounds)
   - **Tagger eval**: checks allocation validators and prompt-injection sanitization
   - **Planner eval**: checks guardrails and that mocked downstream invocations work (`MOCK_LAMBDAS=true`)
3. Prints `ok` per portfolio when checks pass; exits non-zero on failure

This is meant to catch regressions like “a refactor broke portfolio aggregation” or “guardrails stopped working”.

## What it is not

- Not a narrative-quality judge: it does **not** call Bedrock/OpenAI or grade prose.
- Not full-stack: it does **not** hit AWS (Aurora, SQS, Lambdas, App Runner).
- It’s a fast “did we break core math/shape/guardrails?” harness you can run all the time.

## Run

From `backend/`:

- `uv run evals/run_local.py`

This will run:
- `backend/charter/eval_local.py`
- `backend/retirement/eval_local.py`
- `backend/tagger/eval_local.py`
- `backend/planner/eval_local.py`

Notes:
- The runner removes `VIRTUAL_ENV` when spawning per-agent eval scripts so `uv` can select each agent's own environment.

## How to read the output

You’ll see blocks like:

- `== charter ==` — which eval is running
- `portfolio_simple: ok (...)` — that fixture passed
- `PASSED (3/3)` — all fixtures passed for that eval
- `FAILED: planner` — at least one eval failed; the command exits non-zero

Some evals print simple scores:

- Charter: `ok (score 7/7)`
  - Structural score: checks that key headings exist in the generated Charter summary text.
- Retirement: `ok (scenario_score 2/2)`
  - Scenario score: checks a basic monotonic expectation on success rates: `easy >= base >= stress`.

You may also see logs like `Potential prompt injection detected...`.
Those are expected for the injection fixture and indicate guardrails are firing.

## Add a new case

Add a new JSON file under `backend/evals/fixtures/` with:
- `id`
- `portfolio` (accounts/positions/instruments)
- `expected.total_value`

If you want to test prompt-injection guardrails:
- Add `expected.expects_sanitization_marker: true`
- Optionally add `expected.forbidden_substrings: [...]` for phrases that must not appear in Charter output

### Fixture schema (practical)

Each fixture is roughly:

- `id`: string (used in output)
- `description`: string (optional)
- `portfolio.accounts[]`:
  - `name`, `type`, `cash_balance`
  - `positions[]` with `symbol`, `quantity`, `instrument`
  - `instrument.current_price` and (optionally) allocation maps like `allocation_asset_class`
- `expected.total_value`: number (cash + sum(quantity * current_price))

## Scenarios

The retirement eval runs multiple built-in scenarios per portfolio (base/stress/easy) and checks that success rates remain sane.

If you want to override scenarios for a fixture, add a `scenarios` array to the fixture JSON with:
- `id`
- `years_until_retirement`
- `target_annual_income`

If `scenarios` is not provided, the retirement eval uses its default trio. The random seed is reset per scenario so comparisons are stable.

## What each eval checks

### Charter (`backend/charter/eval_local.py`)
- Portfolio total math matches `expected.total_value`
- Summary contains key headings (structural invariants)
- For injection fixtures:
  - `"[INVALID INPUT DETECTED]"` appears when expected
  - `expected.forbidden_substrings` are not present

### Retirement (`backend/retirement/eval_local.py`)
- `calculate_portfolio_value(...)` matches `expected.total_value`
- `calculate_asset_allocation(...)` returns a non-zero allocation with sane bounds
- Monte Carlo returns `success_rate` in `[0, 100]` across scenarios
- Scenario monotonic check produces `scenario_score`

### Tagger (`backend/tagger/eval_local.py`)
- `sanitize_user_input(...)` flags injection-like strings
- Pydantic validators reject allocation breakdowns that don’t sum to ~100

### Planner (`backend/planner/eval_local.py`)
- `sanitize_user_input(...)` flags injection-like strings
- `truncate_response(...)` truncates and includes the truncation marker
- `invoke_agent_with_retry(...)` returns a mocked success result when `MOCK_LAMBDAS=true`

## CI

GitHub Actions runs these evals on PRs and pushes to `main`/`master` via `.github/workflows/local-evals.yml`.

## Next steps

- Add more fixtures covering edge cases (missing prices, missing allocations, extreme cash balances).
- Add an optional “LLM judge” layer to score report quality (separately from these deterministic checks).
- Add a “full-stack nightly” job that runs the real pipeline (Aurora + SQS + Lambdas) on a small subset of cases.
