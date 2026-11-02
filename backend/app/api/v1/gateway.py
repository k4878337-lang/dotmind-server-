import time
import asyncio
from datetime import datetime, timezone
from typing import List, Optional
import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from app.config import settings
from app.core.dependencies import get_current_user
from app.models.user import User
from app.schemas.gateway import (
    ModelInfo,
    DiscoverModelsRequest,
    DiscoverModelsResponse,
    TestConnectionRequest,
    TestConnectionResponse,
    GatewayStatusResponse
)

router = APIRouter(prefix="/gateway", tags=["AI Provider Gateway"])

FALLBACK_CHAT_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-1.5-flash",
    "gemini-1.5-pro",
]

def sanitize_error(message: str, key_to_redact: Optional[str] = None) -> str:
    """Ensure no API keys or sensitive auth tokens leak in error messages."""
    if not message:
        return ""
    if key_to_redact and key_to_redact in message:
        message = message.replace(key_to_redact, "[REDACTED_API_KEY]")
    return message

@router.get("/status", response_model=GatewayStatusResponse)
async def get_gateway_status(
    current_user: User = Depends(get_current_user)
):
    """Returns gateway configuration options and availability."""
    return GatewayStatusResponse(
        supported_providers=["gemini"],
        available_models=FALLBACK_CHAT_MODELS,
        server_managed_available=bool(settings.GEMINI_API_KEY),
        default_provider=settings.DEFAULTLLM_PROVIDER if hasattr(settings, "DEFAULTLLM_PROVIDER") else settings.DEFAULT_LLM_PROVIDER,
        default_model=settings.GEMINI_MODEL
    )

@router.post("/models", response_model=DiscoverModelsResponse)
async def discover_models(
    req: DiscoverModelsRequest,
    current_user: User = Depends(get_current_user)
):
    """
    Live Gemini Model Discovery.
    Calls official Google Generative Language API (GET https://generativelanguage.googleapis.com/v1beta/models)
    using the provided personal key or configured server key.
    Filters models by supportedGenerationMethods for text chat vs specialized models.
    """
    provider = req.provider.lower()
    if provider != "gemini":
        return DiscoverModelsResponse(
            status="error",
            provider=req.provider,
            models=[],
            chat_models=[],
            total_count=0,
            message=f"Model discovery is not supported for provider '{req.provider}'.",
            fetched_at=datetime.now(timezone.utc).isoformat()
        )

    # Precedence: user personal key > server key
    key_to_use = (req.api_key or "").strip()
    if not key_to_use:
        key_to_use = (settings.GEMINI_API_KEY or "").strip()

    if not key_to_use:
        return DiscoverModelsResponse(
            status="error",
            provider="gemini",
            models=[],
            chat_models=[],
            total_count=0,
            message="No API key provided and no server-managed key is configured. Please enter your Gemini API key.",
            fetched_at=datetime.now(timezone.utc).isoformat()
        )

    headers = {
        "x-goog-api-key": key_to_use,
        "Accept": "application/json"
    }

    discovered_models: List[ModelInfo] = []
    page_token: Optional[str] = None
    max_pages = 5

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            for _ in range(max_pages):
                url = "https://generativelanguage.googleapis.com/v1beta/models?pageSize=100"
                if page_token:
                    url += f"&pageToken={page_token}"

                resp = await client.get(url, headers=headers)

                if resp.status_code == 200:
                    data = resp.json()
                    raw_models = data.get("models", [])
                    for m in raw_models:
                        raw_name = m.get("name", "")
                        model_id = raw_name.removeprefix("models/")
                        methods = m.get("supportedGenerationMethods", [])
                        is_chat = "generateContent" in methods
                        category = "chat" if is_chat else "specialized"

                        discovered_models.append(
                            ModelInfo(
                                id=model_id,
                                name=raw_name,
                                display_name=m.get("displayName") or model_id,
                                description=m.get("description"),
                                supported_generation_methods=methods,
                                input_token_limit=m.get("inputTokenLimit"),
                                output_token_limit=m.get("outputTokenLimit"),
                                category=category
                            )
                        )

                    page_token = data.get("nextPageToken")
                    if not page_token:
                        break
                elif resp.status_code in [400, 401]:
                    return DiscoverModelsResponse(
                        status="error",
                        provider="gemini",
                        models=[],
                        chat_models=[],
                        total_count=0,
                        message="Invalid API key. Please verify your Gemini API key in Google AI Studio (aistudio.google.com).",
                        fetched_at=datetime.now(timezone.utc).isoformat()
                    )
                elif resp.status_code == 403:
                    return DiscoverModelsResponse(
                        status="error",
                        provider="gemini",
                        models=[],
                        chat_models=[],
                        total_count=0,
                        message="Permission denied. Your API key does not have permission to list models.",
                        fetched_at=datetime.now(timezone.utc).isoformat()
                    )
                elif resp.status_code == 429:
                    return DiscoverModelsResponse(
                        status="error",
                        provider="gemini",
                        models=[],
                        chat_models=[],
                        total_count=0,
                        message="Quota or rate limit exceeded on your Gemini API key.",
                        fetched_at=datetime.now(timezone.utc).isoformat()
                    )
                else:
                    err_msg = sanitize_error(resp.text[:200], key_to_use)
                    return DiscoverModelsResponse(
                        status="error",
                        provider="gemini",
                        models=[],
                        chat_models=[],
                        total_count=0,
                        message=f"Google API returned HTTP {resp.status_code}: {err_msg}",
                        fetched_at=datetime.now(timezone.utc).isoformat()
                    )

        # Filter chat-ready models (those supporting generateContent)
        chat_models = [m for m in discovered_models if m.category == "chat"]

        return DiscoverModelsResponse(
            status="success",
            provider="gemini",
            models=discovered_models,
            chat_models=chat_models,
            total_count=len(discovered_models),
            message=f"Discovered {len(chat_models)} chat models ({len(discovered_models)} total) from live Gemini API.",
            fetched_at=datetime.now(timezone.utc).isoformat()
        )

    except httpx.TimeoutException:
        return DiscoverModelsResponse(
            status="error",
            provider="gemini",
            models=[],
            chat_models=[],
            total_count=0,
            message="Connection timed out while discovering models from Google Gemini API (20s limit). Check your internet connection.",
            fetched_at=datetime.now(timezone.utc).isoformat()
        )
    except Exception as e:
        err_str = sanitize_error(str(e), key_to_use)
        return DiscoverModelsResponse(
            status="error",
            provider="gemini",
            models=[],
            chat_models=[],
            total_count=0,
            message=f"Network error during model discovery: {err_str}",
            fetched_at=datetime.now(timezone.utc).isoformat()
        )

@router.post("/test-connection", response_model=TestConnectionResponse)
async def test_provider_connection(
    req: TestConnectionRequest,
    current_user: User = Depends(get_current_user)
):
    """Tests connectivity to the chosen AI provider with either personal or server key."""
    provider = req.provider.lower()
    if provider != "gemini":
        return TestConnectionResponse(
            status="error",
            provider=req.provider,
            model=req.model or "unknown",
            message=f"Provider '{req.provider}' is not yet supported. Currently supported: gemini",
            error_code="UNSUPPORTED_PROVIDER",
            server_managed_available=bool(settings.GEMINI_API_KEY)
        )

    # Determine key to test: user-provided personal key takes precedence, else server key
    key_to_test = (req.api_key or "").strip()
    is_personal = bool(key_to_test)
    if not key_to_test:
        key_to_test = (settings.GEMINI_API_KEY or "").strip()

    if not key_to_test:
        return TestConnectionResponse(
            status="error",
            provider="gemini",
            model=req.model or settings.GEMINI_MODEL,
            message="No API key provided and no server-managed key is configured. Please enter your personal Gemini API key.",
            error_code="MISSING_API_KEY",
            server_managed_available=False
        )

    # Normalize model identifier (strip 'models/' prefix to avoid models/models/ bug)
    raw_model = (req.model or settings.GEMINI_MODEL).strip()
    clean_model = raw_model.removeprefix("models/")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{clean_model}:generateContent"
    headers = {
        "x-goog-api-key": key_to_test,
        "Content-Type": "application/json"
    }
    payload = {
        "contents": [
            {"role": "user", "parts": [{"text": "ping"}]}
        ],
        "generationConfig": {
            "maxOutputTokens": 2,
            "temperature": 0.0
        }
    }

    start_time = time.perf_counter()
    max_test_attempts = 2  # 1 initial + 1 retry for transient errors
    last_resp = None

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            for attempt in range(1, max_test_attempts + 1):
                resp = await client.post(url, headers=headers, json=payload)
                last_resp = resp
                elapsed_ms = int((time.perf_counter() - start_time) * 1000)

                if resp.status_code == 200:
                    key_type = "Personal" if is_personal else "Server-managed"
                    return TestConnectionResponse(
                        status="connected",
                        provider="gemini",
                        model=clean_model,
                        message=f"Successfully connected to Google Gemini ({clean_model}) using {key_type} key.",
                        server_managed_available=bool(settings.GEMINI_API_KEY),
                        latency_ms=elapsed_ms
                    )
                elif resp.status_code == 401:
                    return TestConnectionResponse(
                        status="error",
                        provider="gemini",
                        model=clean_model,
                        message="Invalid or expired API Key. Please verify your Gemini API key in Google AI Studio (aistudio.google.com).",
                        error_code="INVALID_API_KEY",
                        server_managed_available=bool(settings.GEMINI_API_KEY),
                        latency_ms=elapsed_ms
                    )
                elif resp.status_code == 400:
                    error_body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
                    err_detail = error_body.get("error", {}).get("message", resp.text[:200])
                    clean_err = sanitize_error(err_detail, key_to_test)
                    lower_err = clean_err.lower()

                    if "api key" in lower_err or "apikey" in lower_err or "api_key_invalid" in lower_err:
                        err_code = "INVALID_API_KEY"
                        err_msg = "Invalid API Key. Please verify your Gemini API key in Google AI Studio (aistudio.google.com)."
                    elif "not supported" in lower_err or "generatecontent" in lower_err:
                        err_code = "UNSUPPORTED_MODEL"
                        err_msg = f"Model '{clean_model}' is not supported for generateContent. Please select an active chat model."
                    else:
                        err_code = "INVALID_REQUEST"
                        err_msg = f"Invalid request configuration for model '{clean_model}': {clean_err}"

                    return TestConnectionResponse(
                        status="error",
                        provider="gemini",
                        model=clean_model,
                        message=err_msg,
                        error_code=err_code,
                        server_managed_available=bool(settings.GEMINI_API_KEY),
                        latency_ms=elapsed_ms
                    )
                elif resp.status_code == 403:
                    return TestConnectionResponse(
                        status="error",
                        provider="gemini",
                        model=clean_model,
                        message=f"Permission denied. Your API key does not have access to model '{clean_model}'.",
                        error_code="PERMISSION_DENIED",
                        server_managed_available=bool(settings.GEMINI_API_KEY),
                        latency_ms=elapsed_ms
                    )
                elif resp.status_code == 404:
                    return TestConnectionResponse(
                        status="error",
                        provider="gemini",
                        model=clean_model,
                        message=f"Model '{clean_model}' not found on Gemini API. Please click 'Refresh Models' and select an active model.",
                        error_code="MODEL_NOT_FOUND",
                        server_managed_available=bool(settings.GEMINI_API_KEY),
                        latency_ms=elapsed_ms
                    )
                elif resp.status_code == 429:
                    if attempt < max_test_attempts:
                        await asyncio.sleep(1.0)
                        continue
                    return TestConnectionResponse(
                        status="error",
                        provider="gemini",
                        model=clean_model,
                        message="Rate limit or quota exceeded for this API key in Google AI Studio.",
                        error_code="QUOTA_EXCEEDED",
                        server_managed_available=bool(settings.GEMINI_API_KEY),
                        latency_ms=elapsed_ms
                    )
                elif resp.status_code in [500, 502, 503, 504]:
                    if attempt < max_test_attempts:
                        await asyncio.sleep(1.0)
                        continue
                    msg = "Google Gemini server encountered a temporary internal error (HTTP 500). Please retry in a few moments or switch to a different model." if resp.status_code == 500 else f"Google Gemini service unavailable (HTTP {resp.status_code})."
                    return TestConnectionResponse(
                        status="error",
                        provider="gemini",
                        model=clean_model,
                        message=msg,
                        error_code="UPSTREAM_500" if resp.status_code == 500 else "UPSTREAM_5XX",
                        server_managed_available=bool(settings.GEMINI_API_KEY),
                        latency_ms=elapsed_ms
                    )
                else:
                    error_body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
                    err_detail = error_body.get("error", {}).get("message", resp.text[:200])
                    clean_err = sanitize_error(err_detail, key_to_test)

                    return TestConnectionResponse(
                        status="error",
                        provider="gemini",
                        model=clean_model,
                        message=f"Gemini API error (HTTP {resp.status_code}): {clean_err}",
                        error_code=f"HTTP_{resp.status_code}",
                        server_managed_available=bool(settings.GEMINI_API_KEY),
                        latency_ms=elapsed_ms
                    )
    except httpx.TimeoutException:
        return TestConnectionResponse(
            status="error",
            provider="gemini",
            model=clean_model,
            message="Connection timed out while reaching Google Gemini API (15s limit). Please check your internet connection.",
            error_code="TIMEOUT",
            server_managed_available=bool(settings.GEMINI_API_KEY)
        )
    except Exception as e:
        err_msg = sanitize_error(str(e), key_to_test)
        return TestConnectionResponse(
            status="error",
            provider="gemini",
            model=clean_model,
            message=f"Network error during connection test: {err_msg}",
            error_code="NETWORK_ERROR",
            server_managed_available=bool(settings.GEMINI_API_KEY)
        )
    except Exception as e:
        err_msg = sanitize_error(str(e), key_to_test)
        return TestConnectionResponse(
            status="error",
            provider="gemini",
            model=clean_model,
            message=f"Network error: {err_msg}",
            error_code="NETWORK_ERROR",
            server_managed_available=bool(settings.GEMINI_API_KEY)
        )
