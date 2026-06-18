"""Obligra Verify Python SDK — Client for the Verify API."""

from __future__ import annotations

import os
import time
import json
import urllib.request
import urllib.error
from typing import Any

__version__ = "0.1.0"

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
        max_retries: Max retry attempts for transient failures. Default 2.
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

        self._base_url = self._base_url.rstrip("/")

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
    ) -> dict[str, Any]:
        """Create a decision record.

        Args:
            workflow_id: Required workflow identifier.
            prompt: Input to the AI model.
            response: Output from the AI model.
            model: Dict with 'provider' and/or 'modelId'.
            operational_context: Additional context fields.
            retrieval_key: One or more retrieval keys.
            metadata: Arbitrary metadata.
            idempotency_key: Idempotency key for deduplication.

        Returns:
            API response dict with decisionRecordId, status, etc.
        """
        if not workflow_id:
            raise VerifyError("workflow_id is required.", code="MISSING_WORKFLOW_ID")

        body: dict[str, Any] = {"workflowId": workflow_id}

        if operational_context:
            self._validate_fields(operational_context)
            body["operationalContext"] = operational_context

        if prompt is not None:
            body.setdefault("operationalContext", {})["prompt"] = prompt
        if response is not None:
            body.setdefault("operationalContext", {})["response"] = response
        if model is not None:
            body["model"] = model
        if retrieval_key is not None:
            body["retrievalKey"] = retrieval_key if isinstance(retrieval_key, list) else [retrieval_key]
        if metadata is not None:
            body["metadata"] = metadata
        if idempotency_key is not None:
            body["idempotencyKey"] = idempotency_key

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
        return self._request("GET", f"/decision-records/{record_id}")

    def verify_record(self, record_id: str) -> dict[str, Any]:
        """Verify a decision record's integrity.

        Args:
            record_id: The decisionRecordId.

        Returns:
            Verification result dict.
        """
        if not record_id:
            raise VerifyError("record_id is required.", code="MISSING_RECORD_ID")
        return self._request("POST", f"/decision-records/{record_id}/verify")

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
        params: dict[str, str] = {"limit": str(min(max(limit, 1), 100))}
        if workflow_id:
            params["workflowId"] = workflow_id
        if environment_id:
            params["environmentId"] = environment_id
        if cursor:
            params["cursor"] = cursor

        query = "&".join(f"{k}={v}" for k, v in params.items())
        return self._request("GET", f"/decision-records?{query}")

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
        for attempt in range(self._max_retries + 1):
            try:
                req = urllib.request.Request(url, data=data, headers=headers, method=method)
                with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                    resp_body = resp.read().decode()
                    return json.loads(resp_body) if resp_body else {}
            except urllib.error.HTTPError as e:
                resp_body = e.read().decode() if e.fp else ""
                parsed = {}
                try:
                    parsed = json.loads(resp_body)
                except (json.JSONDecodeError, ValueError):
                    pass

                # Don't retry client errors (4xx)
                if 400 <= e.code < 500:
                    raise VerifyError(
                        parsed.get("message", f"HTTP {e.code}"),
                        status_code=e.code,
                        code=parsed.get("error", parsed.get("code")),
                    ) from e

                last_error = VerifyError(
                    parsed.get("message", f"HTTP {e.code}"),
                    status_code=e.code,
                    code=parsed.get("error"),
                )
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                last_error = VerifyError(f"Request failed: {e}", code="NETWORK_ERROR")

            # Exponential backoff before retry
            if attempt < self._max_retries:
                time.sleep(0.5 * (2 ** attempt))

        raise last_error  # type: ignore[misc]
