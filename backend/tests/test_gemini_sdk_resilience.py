import json
import pytest
import httpx
from unittest.mock import patch, AsyncMock, MagicMock
from app.services.llm.gemini import GeminiProvider, GeminiAPIException

@pytest.mark.asyncio
async def test_1_successful_gemini_response():
    """Scenario 1: Successful non-streaming generation helper."""
    provider = GeminiProvider(api_key="AIzaSyTestValidKey123", model="gemini-2.5-flash", base_delay=0.001)

    sse_data = "data: " + json.dumps({
        "candidates": [{
            "content": {"parts": [{"text": "Hello! I am DotMind."}]}
        }]
    }) + "\n\n"

    mock_resp = AsyncMock()
    mock_resp.status_code = 200
    mock_resp.aiter_lines = MagicMock(return_value=aiter_from_lines([sse_data]))

    with patch("httpx.AsyncClient.stream") as mock_stream:
        mock_stream.return_value.__aenter__.return_value = mock_resp
        result = await provider.generate_content("Hi there")
        assert result == "Hello! I am DotMind."

@pytest.mark.asyncio
async def test_2_successful_streaming_response():
    """Scenario 2: Successful streaming response with internal thought filtering."""
    provider = GeminiProvider(api_key="AIzaSyTestValidKey123", model="gemini-2.5-flash", base_delay=0.001)

    chunk1 = "data: " + json.dumps({
        "candidates": [{
            "content": {"parts": [
                {"thought": "Hidden internal thought", "text": ""},
                {"text": "First chunk. "}
            ]}
        }]
    }) + "\n\n"

    chunk2 = "data: " + json.dumps({
        "candidates": [{
            "content": {"parts": [{"text": "Second chunk."}]}
        }]
    }) + "\n\n"

    mock_resp = AsyncMock()
    mock_resp.status_code = 200
    mock_resp.aiter_lines = MagicMock(return_value=aiter_from_lines([chunk1, chunk2]))

    with patch("httpx.AsyncClient.stream") as mock_stream:
        mock_stream.return_value.__aenter__.return_value = mock_resp
        chunks = []
        async for c in provider.stream_chat([{"role": "user", "content": "Tell me something"}]):
            chunks.append(c)

        assert chunks == ["First chunk. ", "Second chunk."]
        assert "Hidden internal thought" not in "".join(chunks)

@pytest.mark.asyncio
async def test_3_invalid_api_key():
    """Scenario 3: Invalid API key fails fast with INVALID_API_KEY without retrying."""
    provider = GeminiProvider(api_key="AIzaSyBadKey", model="gemini-2.5-flash", base_delay=0.001)

    mock_resp = AsyncMock()
    mock_resp.status_code = 400
    mock_resp.aread = AsyncMock(return_value=b'{"error": {"code": 400, "message": "API key not valid."}}')

    with patch("httpx.AsyncClient.stream") as mock_stream:
        mock_stream.return_value.__aenter__.return_value = mock_resp
        with pytest.raises(GeminiAPIException) as exc_info:
            async for _ in provider.stream_chat([{"role": "user", "content": "hi"}]):
                pass

        assert exc_info.value.error_code == "INVALID_API_KEY"
        assert exc_info.value.status_code == 400
        assert exc_info.value.attempts == 1  # Did not retry

@pytest.mark.asyncio
async def test_4_unsupported_model():
    """Scenario 4: HTTP 404 Model Not Found fails fast without retrying."""
    provider = GeminiProvider(api_key="AIzaSyTestKey", model="non-existent-model-xyz", base_delay=0.001)

    mock_resp = AsyncMock()
    mock_resp.status_code = 404
    mock_resp.aread = AsyncMock(return_value=b'{"error": {"code": 404, "message": "Model not found."}}')

    with patch("httpx.AsyncClient.stream") as mock_stream:
        mock_stream.return_value.__aenter__.return_value = mock_resp
        with pytest.raises(GeminiAPIException) as exc_info:
            async for _ in provider.stream_chat([{"role": "user", "content": "hi"}]):
                pass

        assert exc_info.value.error_code == "MODEL_NOT_FOUND"
        assert exc_info.value.status_code == 404
        assert exc_info.value.attempts == 1

@pytest.mark.asyncio
async def test_5_http_429_quota():
    """Scenario 5: HTTP 429 quota exhaustion retries and returns QUOTA_EXCEEDED."""
    provider = GeminiProvider(api_key="AIzaSyTestKey", model="gemini-2.5-flash", max_retries=2, base_delay=0.001)

    mock_resp = AsyncMock()
    mock_resp.status_code = 429
    mock_resp.headers = {"Retry-After": "0.01"}
    mock_resp.aread = AsyncMock(return_value=b'{"error": {"code": 429, "message": "Resource exhausted."}}')

    with patch("httpx.AsyncClient.stream") as mock_stream:
        mock_stream.return_value.__aenter__.return_value = mock_resp
        with pytest.raises(GeminiAPIException) as exc_info:
            async for _ in provider.stream_chat([{"role": "user", "content": "hi"}]):
                pass

        assert exc_info.value.error_code == "QUOTA_EXCEEDED"
        assert exc_info.value.status_code == 429
        assert exc_info.value.attempts == 3  # 1 initial + 2 retries

@pytest.mark.asyncio
async def test_6_http_500_with_transient_retry():
    """Scenario 6: HTTP 500 on first attempt followed by HTTP 200 success on retry."""
    provider = GeminiProvider(api_key="AIzaSyTestKey", model="gemini-2.5-flash", max_retries=2, base_delay=0.001)

    resp_500 = AsyncMock()
    resp_500.status_code = 500
    resp_500.headers = {}
    resp_500.aread = AsyncMock(return_value=b'{"error": {"code": 500, "message": "Internal error encountered."}}')

    resp_200 = AsyncMock()
    resp_200.status_code = 200
    sse_data = "data: " + json.dumps({
        "candidates": [{
            "content": {"parts": [{"text": "Recovered from 500!"}]}
        }]
    }) + "\n\n"
    resp_200.aiter_lines = MagicMock(return_value=aiter_from_lines([sse_data]))

    call_count = 0
    def mock_stream_fn(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=resp_500 if call_count == 1 else resp_200)
        cm.__aexit__ = AsyncMock(return_value=None)
        return cm

    with patch("httpx.AsyncClient.stream", side_effect=mock_stream_fn):
        tokens = []
        async for t in provider.stream_chat([{"role": "user", "content": "hi"}]):
            tokens.append(t)

        assert "".join(tokens) == "Recovered from 500!"
        assert call_count == 2  # Retried and succeeded on attempt 2

@pytest.mark.asyncio
async def test_7_retry_exhaustion_500():
    """Scenario 7: Continuous HTTP 500 exhausts retries and returns clean UPSTREAM_500."""
    provider = GeminiProvider(api_key="AIzaSyTestKey", model="gemini-2.5-flash", max_retries=2, base_delay=0.001)

    mock_resp = AsyncMock()
    mock_resp.status_code = 500
    mock_resp.headers = {}
    mock_resp.aread = AsyncMock(return_value=b'{"error": {"code": 500, "message": "Internal error encountered."}}')

    with patch("httpx.AsyncClient.stream") as mock_stream:
        mock_stream.return_value.__aenter__.return_value = mock_resp
        with pytest.raises(GeminiAPIException) as exc_info:
            async for _ in provider.stream_chat([{"role": "user", "content": "hi"}]):
                pass

        assert exc_info.value.error_code == "UPSTREAM_500"
        assert exc_info.value.status_code == 500
        assert "temporary internal error" in exc_info.value.message
        assert exc_info.value.attempts == 3

@pytest.mark.asyncio
async def test_8_network_timeout():
    """Scenario 8: Network timeout retries and returns TIMEOUT."""
    provider = GeminiProvider(api_key="AIzaSyTestKey", model="gemini-2.5-flash", max_retries=1, base_delay=0.001)

    with patch("httpx.AsyncClient.stream", side_effect=httpx.TimeoutException("Timed out")):
        with pytest.raises(GeminiAPIException) as exc_info:
            async for _ in provider.stream_chat([{"role": "user", "content": "hi"}]):
                pass

        assert exc_info.value.error_code == "TIMEOUT"
        assert exc_info.value.status_code == 504
        assert exc_info.value.attempts == 2

@pytest.mark.asyncio
async def test_9_interrupted_stream():
    """Scenario 9: Mid-stream interruption raises STREAM_INTERRUPTED and does not duplicate stream."""
    provider = GeminiProvider(api_key="AIzaSyTestKey", model="gemini-2.5-flash", max_retries=2, base_delay=0.001)

    chunk = "data: " + json.dumps({
        "candidates": [{"content": {"parts": [{"text": "Partial start..."}]}}]
    }) + "\n\n"

    async def faulty_lines():
        yield chunk
        raise httpx.NetworkError("Connection reset by peer")

    mock_resp = AsyncMock()
    mock_resp.status_code = 200
    mock_resp.aiter_lines = MagicMock(return_value=faulty_lines())

    with patch("httpx.AsyncClient.stream") as mock_stream:
        mock_stream.return_value.__aenter__.return_value = mock_resp
        collected = []
        with pytest.raises(GeminiAPIException) as exc_info:
            async for t in provider.stream_chat([{"role": "user", "content": "hi"}]):
                collected.append(t)

        assert collected == ["Partial start..."]
        assert exc_info.value.error_code == "STREAM_INTERRUPTED"
        assert exc_info.value.status_code == 502

@pytest.mark.asyncio
async def test_10_empty_response():
    """Scenario 10: 200 OK with no text chunks raises EMPTY_RESPONSE."""
    provider = GeminiProvider(api_key="AIzaSyTestKey", model="gemini-2.5-flash", base_delay=0.001)

    mock_resp = AsyncMock()
    mock_resp.status_code = 200
    mock_resp.aiter_lines = MagicMock(return_value=aiter_from_lines([]))

    with patch("httpx.AsyncClient.stream") as mock_stream:
        mock_stream.return_value.__aenter__.return_value = mock_resp
        with pytest.raises(GeminiAPIException) as exc_info:
            async for _ in provider.stream_chat([{"role": "user", "content": "hi"}]):
                pass

        assert exc_info.value.error_code == "EMPTY_RESPONSE"
        assert exc_info.value.status_code == 200

def test_11_conversation_history_turn_normalization():
    """Scenario 11: Normalizes consecutive user turns, drops leading model turn, cleans whitespace."""
    messages = [
        {"role": "model", "content": "Orphan assistant greeting"},
        {"role": "user", "content": "User part 1"},
        {"role": "user", "content": "User part 2"},
        {"role": "assistant", "content": "Model reply 1"},
        {"role": "assistant", "content": "Model reply 2"},
        {"role": "user", "content": ""},  # empty to drop
        {"role": "user", "content": "Final user query"}
    ]

    normalized = GeminiProvider.normalize_messages(messages)

    # 1. Leading model turn dropped
    assert normalized[0]["role"] == "user"
    # 2. Consecutive user parts merged
    assert normalized[0]["parts"][0]["text"] == "User part 1\n\nUser part 2"
    # 3. Consecutive model parts merged
    assert normalized[1]["role"] == "model"
    assert normalized[1]["parts"][0]["text"] == "Model reply 1\n\nModel reply 2"
    # 4. Final turn is user
    assert normalized[2]["role"] == "user"
    assert normalized[2]["parts"][0]["text"] == "Final user query"
    # 5. Exactly 3 turns alternating user -> model -> user
    assert len(normalized) == 3

def test_12_no_api_key_leakage_in_logs():
    """Scenario 12: Sensitive API key and AIzaSy tokens are rigorously redacted."""
    secret_key = "AIzaSySecretTestingKey998877665544"
    provider = GeminiProvider(api_key=secret_key)

    raw_err = f"Failed to connect using key {secret_key} to https://generativelanguage.googleapis.com"
    sanitized = provider.sanitize_error(raw_err)

    assert secret_key not in sanitized
    assert "[REDACTED_API_KEY]" in sanitized

def test_13_correct_model_selection():
    """Scenario 13: Normalizes model name and defaults cleanly."""
    p1 = GeminiProvider(api_key="key", model="models/gemini-2.5-flash")
    assert p1.model == "gemini-2.5-flash"

    p2 = GeminiProvider(api_key="key", model=None)
    assert p2.model == "gemini-2.5-flash"

@pytest.mark.asyncio
async def test_14_no_duplicate_assistant_messages_after_retry():
    """Scenario 14: Simulates message retry normalization ensuring no duplicate user or assistant turns."""
    history = [
        {"role": "user", "content": "Calculate 2+2"},
        {"role": "assistant", "content": "", "status": "error"}  # failed assistant
    ]

    # Clean history as done in ChatViewModel
    trimmed = [m for m in history if not (m["role"] == "assistant" and m.get("status") == "error")]
    assert len(trimmed) == 1
    assert trimmed[0]["role"] == "user"

    normalized = GeminiProvider.normalize_messages(trimmed)
    assert len(normalized) == 1
    assert normalized[0]["parts"][0]["text"] == "Calculate 2+2"

def test_15_error_codes_mapping():
    """Scenario 15: Error codes are properly structured for Android error cards."""
    ex = GeminiAPIException("Server error", status_code=500, error_code="UPSTREAM_500")
    assert ex.error_code == "UPSTREAM_500"
    assert ex.status_code == 500

async def aiter_from_lines(lines):
    for line in lines:
        yield line
