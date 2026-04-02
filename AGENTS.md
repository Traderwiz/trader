# AGENTS.md — Systematic Trading Platform

## Project identity

This is a systematic, automated trading platform built in Python. It is a real-money system. Every decision that touches execution, safety, or architecture is treated with production-grade seriousness. The architecture spec is the authoritative reference for all design decisions. It lives at `docs/architecture-spec.md`.

## Runtime environment

- Bot box: Ubuntu 20.04, `openclaw-bot` via SSH
- Python: 3.11.15 via uv, venv at `~/trader/.venv`
- Always run tests and Python commands using `~/trader/.venv/bin/python` and `~/trader/.venv/bin/pytest`
- Never use system `python3` (3.8.10) for this project
- Working directory on the bot box: `~/trader/`
- All file operations, test runs, and verifications happen on the bot box, not the local Windows machine

## Architecture rules — non-negotiable

These rules come from the approved architecture spec and cannot be changed without explicit operator approval:

1. `traderd` is the only authoritative runtime process. No scripts bypass the safety stack.
2. `ExecutionService.submit_order_intent()` is the only path from intent to broker. No exceptions.
3. `BrokerAdapter.submit()` is private to the execution module. Strategies never receive a broker reference.
4. The `HALTED -> READY` state transition requires an explicit operator token. It never happens automatically.
5. Every state transition is written to the audit log before the state changes.
6. The audit log is append-only. No record is ever updated in place.
7. Slippage is mandatory in all backtests. There is no zero-slippage mode.
8. The backtesting engine and live runtime share one strategy codebase. No separate codepaths.
9. Strategy promotion (RESEARCH -> BACKTEST -> PAPER -> LIVE) requires explicit operator action. Never auto-promote.
10. AI does not have order authority. LLM input is advisory only and never directly triggers an order.
11. No broker imports (`ib_insync` or similar) outside the `platform/broker/` module.
12. No order submission code outside `platform/execution/`.

## Safety gate order — never reorder, never skip

Every order intent must pass these checks in this exact sequence:
1. Halt state check
2. Daily loss limit check
3. Duplicate order / idempotency check
4. Order price sanity check
5. Position reconciliation pre-trade check
6. Broker connectivity check

## Directory structure

Follow the approved spec layout exactly. Do not create modules outside these directories:

```
platform/
  models/
  broker/
  execution/
  portfolio/
  strategy/
  regime/
  data/
  backtest/
  persistence/
  operator/
config/
tests/
  unit/
  integration/
  scenario/
docs/
var/
  audit/
  state/
  data/
  reports/
```

Do not create empty placeholder directories. A directory exists only when it contains implemented code.

## Coding standards

- Python 3.11+ features are allowed and preferred
- Every module must have a docstring stating its single responsibility
- No ORM. SQLite via the standard library `sqlite3` module only
- No Redis, ZMQ, Celery, or distributed message brokers in V1
- Plain Python `dataclasses` or frozen dataclasses for domain models. No Pydantic, no SQLAlchemy
- All timestamps are UTC `datetime` objects with tzinfo. Never naive datetimes
- Dependencies must be justified. Prefer the standard library. Add to `requirements.txt` when a third-party library is genuinely needed
- Type hints on all function signatures
- No `# type: ignore` comments without an explanation

## Testing standards

- Every implemented module has corresponding tests
- Tests live in `tests/unit/` for isolated logic, `tests/integration/` for broker and persistence integration, `tests/scenario/` for crisis and promotion-gate scenarios
- Run the full suite with: `~/trader/.venv/bin/pytest tests/unit tests/scenario -v`
- Tests must pass before any phase is marked complete
- Safety gate tests must verify hard failures on invalid inputs, not just happy-path behavior
- A test that only checks that a field exists is not sufficient. Tests must assert correct values and correct error behavior

## Phase discipline

- The current phase scope is defined in the phase prompt. Do not build outside that scope.
- Do not begin the next phase without explicit operator approval
- Every phase ends with: all implementation files on the bot box, updated `requirements.txt`, full pytest output, and a completion report at `docs/phaseN-completion-report.md`
- Completion reports must list each criterion and whether it passed. Self-reporting without running the actual tests is not acceptable

## What is explicitly out of scope for V1

Do not build any of the following, even if they seem useful:
- Options trading of any kind
- Multi-broker support
- Multi-process or distributed runtime
- Automatic reconciliation trades
- Automatic strategy promotion
- LLM order authority
- Web dashboard
- General plugin system
- Redis, ZMQ, or distributed messaging

## Review protocol

When a phase is complete:
1. Run the full test suite on the bot box and capture the raw output
2. Write the completion report at `docs/phaseN-completion-report.md`
3. Stop and wait for operator review before proceeding
4. Do not self-approve. The operator reviews the pytest output and the completion report before Phase N+1 begins

## Operator

The operator is Greg. Greg is the architect and decision-maker. Codex is the implementer. Claude (Anthropic) is the reviewer. Greg relays review decisions between sessions. When in doubt about an architectural decision, stop and ask rather than assume.

## Git discipline

- Repository: git@github.com:Traderwiz/trader.git
- Default branch: master
- Every phase ends with a commit and push before the completion report is filed
- Commit message format: `Phase N: short description` with bullet list of what was built
- Never commit with failing tests
- Never commit `__pycache__/`, `.venv/`, `var/`, or `.pytest_cache/` — covered by .gitignore
- After every phase commit, push to origin before reporting completion
- Use `git status` before committing to verify no unintended files are staged


## Phase 5 Notes

- The system has been through 5 build phases.
- Paper-to-live promotion requires: 20+ paper sessions, zero reconciliation mismatches, drift within tolerance, and operator sign-off.
- Live mode requires an explicit config change and a non-empty account ID.
- Never set `mode: live` without operator approval.
