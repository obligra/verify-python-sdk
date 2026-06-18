# Obligra Verify — Python SDK

> **Status: Early Preview** — APIs may change before 1.0.

Zero-dependency Python client for the Obligra Verify API. Capture, retrieve, and verify AI decision records.

## Install

```bash
pip install git+https://github.com/obligra/verify-python-sdk.git
```

## Quick Start

```python
from obligra_verify import VerifyClient

client = VerifyClient(
    api_key="obv_your_key_here",
    base_url="https://api.obligra.ai/api/v1",
)
```

> **Preview period:** Until the production domain is live, use the preview URL provided in your onboarding email.

# Create a decision record
result = client.create_record(
    workflow_id="claim-review",
    prompt="Review this claim for approval.",
    response="Claim meets standard approval criteria.",
    model={"provider": "anthropic", "modelId": "claude-sonnet-4-20250514"},
    operational_context={
        "ticketId": "CLAIM-001",
        "severity": "medium",
    },
)
print(result["decisionRecordId"])  # dr_...

# Retrieve a record
record = client.get_record(result["decisionRecordId"])

# Verify integrity
verification = client.verify_record(result["decisionRecordId"])
print(verification["verificationState"])  # "verified"

# Search records
results = client.search_records(workflow_id="claim-review", limit=10)
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `VERIFY_API_KEY` | Verify API key (fallback if not passed to constructor) |
| `VERIFY_BASE_URL` | Verify API base URL (fallback if not passed to constructor). Use `https://api.obligra.ai/api/v1` for production. |

## Auth Model

The SDK supports two authentication flows:

| Method | Auth | Use Case |
|--------|------|----------|
| `create_record()` | API key (`X-Verify-Api-Key`) | Customer capture flow — primary SDK path |
| `get_record()` | Cognito session (console) | Admin/tooling — not available via API key |
| `verify_record()` | Cognito session (console) | Admin/tooling — not available via API key |
| `search_records()` | Cognito session (console) | Admin/tooling — not available via API key |

For normal integration, use `create_record()`. The returned `decisionRecordId` can be used to retrieve and verify records through the Verify Console.

## API

### VerifyClient(api_key, base_url, timeout=15, max_retries=2)

Constructor. Both `api_key` and `base_url` are required (via argument or env var).

### client.create_record(workflow_id, *, prompt, response, model, operational_context, retrieval_key, metadata, idempotency_key)

Create a decision record. Returns dict with `decisionRecordId`, `status`.

### client.get_record(record_id)

Retrieve a record by ID. Returns dict with `record` containing full detail.

### client.verify_record(record_id)

Verify record integrity. Returns dict with `verificationState`, `ledger`.

### client.search_records(*, workflow_id, environment_id, limit, cursor)

Search records with optional filters. Returns dict with `records`, `count`, `hasMore`, `nextCursor`.

## Field Contract

**Supported fields:**
- `prompt` — input to the AI model
- `response` — output from the AI model
- `model` — `{"provider": "...", "modelId": "..."}`
- `workflow_id` — workflow identifier (required)
- `operational_context` — additional context dict
- `retrieval_key` — search key(s)
- `metadata` — arbitrary metadata
- `idempotency_key` — deduplication key

**Rejected fields** (raises `UNSUPPORTED_FIELD` error):
- `output`, `result`, `completion`, `answer`, `generation`

## Error Handling

```python
from obligra_verify import VerifyClient, VerifyError

try:
    client.create_record("my-workflow", prompt="...")
except VerifyError as e:
    print(e.code)         # "UNSUPPORTED_FIELD", "MISSING_API_KEY", etc.
    print(e.status_code)  # HTTP status if applicable
```

## Retry Logic

- Retries on 5xx and network errors (up to `max_retries`, default 2)
- Exponential backoff: 0.5s, 1s, 2s...
- Never retries 4xx (client errors)

## Requirements

- Python >= 3.9
- Zero runtime dependencies (uses `urllib.request` from stdlib)

## Run Tests

```bash
pip install pytest
pytest
```

## License

Apache License 2.0
