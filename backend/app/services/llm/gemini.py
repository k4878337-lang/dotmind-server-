import asyncio
import json
import random
import re
from typing import AsyncGenerator, List, Dict, Optional, Any
import httpx

from app.services.llm.base import BaseLLMProvider
from app.config import settings

class GeminiAPIException(Exception):
    def __init__(
        self,
        message: str,
        status_code: int = 500,
        error_code: str = "GEMINI_ERROR",
        attempts: int = 1
    ):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.error_code = error_code
        self.attempts = attempts

    def __str__(self) -> str:
        return self.message

class GeminiProvider(BaseLLMProvider):
    """
    Google Gemini Provider for DOTMIND.
    Uses the official @google/genai Node.js SDK service when available (http://127.0.0.1:8001),
    with robust direct REST API engine as an active fallback.
    Implements strict turn normalization, exponential backoff with jitter on 429 and 5xx errors,
    stream partial-completion safeguards, and sensitive key redaction.
    """
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        max_retries: int = 3,
        base_delay: float = 1.0,
        timeout: float = 60.0,
        sdk_service_url: Optional[str] = None,
        use_sdk_service: Optional[bool] = None
    ):
        self.api_key = (api_key or settings.GEMINI_API_KEY or "").strip()
        raw_model = (model or settings.GEMINI_MODEL or "gemini-2.5-flash").strip()
        self.model = raw_model.removeprefix("models/")
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.timeout = timeout
        self.sdk_service_url = sdk_service_url or getattr(settings, "GENAI_SERVICE_URL", "http://127.0.0.1:8001")
        self.use_sdk_service = use_sdk_service if use_sdk_service is not None else getattr(settings, "USE_GENAI_SERVICE", False)

    def sanitize_error(self, message: str) -> str:
        """Ensure no API keys or sensitive auth tokens leak in error messages."""
        if not message:
            return ""
        if self.api_key and self.api_key in message:
            message = message.replace(self.api_key, "[REDACTED_API_KEY]")
        message = re.sub(r"AIzaSy[A-Za-z0-9_-]{33}", "[REDACTED_API_KEY]", message)
        return message

    @staticmethod
    def _calculate_backoff(attempt: int, base_delay: float = 1.0, retry_after: Optional[str] = None) -> float:
        """Calculate exponential backoff with jitter, respecting Retry-After if present."""
        if retry_after:
            try:
                val = float(retry_after)
                if 0.1 <= val <= 30.0:
                    return val
            except ValueError:
                pass
        raw = base_delay * (2 ** (attempt - 1))
        jitter = random.uniform(0.85, 1.15)
        return min(raw * jitter, 15.0)

    @staticmethod
    def normalize_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Normalize messages into strict alternating Gemini contents:
        1. Filters empty messages without content or parts.
        2. Preserves multimodal parts (e.g. inline_data / inlineData).
        3. Merges consecutive turns with the same role into a single turn.
        4. Discards leading orphan 'model' turns so conversation strictly begins with 'user'.
        """
        raw_turns: List[Dict[str, Any]] = []
        for msg in messages:
            content = (msg.get("content") or "").strip()
            parts = msg.get("parts")
            if not content and not parts:
                continue
            role = "user" if msg.get("role") == "user" else "model"
            raw_turns.append({"role": role, "content": content, "parts": parts})

        if not raw_turns:
            return []

        while raw_turns and raw_turns[0]["role"] == "model":
            raw_turns.pop(0)

        if not raw_turns:
            return []

        merged_turns: List[Dict[str, Any]] = []
        for turn in raw_turns:
            if merged_turns and merged_turns[-1]["role"] == turn["role"]:
                prev = merged_turns[-1]
                if turn.get("content"):
                    prev_c = prev.get("content") or ""
                    prev["content"] = (prev_c + "\n\n" + turn["content"]).strip() if prev_c else turn["content"]
                if turn.get("parts"):
                    if not prev.get("parts"):
                        prev["parts"] = [{"text": prev.get("content") or ""}] if prev.get("content") else []
                    prev["parts"].extend(turn["parts"])
            else:
                merged_turns.append(turn.copy())

        contents: List[Dict[str, Any]] = []
        for turn in merged_turns:
            parts = turn.get("parts")
            if not parts:
                parts = [{"text": turn.get("content") or ""}]
            contents.append({
                "role": turn["role"],
                "parts": parts
            })

        return contents

    async def _check_sdk_service_available(self) -> bool:
        """Check if local @google/genai service is configured and running."""
        if not self.use_sdk_service:
            return False
        try:
            async with httpx.AsyncClient(timeout=0.3) as client:
                res = await client.get(f"{self.sdk_service_url}/health")
                return res.status_code == 200 and res.json().get("sdk") == "@google/genai"
        except Exception:
            return False

    async def stream_chat(
        self,
        messages: List[Dict[str, str]],
        system_instruction: Optional[str] = None
    ) -> AsyncGenerator[str, None]:
        """
        Stream chat completion with automatic exponential backoff retry for transient errors (429, 500, 503, 504).
        Routes via @google/genai SDK service when active, falling back to direct REST engine seamlessly.
        """
        if not self.api_key:
            raise GeminiAPIException(
                "Gemini API key is not configured. Please enter your personal key in AI Provider Gateway.",
                status_code=401,
                error_code="MISSING_API_KEY",
                attempts=1
            )

        contents = self.normalize_messages(messages)
        if not contents:
            raise GeminiAPIException(
                "Cannot generate response for empty message content.",
                status_code=400,
                error_code="EMPTY_REQUEST",
                attempts=1
            )

        max_attempts = self.max_retries + 1
        tokens_yielded = 0
        safety_reason: Optional[str] = None

        has_sdk_service = await self._check_sdk_service_available()

        for attempt in range(1, max_attempts + 1):
            try:
                if has_sdk_service:
                    # Stream via official @google/genai SDK service
                    sdk_payload = {
                        "apiKey": self.api_key,
                        "model": self.model,
                        "contents": contents,
                        "systemInstruction": system_instruction.strip() if system_instruction else None,
                        "generationConfig": {
                            "temperature": 0.4,
                            "maxOutputTokens": 8192
                        }
                    }

                    async with httpx.AsyncClient(timeout=self.timeout) as client:
                        async with client.stream("POST", f"{self.sdk_service_url}/stream", json=sdk_payload) as response:
                            if response.status_code == 200:
                                async for line in response.aiter_lines():
                                    if line.startswith("data: "):
                                        raw_data = line[6:].strip()
                                        if raw_data == "[DONE]":
                                            break
                                        if not raw_data:
                                            continue
                                        try:
                                            chunk = json.loads(raw_data)
                                            text = chunk.get("text")
                                            if not text and "candidates" in chunk:
                                                parts = chunk["candidates"][0].get("content", {}).get("parts", [])
                                                text = "".join(p.get("text", "") for p in parts if "text" in p and not p.get("thought"))
                                            if text:
                                                tokens_yielded += 1
                                                yield text
                                        except Exception:
                                            continue

                                if tokens_yielded == 0:
                                    raise GeminiAPIException(
                                        "Gemini model returned an empty response. Please try rephrasing your request.",
                                        status_code=200,
                                        error_code="EMPTY_RESPONSE",
                                        attempts=attempt
                                    )
                                return

                            # If SDK service returned an error status
                            err_body = await response.aread()
                            self._handle_http_error(response.status_code, err_body.decode('utf-8', errors='ignore'), attempt)

                # Fallback / Direct REST API Engine
                payload: Dict[str, Any] = {
                    "contents": contents,
                    "generationConfig": {
                        "temperature": 0.4,
                        "maxOutputTokens": 8192,
                    }
                }

                if system_instruction and system_instruction.strip():
                    payload["systemInstruction"] = {
                        "parts": [{"text": system_instruction.strip()}]
                    }

                url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:streamGenerateContent?alt=sse"
                headers = {
                    "x-goog-api-key": self.api_key,
                    "Content-Type": "application/json"
                }

                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    async with client.stream("POST", url, headers=headers, json=payload) as response:
                        if response.status_code == 200:
                            async for line in response.aiter_lines():
                                if line.startswith("data: "):
                                    raw_data = line[6:].strip()
                                    if not raw_data:
                                        continue
                                    try:
                                        chunk = json.loads(raw_data)
                                        candidates = chunk.get("candidates", [])
                                        if candidates:
                                            cand = candidates[0]
                                            fr = cand.get("finishReason")
                                            if fr and fr in ["SAFETY", "BLOCKLIST", "PROHIBITED_CONTENT", "RECITATION"]:
                                                safety_reason = fr
                                            parts = cand.get("content", {}).get("parts", [])
                                            for part in parts:
                                                if part.get("thought"):
                                                    continue
                                                text = part.get("text")
                                                if text:
                                                    tokens_yielded += 1
                                                    yield text
                                    except Exception:
                                        continue

                            if tokens_yielded == 0:
                                if safety_reason:
                                    raise GeminiAPIException(
                                        f"Response was filtered by Gemini safety guidelines ({safety_reason}).",
                                        status_code=200,
                                        error_code="SAFETY_BLOCK",
                                        attempts=attempt
                                    )
                                else:
                                    raise GeminiAPIException(
                                        "Gemini model returned an empty response. Please try rephrasing your request.",
                                        status_code=200,
                                        error_code="EMPTY_RESPONSE",
                                        attempts=attempt
                                    )
                            return

                        err_body = await response.aread()
                        retry_after_hdr = response.headers.get("Retry-After")
                        self._handle_http_error(response.status_code, err_body.decode('utf-8', errors='ignore'), attempt, retry_after_hdr)

            except GeminiAPIException as g_exc:
                # If error is transient and attempts remain, sleep and retry
                if g_exc.error_code in ["UPSTREAM_500", "SERVICE_UNAVAILABLE", "QUOTA_EXCEEDED"] and attempt < max_attempts:
                    backoff_delay = self._calculate_backoff(attempt, self.base_delay)
                    await asyncio.sleep(backoff_delay)
                    continue
                raise

            except (httpx.TimeoutException, httpx.NetworkError, httpx.ConnectError) as exc:
                if tokens_yielded > 0:
                    raise GeminiAPIException(
                        "Connection dropped while streaming response from Gemini. Stream interrupted.",
                        status_code=502,
                        error_code="STREAM_INTERRUPTED",
                        attempts=attempt
                    )

                if attempt < max_attempts:
                    backoff_delay = self._calculate_backoff(attempt, self.base_delay)
                    await asyncio.sleep(backoff_delay)
                    continue
                else:
                    if isinstance(exc, httpx.TimeoutException):
                        raise GeminiAPIException(
                            "Connection timed out while waiting for Gemini AI response (60s limit). Please check your internet connection.",
                            status_code=504,
                            error_code="TIMEOUT",
                            attempts=attempt
                        )
                    else:
                        clean_err = self.sanitize_error(str(exc))
                        raise GeminiAPIException(
                            f"Network error communicating with Gemini API: {clean_err}",
                            status_code=502,
                            error_code="NETWORK_ERROR",
                            attempts=attempt
                        )

    def _handle_http_error(self, status_code: int, err_text_raw: str, attempt: int, retry_after: Optional[str] = None):
        """Translates upstream HTTP errors into structured, safe exceptions."""
        err_text = self.sanitize_error(err_text_raw)

        if status_code in [400, 401]:
            raise GeminiAPIException(
                "Invalid API key. Please verify your Gemini API key in Google AI Studio (aistudio.google.com).",
                status_code=status_code,
                error_code="INVALID_API_KEY",
                attempts=attempt
            )
        elif status_code == 403:
            raise GeminiAPIException(
                f"Permission denied for model '{self.model}'. Your API key does not have access to this model.",
                status_code=403,
                error_code="PERMISSION_DENIED",
                attempts=attempt
            )
        elif status_code == 404:
            raise GeminiAPIException(
                f"Model '{self.model}' not found on Gemini API. Please click 'Discover Models' in AI Gateway and select an active model.",
                status_code=404,
                error_code="MODEL_NOT_FOUND",
                attempts=attempt
            )
        elif status_code == 429:
            raise GeminiAPIException(
                "Rate limit or quota exceeded in Google AI Studio for your Gemini API key.",
                status_code=429,
                error_code="QUOTA_EXCEEDED",
                attempts=attempt
            )
        elif status_code == 500:
            raise GeminiAPIException(
                "Google Gemini server encountered a temporary internal error (HTTP 500). All retry attempts were exhausted. Please wait a few moments or switch models in AI Gateway.",
                status_code=500,
                error_code="UPSTREAM_500",
                attempts=attempt
            )
        elif status_code in [502, 503, 504]:
            raise GeminiAPIException(
                f"Google Gemini service is temporarily unavailable (HTTP {status_code}). All retry attempts were exhausted.",
                status_code=status_code,
                error_code="SERVICE_UNAVAILABLE",
                attempts=attempt
            )
        else:
            raise GeminiAPIException(
                f"Gemini API returned HTTP {status_code}: {err_text[:200]}",
                status_code=status_code,
                error_code=f"HTTP_{status_code}",
                attempts=attempt
            )

    async def generate_content(
        self,
        prompt: str,
        system_instruction: Optional[str] = None
    ) -> str:
        """Non-streaming generation helper with the same retry & resilience engine."""
        tokens: List[str] = []
        async for chunk in self.stream_chat(
            messages=[{"role": "user", "content": prompt}],
            system_instruction=system_instruction
        ):
            tokens.append(chunk)
        return "".join(tokens)
