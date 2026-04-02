# traderd Phase 1

Phase 1 implements the control plane and safety skeleton from the approved architecture spec:

- config loading from `config/service.yaml`
- SQLite operational state in WAL mode
- append-only chained audit log in JSON Lines format
- runtime state machine with hard transition guards
- persistent halt state
- loopback-only operator API on `127.0.0.1`

No broker connection code and no order submission code are included in this phase.

## Requirements

- Python 3.11+
- `pip`

## Install

```bash
python -m venv .venv
. .venv/Scripts/activate
pip install -r requirements.txt
```

Environment-backed secret overrides are supported for any `secrets` entry that uses an `env` placeholder. The default sample config does not require one, so the service boots from a fresh directory without extra environment setup.

If you want to exercise that override path, temporarily change a `secrets` entry in [config/service.yaml](/C:/Users/gaber/projects/0dte-trader/config/service.yaml) to:

```yaml
secrets:
  sample_env_override:
    env: TRADERD_SAMPLE_SECRET
```

Then set the environment variable:

```bash
$env:TRADERD_SAMPLE_SECRET="phase1-local-secret"
```

## Run

From the repository root:

```bash
python -m platform.app --config config/service.yaml
```

The service will create:

- [var/state/control_plane.db](/C:/Users/gaber/projects/0dte-trader/var/state/control_plane.db)
- [var/audit](/C:/Users/gaber/projects/0dte-trader/var/audit)

## Verify

Check current runtime state:

```bash
curl http://127.0.0.1:8080/status
```

Set a halt:

```bash
curl -X POST http://127.0.0.1:8080/halt ^
  -H "Content-Type: application/json" ^
  -d "{\"issued_by\":\"operator-1\",\"reason_code\":\"MANUAL\",\"reason_text\":\"manual stop\"}"
```

Confirm the service is halted:

```bash
curl http://127.0.0.1:8080/status
```

Fetch recent audit entries and copy the latest `reconciliation.confirmed` token from the payload:

```bash
curl "http://127.0.0.1:8080/audit?limit=20"
```

Clear the halt with that token:

```bash
curl -X POST http://127.0.0.1:8080/clear-halt ^
  -H "Content-Type: application/json" ^
  -d "{\"issued_by\":\"operator-1\",\"reason_text\":\"reconciliation clean\",\"reconciliation_token\":\"PASTE_TOKEN_HERE\"}"
```

Restart the process after setting a halt to verify that persistent halt state is read on boot and the service lands in `HALTED` until it is explicitly cleared.

## Tests

```bash
pytest tests/unit
```

The unit suite covers:

- valid and invalid state transitions
- halt set and clear behavior
- audit log chain tamper detection
- config validation failure
