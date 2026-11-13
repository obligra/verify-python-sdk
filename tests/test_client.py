"""Tests for the Obligra Verify Python SDK."""

import json
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread
from unittest.mock import patch

import pytest

MODEL = {"provider": "synthetic", "modelId": "fixture-v1"}

from obligra_verify import VerifyClient, VerifyError, __version__


# ─── Mock Server ────────────────────────────────────────────────────────────

class MockVerifyHandler(BaseHTTPRequestHandler):
    """Mock Verify API for testing."""

    def do_POST(self):
        content_len = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(content_len)) if content_len else {}

        if self.path == "/decision-records":
            self._respond(201, {
                "decisionRecordId": "dr_test_123",
                "status": "recorded",
                "verificationState": "not_verified",
                "workflowId": body.get("workflowId"),
            })
        elif "/verify" in self.path:
            self._respond(200, {
                "decisionRecordId": "dr_test_123",
                "verificationState": "verified",
                "ledger": {"hashMatches": True, "signatureValid": True},
            })
        else:
            self._respond(404, {"error": "not_found"})

    def do_GET(self):
        if "/decision-records/" in self.path and "?" not in self.path:
            self._respond(200, {
                "record": {
                    "decisionRecordId": "dr_test_123",
                    "workflowId": "test-wf",
                    "verificationState": "not_verified",
                }
            })
        elif "/decision-records" in self.path:
            self._respond(200, {
                "records": [{"decisionRecordId": "dr_test_123", "workflowId": "test-wf"}],
                "count": 1,
                "hasMore": False,
            })
        else:
            self._respond(404, {"error": "not_found"})

    def _respond(self, code, body):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())

    def log_message(self, *args):
        pass  # Suppress logs during tests


@pytest.fixture(scope="module")
def mock_server():
    server = HTTPServer(("127.0.0.1", 0), MockVerifyHandler)
    port = server.server_address[1]
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()


@pytest.fixture
def client(mock_server):
    c = VerifyClient(api_key="obv_test.secret", base_url=mock_server)
    original = c.create_record
    def create_record(*args, **kwargs):
        kwargs.setdefault("model", MODEL)
        return original(*args, **kwargs)
    c.create_record = create_record
    return c


# ─── Constructor Tests ──────────────────────────────────────────────────────

class TestConstructor:
    def test_requires_api_key(self):
        with pytest.raises(VerifyError, match="api_key is required"):
            VerifyClient(base_url="http://localhost")

    def test_requires_base_url(self):
        with pytest.raises(VerifyError, match="base_url is required"):
            VerifyClient(api_key="obv_test.secret")

    def test_reads_env_vars(self, mock_server):
        with patch.dict(os.environ, {"VERIFY_API_KEY": "obv_env.key", "VERIFY_BASE_URL": mock_server}):
            c = VerifyClient()
            assert c._api_key == "obv_env.key"

    def test_explicit_overrides_env(self, mock_server):
        with patch.dict(os.environ, {"VERIFY_API_KEY": "obv_env.key", "VERIFY_BASE_URL": "http://wrong"}):
            c = VerifyClient(api_key="obv_direct.key", base_url=mock_server)
            assert c._api_key == "obv_direct.key"


# ─── Create Record Tests ───────────────────────────────────────────────────

class TestCreateRecord:
    def test_basic_create(self, client):
        result = client.create_record("test-workflow", prompt="Hello", response="World")
        assert result["decisionRecordId"] == "dr_test_123"
        assert result["status"] == "recorded"

    def test_requires_workflow_id(self, client):
        with pytest.raises(VerifyError, match="workflow_id is required"):
            client.create_record("")

    def test_with_model(self, client):
        result = client.create_record(
            "test-wf",
            model={"provider": "anthropic", "modelId": "claude-sonnet-4-20250514"},
        )
        assert result["status"] == "recorded"

    def test_with_operational_context(self, client):
        result = client.create_record(
            "test-wf",
            operational_context={"ticketId": "T-001", "severity": "high"},
        )
        assert result["status"] == "recorded"

    def test_with_retrieval_key_string(self, client):
        with pytest.raises(VerifyError, match="not supported"):
            client.create_record("test-wf", retrieval_key="key-001")

    def test_with_retrieval_key_list(self, client):
        with pytest.raises(VerifyError, match="not supported"):
            client.create_record("test-wf", retrieval_key=["key-001", "key-002"])

    def test_with_idempotency_key(self, client):
        with pytest.raises(VerifyError, match="not supported"):
            client.create_record("test-wf", idempotency_key="idem-001")

    @pytest.mark.parametrize("field", ["output", "result", "completion", "answer", "generation"])
    def test_rejects_unsupported_fields(self, client, field):
        with pytest.raises(VerifyError, match="UNSUPPORTED_FIELD"):
            client.create_record("test-wf", operational_context={field: "value"})

    def test_accepts_valid_fields(self, client):
        result = client.create_record(
            "test-wf",
            operational_context={"ticketId": "T-001", "severity": "low"},
        )
        assert result["status"] == "recorded"


# ─── Get Record Tests ──────────────────────────────────────────────────────

class TestGetRecord:
    def test_get_record(self, client):
        with pytest.raises(VerifyError) as e:
            client.get_record("dr_test_123")
        assert e.value.code == "CONSOLE_AUTH_REQUIRED"

    def test_requires_record_id(self, client):
        with pytest.raises(VerifyError, match="record_id is required"):
            client.get_record("")


# ─── Verify Record Tests ───────────────────────────────────────────────────

class TestVerifyRecord:
    def test_verify_record(self, client):
        with pytest.raises(VerifyError) as e:
            client.verify_record("dr_test_123")
        assert e.value.code == "CONSOLE_AUTH_REQUIRED"

    def test_requires_record_id(self, client):
        with pytest.raises(VerifyError, match="record_id is required"):
            client.verify_record("")


# ─── Search Records Tests ──────────────────────────────────────────────────

class TestSearchRecords:
    def test_search_records(self, client):
        with pytest.raises(VerifyError) as e:
            client.search_records()
        assert e.value.code == "CONSOLE_AUTH_REQUIRED"

    def test_search_with_filters(self, client):
        with pytest.raises(VerifyError) as e:
            client.search_records(workflow_id="test-wf", limit=10)
        assert e.value.code == "CONSOLE_AUTH_REQUIRED"


# ─── Error Handling Tests ──────────────────────────────────────────────────

class TestErrorHandling:
    def test_network_error(self):
        client = VerifyClient(api_key="obv_test.secret", base_url="http://127.0.0.1:1", timeout=1, max_retries=0)
        with pytest.raises(VerifyError) as exc_info:
            client.create_record("test-wf", model=MODEL)
        assert exc_info.value.code == "NETWORK_ERROR"



# ─── Version Test ──────────────────────────────────────────────────────────

class TestVersion:
    def test_version_exists(self):
        assert __version__ == "0.1.0"
