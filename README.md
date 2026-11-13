# Obligra Verify Python SDK

Early preview. This is an explicit, server-side capture client, not automatic model interception or a file uploader. The optional customer-managed proxy is a separate integration path.

## Install

```bash
pip install git+https://github.com/obligra/verify-python-sdk.git
```

Requires Python 3.9 or newer, with no runtime dependencies.

## First synthetic record

Create a capture key for your Test workspace and environment in the Verify Console. Keep it in your backend secret store, never browser code or a recording. The key needs `records:write`. The authenticated key determines workspace and environment; the payload cannot select them.

Set `VERIFY_API_KEY` securely in your backend environment, then run:

```python
from obligra_verify import VerifyClient

client = VerifyClient(base_url="https://api.obligra.ai")
receipt = client.create_record(
    "synthetic-first-record",
    operational_context={"ticketId": "DEMO-001"},
    prompt="Synthetic example: classify this demo ticket.",
    response="Synthetic recommendation: routine review.",
    model={"provider": "synthetic", "modelId": "demo-v1"},
)
print(receipt["decisionRecordId"])
```

Your application calls `create_record()` at the point it chooses to capture a record. The SDK sends that submitted context over HTTPS using `X-Verify-Api-Key` to `/decision-records`. It does not invoke a model. Use the returned ID in the Console, in the same workspace and environment, to retrieve the record and check integrity. A successful capture response is not itself an integrity-verification result.

Use the API origin, not `/api/v1`. `VERIFY_BASE_URL` is the environment fallback if `base_url` is omitted. Confirm the intended environment before using a real key. No live end-to-end result is claimed by the local tests.

## Capture contract

- `workflow_id`: required nonblank string, maximum 128 UTF-16 units.
- `model`: required `provider` (maximum 64) and `modelId` (maximum 128) strings; limits count UTF-16 units to match the API. Label synthetic examples honestly.
- `operational_context`: short lookup references, up to 20 string values, maximum 128 UTF-16 units per value and 64 per key. Defaults to an empty object. Legacy reserved names `output`, `result`, `completion`, `answer` and `generation` are rejected here; use the top-level `prompt` or `response` arguments for AI text.
- `prompt` and `response`: optional strings, retained without truncation in `aiAssistedContext`, not lookup fields.
- `ai_assisted_context`: optional string-to-string dictionary. Conflicting prompt/response values are rejected, not overwritten.
- Entire serialized payload: maximum 256 KiB. Oversized input is rejected, never silently shortened.

The earlier `retrieval_key`, `metadata` and `idempotency_key` arguments remain recognized but now raise `UNSUPPORTED_FIELD`: the current capture validator does not retain these top-level fields. Put short retrieval values in `operational_context`. Do not rely on server-side deduplication from an idempotency argument.

`get_record()`, `verify_record()` and `search_records()` raise `CONSOLE_AUTH_REQUIRED`. Those operations require Console authentication; this API-key client does not implement Cognito sessions. Earlier mock tests did not prove API-key access to those operations.

## Errors and retries

```python
from obligra_verify import VerifyError

try:
    receipt = client.create_record(
        "synthetic-example",
        operational_context={"ticketId": "DEMO-002"},
        model={"provider": "synthetic", "modelId": "demo-v1"},
    )
except VerifyError as error:
    print(error.code, error.status_code)
```

Capture POSTs are not automatically retried, including after network failures or server errors. A timeout or malformed success response can leave the capture outcome unknown: check the Console before manually resubmitting to avoid duplicates. A response without a nonempty `decisionRecordId` is rejected; the SDK does not invent a receipt.

Constructor options: `api_key`, `base_url`, `timeout=15`, `max_retries=2`. `max_retries` is retained for compatibility but does not enable capture retries. Use a finite positive socket timeout; it is not a total request deadline. Responses are limited to 1 MiB. Redirects are refused to protect credentials. HTTPS origins are required, except HTTP loopback for local tests.

## Verification

```bash
pip install pytest
PYTHONPATH=src pytest
```

Tests use synthetic fixtures and local transport only. They do not establish live deployment, account entitlement, or end-to-end Console retrieval.

## License

Apache License 2.0
