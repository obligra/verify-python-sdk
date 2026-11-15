import io
import json
import urllib.error
from unittest.mock import patch, Mock
import pytest
from obligra_verify import VerifyClient, VerifyError

MODEL = {"provider": "synthetic", "modelId": "test-v1"}

def client():
    return VerifyClient(api_key="synthetic-not-a-key", base_url="https://example.invalid")

def test_lossless_payload_and_no_mutation():
    c = client()
    original = {"ticket": "T-1"}
    ai = {"reason": "fixture"}
    with patch.object(c, "_request", return_value={"decisionRecordId":"dr_fixture"}) as request:
        c.create_record("wf", prompt="p" * 600, response="r" * 1000, model=MODEL, operational_context=original, ai_assisted_context=ai)
    body = request.call_args.kwargs["body"]
    assert body["aiAssistedContext"]["prompt"] == "p" * 600
    assert body["aiAssistedContext"]["output"] == "r" * 1000
    assert body["operationalContext"] == original == {"ticket": "T-1"}
    assert ai == {"reason": "fixture"}

def test_output_is_sent_in_console_display_field():
    response = Mock()
    response.read.return_value = b'{"decisionRecordId":"dr_fixture","status":"recorded"}'
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    output = "Fictional recommendation: caf\u00e9 / \u6771\u4eac / \U0001f9ea " + "x" * 600
    ai = {"sourceRef": "fictional-document-1"}
    with patch("urllib.request.build_opener") as factory:
        factory.return_value.open.return_value = response
        receipt = client().create_record("wf", prompt="Fictional input", response=output, model=MODEL, ai_assisted_context=ai)
        request = factory.return_value.open.call_args.args[0]
        payload = json.loads(request.data)
        assert payload["aiAssistedContext"] == {"prompt": "Fictional input", "output": output, "sourceRef": "fictional-document-1"}
        assert receipt == {"decisionRecordId": "dr_fixture", "status": "recorded"}
        factory.return_value.open.assert_called_once()
    assert ai == {"sourceRef": "fictional-document-1"}

@pytest.mark.parametrize("response,context,expected", [
    ("same", {"output": "same"}, {"output": "same"}),
    (None, {"output": "explicit"}, {"output": "explicit"}),
    ("", {}, {"output": ""}),
    ("new", {"response": "caller-owned"}, {"response": "caller-owned", "output": "new"}),
])
def test_output_mapping_preserves_explicit_context(response, context, expected):
    c = client()
    with patch.object(c, "_request", return_value={"decisionRecordId": "dr_fixture"}) as request:
        c.create_record("wf", response=response, model=MODEL, ai_assisted_context=context)
    assert request.call_args.kwargs["body"]["aiAssistedContext"] == expected

def test_output_conflict_is_rejected_before_transport():
    with patch("urllib.request.build_opener") as transport:
        with pytest.raises(VerifyError) as error:
            client().create_record("wf", response="first", model=MODEL, ai_assisted_context={"output": "second"})
        assert error.value.code == "INVALID_AI_CONTEXT"
        transport.assert_not_called()

@pytest.mark.parametrize("kwargs", [{}, {"model": MODEL, "operational_context": {1:"x"}}, {"model": {}}, {"model": MODEL, "operational_context": {"a": 42}}, {"model": MODEL, "operational_context": {"a":"x"*129}}, {"model":MODEL,"prompt":42}, {"model":MODEL,"prompt":"a","ai_assisted_context":{"prompt":"b"}}, {"model":MODEL,"prompt":"x"*262144}])
def test_invalid_capture_is_local(kwargs):
    with patch("urllib.request.build_opener") as transport:
        with pytest.raises(VerifyError): client().create_record("wf", **kwargs)
        transport.assert_not_called()

@pytest.mark.parametrize("body", [b'{}', b'[]', b'null', b'not-json', b'{"decisionRecordId":""}'])
def test_bad_receipts_are_not_success(body):
    response=Mock();response.read.return_value=body
    response.__enter__=Mock(return_value=response); response.__exit__=Mock(return_value=False)
    with patch("urllib.request.build_opener") as factory:
        factory.return_value.open.return_value=response
        with pytest.raises(VerifyError) as e: client().create_record("wf",model=MODEL)
        assert e.value.code == "INVALID_RESPONSE"
        assert factory.return_value.open.call_count == 1

@pytest.mark.parametrize("error", [urllib.error.URLError("unknown outcome"), urllib.error.HTTPError("https://example.invalid",503,"error",{},io.BytesIO(b'{}'))])
def test_no_ambiguous_post_retries(error):
    with patch("urllib.request.build_opener") as factory:
        factory.return_value.open.side_effect=error
        with pytest.raises(VerifyError): client().create_record("wf",model=MODEL)
        assert factory.return_value.open.call_count == 1

@pytest.mark.parametrize("url", ["https://example.invalid/api/v1","http://example.invalid","https://a:b@example.invalid","https://example.invalid?q=1"])
def test_unsafe_origin_rejected(url):
    with pytest.raises(VerifyError): VerifyClient(api_key="synthetic",base_url=url)

@pytest.mark.parametrize("field", ["workflow", "provider", "lookup"])
def test_utf16_contract_limits(field):
    kwargs = {"model": dict(MODEL), "operational_context": {"id":"T1"}}
    workflow = "fixture"
    if field == "workflow": workflow = "😀" * 65
    if field == "provider": kwargs["model"]["provider"] = "😀" * 33
    if field == "lookup": kwargs["operational_context"]["id"] = "😀" * 65
    with pytest.raises(VerifyError): client().create_record(workflow, **kwargs)

@pytest.mark.parametrize("body", [b'\xff', b'x' * (1024 * 1024 + 1)])
def test_invalid_utf8_and_oversized_response(body):
    response = Mock(); response.read.return_value = body
    response.__enter__ = Mock(return_value=response); response.__exit__ = Mock(return_value=False)
    with patch("urllib.request.build_opener") as factory:
        factory.return_value.open.return_value = response
        with pytest.raises(VerifyError) as error: client().create_record("wf", model=MODEL)
        assert error.value.code == "INVALID_RESPONSE"
        response.read.assert_called_once_with(1024 * 1024 + 1)

def test_redirect_handler_refuses_credentials_forwarding():
    from obligra_verify import _NoRedirect
    with pytest.raises(VerifyError) as error:
        _NoRedirect().redirect_request(None, None, 307, "redirect", {}, "https://other.invalid")
    assert error.value.code == "REDIRECT_REFUSED"

