"""Obligra Verify Python SDK — Client for the Verify API."""

from __future__ import annotations

import os
import time
import json
import urllib.request
import urllib.error
import urllib.parse
import copy
from typing import Any

__version__ = "0.1.0"

def _utf16_length(value: str) -> int:
    """Match JavaScript validator string.length (UTF-16 code units)."""
    return len(value.encode("utf-16-le", errors="surrogatepass")) // 2


UNSUPPORTED_FIELDS = frozenset({"output", "result", "completion", "answer", "generation"})

VALID_CONTEXT_FIELDS = frozenset({
    "prompt", "response", "model", "workflow_id", "retrieval_key",
    "operational_context", "metadata", "idempotency_key",
})


class VerifyError(Exception):
    """Base error for Verify SDK operations."""

    def __init__(self, message: str, status_code: int | None = None, code: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code


class VerifyClient:
    """Client for the Obligra Verify API.

    Args:
        api_key: Verify API key. Falls back to VERIFY_API_KEY env var.
        base_url: Verify API base URL. Falls back to VERIFY_BASE_URL env var.
        timeout: Request timeout in seconds. Default 15.
        max_retries: Legacy compatibility option; capture POSTs are never retried.
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: int = 15,
        max_retries: int = 2,
    ):
        self._api_key = api_key or os.environ.get("VERIFY_API_KEY")
        self._base_url = base_url or os.environ.get("VERIFY_BASE_URL")
        self._timeout = timeout
        self._max_retries = max_retries

        if not self._api_key:
            raise VerifyError("api_key is required. Pass it directly or set VERIFY_API_KEY.", code="MISSING_API_KEY")
        if not self._base_url:
            raise VerifyError("base_url is required. Pass it directly or set VERIFY_BASE_URL.", code="MISSING_BASE_URL")

        if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not 0 < timeout < float("inf"):
            raise VerifyError("timeout must be finite and positive.", code="INVALID_TIMEOUT")
        if not isinstance(max_retries, int) or isinstance(max_retries, bool) or max_retries < 0:
            raise VerifyError("max_retries must be a non-negative integer.", code="INVALID_RETRIES")
        self._base_url = self._base_url.rstrip("/")
        parsed = urllib.parse.urlsplit(self._base_url)
        local_http = parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1", "::1")
        if (parsed.scheme != "https" and not local_http) or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path:
            raise VerifyError("Use an HTTPS API origin without /api/v1, credentials, query or fragment. HTTP is allowed only for loopback testing.", code="INVALID_BASE_URL")

    def create_record(
        self,
        workflow_id: str,
        *,
        prompt: str | None = None,
        response: str | None = None,
        model: dict[str, str] | None = None,
        operational_context: dict[str, Any] | None = None,
        retrieval_key: str | list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
        ai_assisted_context: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Create a decision record.

        Args:
            workflow_id: Required workflow identifier.
            prompt: Input to the AI model.
            response: Output from the AI model.
            model: Dict with required 'provider' and 'modelId'.
            operational_context: Additional context fields.
            retrieval_key: Unsupported; use operational_context lookup values.
            metadata: Unsupported by the current capture contract.
            idempotency_key: Unsupported; no server deduplication is claimed.
            ai_assisted_context: Lossless string-to-string AI context.

        Returns:
            API response dict with decisionRecordId, status, etc.
        """
        if not workflow_id:
            raise VerifyError("workflow_id is required.", code="MISSING_WORKFLOW_ID")

        if not isinstance(workflow_id, str) or not workflow_id.strip() or _utf16_length(workflow_id) > 128:
            raise VerifyError("workflow_id must be a non-empty string of at most 128 characters.", code="INVALID_WORKFLOW_ID")
        if any(v is not None for v in (retrieval_key, metadata, idempotency_key)):
            raise VerifyError("retrieval_key, metadata and idempotency_key are not supported by the capture contract. Put short lookup values in operational_context.", code="UNSUPPORTED_FIELD")
        context = copy.deepcopy(operational_context) if operational_context is not None else {}
        if not isinstance(context, dict) or len(context) > 20:
            raise VerifyError("operational_context must be a dict with at most 20 lookup values.", code="INVALID_OPERATIONAL_CONTEXT")
        for key, value in context.items():
            if not isinstance(key, str) or _utf16_length(key) > 64 or not isinstance(value, str) or _utf16_length(value) > 128:
                raise VerifyError("operational_context requires string keys (max 64) and string values (max 128).", code="INVALID_OPERATIONAL_CONTEXT")
        self._validate_fields(context)
        if not isinstance(model, dict) or any(not isinstance(model.get(k), str) or not model[k] or _utf16_length(model[k]) > n for k, n in (("provider", 64), ("modelId", 128))):
            raise VerifyError("model requires provider (max 64) and modelId (max 128) strings.", code="INVALID_MODEL")
        ai = copy.deepcopy(ai_assisted_context) if ai_assisted_context is not None else {}
        if not isinstance(ai, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in ai.items()):
            raise VerifyError("ai_assisted_context must contain string keys and values.", code="INVALID_AI_CONTEXT")
        for key, value in (("prompt", prompt), ("response", response)):
            if value is not None:
                if not isinstance(value, str) or (key in ai and ai[key] != value):
                    raise VerifyError("Prompt/response must be strings and must not conflict with ai_assisted_context.", code="INVALID_AI_CONTEXT")
                ai[key] = value
        body: dict[str, Any] = {"workflowId": workflow_id, "operationalContext": context, "model": {k: model[k] for k in ("provider", "modelId")}}
        if ai:
            body["aiAssistedContext"] = ai
        if len(json.dumps(body).encode("utf-8")) > 256 * 1024:
            raise VerifyError("Capture payload exceeds 256 KiB.", code="PAYLOAD_TOO_LARGE")
        return self._request("POST", "/decision-records", body=body)

    def get_record(self, record_id: str) -> dict[str, Any]:
        """Retrieve a decision record by ID.

        Args:
            record_id: The decisionRecordId.

        Returns:
            Record detail dict.
        """
        if not record_id:
            raise VerifyError("record_id is required.", code="MISSING_RECORD_ID")
        raise VerifyError("Use the Verify Console to retrieve records. This API-key client does not support Cognito sessions.", code="CONSOLE_AUTH_REQUIRED")

    def verify_record(self, record_id: str) -> dict[str, Any]:
        """Verify a decision record's integrity.

        Args:
            record_id: The decisionRecordId.

        Returns:
            Verification result dict.
        """
        if not record_id:
            raise VerifyError("record_id is required.", code="MISSING_RECORD_ID")
        raise VerifyError("Use the Verify Console to verify records. This API-key client does not support Cognito sessions.", code="CONSOLE_AUTH_REQUIRED")

    def search_records(
        self,
        *,
        workflow_id: str | None = None,
        environment_id: str | None = None,
        limit: int = 25,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """Search decision records.

        Args:
            workflow_id: Filter by workflow.
            environment_id: Filter by environment.
            limit: Max records to return (1-100).
            cursor: Pagination cursor.

        Returns:
            Dict with records list, count, hasMore, nextCursor.
        """
        raise VerifyError("Use the Verify Console to search records. This API-key client does not support Cognito sessions.", code="CONSOLE_AUTH_REQUIRED")

    def _validate_fields(self, context: dict[str, Any]) -> None:
        """Reject unsupported field names."""
        for key in context:
            if key in UNSUPPORTED_FIELDS or key.lower() in UNSUPPORTED_FIELDS:
                raise VerifyError(
                    f"UNSUPPORTED_FIELD: '{key}' is not allowed. Use 'prompt'/'response' instead.",
                    code="UNSUPPORTED_FIELD",
                )

    def _request(self, method: str, path: str, body: dict | None = None) -> dict[str, Any]:
        """Make an HTTP request with retry logic."""
        url = f"{self._base_url}{path}"
        data = json.dumps(body).encode() if body else None
        headers = {
            "Content-Type": "application/json",
            "X-Verify-Api-Key": self._api_key,
        }

        last_error: Exception | None = None
        retries = 0 if method == "POST" else self._max_retries
        for attempt in range(retries + 1):
            try:
                req = urllib.request.Request(url, data=data, headers=headers, method=method)
                opener = urllib.request.build_opener(_NoRedirect)
                with opener.open(req, timeout=self._timeout) as resp:
                    raw = resp.read(1024 * 1024 + 1)
                    if len(raw) > 1024 * 1024:
                        raise VerifyError("Response exceeds 1 MiB; capture outcome unknown.", code="INVALID_RESPONSE")
                    try:
                        resp_body = raw.decode("utf-8")
                    except UnicodeError as e:
                        raise VerifyError("Response is not UTF-8; capture outcome unknown.", code="INVALID_RESPONSE") from e
                    try:
                        result = json.loads(resp_body)
                    except (ValueError, TypeError) as e:
                        raise VerifyError("Capture response is not valid JSON; outcome is unknown. Do not automatically retry.", code="INVALID_RESPONSE") from e
                    if not isinstance(result, dict) or not isinstance(result.get("decisionRecordId"), str) or not result["decisionRecordId"].strip():
                        raise VerifyError("Capture response has no record ID; outcome is unknown. Do not automatically retry.", code="INVALID_RESPONSE")
                    return result
            except urllib.error.HTTPError as e:
                resp_body = e.read(1024 * 1024).decode("utf-8", errors="replace") if e.fp else ""
                parsed = {}
                try:
                    parsed = json.loads(resp_body)
                except (json.JSONDecodeError, ValueError):
                    pass

                if not isinstance(parsed, dict):
                    parsed = {}

                # Don't retry client errors (4xx)
                if 400 <= e.code < 500:
                    raise VerifyError(
                        parsed.get("message", f"HTTP {e.code}"),
                        status_code=e.code,
                        code=parsed.get("code", parsed.get("error")),
                    ) from e

                last_error = VerifyError(
                    parsed.get("message", f"HTTP {e.code}"),
                    status_code=e.code,
                    code=parsed.get("code", parsed.get("error")),
                )
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                last_error = VerifyError(f"Request failed: {e}", code="NETWORK_ERROR")

            # Exponential backoff before retry
            if attempt < retries:
                time.sleep(0.5 * (2 ** attempt))

        raise last_error  # type: ignore[misc]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise VerifyError("Redirect refused to protect API credentials; check the API origin.", code="REDIRECT_REFUSED")
