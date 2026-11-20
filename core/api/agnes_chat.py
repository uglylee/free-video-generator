
"""
OpenRouter-compatible replacement for core.api.agnes_chat.

Keeps the AgnesChatAPI interface so existing screenwriter modules
can continue calling chat(), chat_json(), and chat_multimodal().
Uses the OpenRouter free model router only.
"""

import base64
import json
import logging
import mimetypes
import os
import re
import time
from typing import List

import requests

logger = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
FREE_MODEL = "openrouter/free"

_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 10

_JSON_BLOCK_RE = re.compile(r"\{[\s\S]*\}")


def strip_code_fence(text: str) -> str:
    text = text.strip()

    if text.startswith("```"):
        first_newline = text.find("\n")
        text = text[first_newline + 1:] if first_newline >= 0 else ""

    if text.endswith("```"):
        text = text[:-3]

    return text.strip()


class AgnesChatAPI:
    """OpenRouter chat API with AgnesChatAPI-compatible methods."""

    def __init__(self, api_key: str = "", model: str = FREE_MODEL):
        # Use the OpenRouter key configured in the Render environment.
        self.api_key = os.getenv("OPENROUTER_API_KEY", "").strip()

        # Always use the free router. Do not fall back to a paid model.
        self.model = FREE_MODEL

        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://travel-with-niks-ai-studio.onrender.com",
            "X-Title": "Travel with Niks AI Studio",
        }

    def _check_api_key(self):
        if not self.api_key:
            raise RuntimeError(
                "OPENROUTER_API_KEY is missing. "
                "Add it to the Render environment variables."
            )

    def _image_to_b64_uri(self, path: str) -> str:
        with open(path, "rb") as image_file:
            encoded = base64.b64encode(image_file.read()).decode("utf-8")

        mime = mimetypes.guess_type(path)[0] or "image/png"
        return f"data:{mime};base64,{encoded}"

    def _request_with_retry(
        self,
        payload: dict,
        timeout: int = 120
    ) -> dict:
        """Send requests to OpenRouter with limited retries."""

        self._check_api_key()

        payload["model"] = FREE_MODEL
        last_exception = None

        for attempt in range(_MAX_RETRIES):
            try:
                logger.info(
                    "[OpenRouter] Calling free model router "
                    "(attempt %s/%s)",
                    attempt + 1,
                    _MAX_RETRIES,
                )

                response = requests.post(
                    OPENROUTER_URL,
                    headers=self.headers,
                    json=payload,
                    timeout=timeout,
                )

                if response.status_code == 429 or response.status_code >= 500:
                    if attempt < _MAX_RETRIES - 1:
                        delay = _RETRY_BASE_DELAY * (attempt + 1)

                        logger.warning(
                            "[OpenRouter] Temporary server/rate-limit error "
                            "%s. Retrying in %s seconds.",
                            response.status_code,
                            delay,
                        )

                        time.sleep(delay)
                        continue

                response.raise_for_status()
                return response.json()

            except (requests.ConnectionError, requests.Timeout) as error:
                last_exception = error

                if attempt < _MAX_RETRIES - 1:
                    delay = _RETRY_BASE_DELAY * (attempt + 1)

                    logger.warning(
                        "[OpenRouter] Connection error. "
                        "Retrying in %s seconds.",
                        delay,
                    )

                    time.sleep(delay)
                    continue

                raise

            except requests.HTTPError:
                if response.status_code == 429 or response.status_code >= 500:
                    logger.error(
                        "[OpenRouter] Request failed after retries: %s %s",
                        response.status_code,
                        response.text[:1000],
                    )
                else:
                    logger.error(
                        "[OpenRouter] HTTP error: %s %s",
                        response.status_code,
                        response.text[:1000],
                    )
                raise

        if last_exception:
            raise last_exception

        raise RuntimeError("[OpenRouter] Request failed.")

    def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 4096
    ) -> str:
        """Text-only chat."""

        logger.info(
            "[OpenRouter] Text chat request: %s characters",
            len(user_prompt),
        )

        data = self._request_with_retry(
            {
                "model": FREE_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.7,
                "max_tokens": max_tokens,
            },
            timeout=120,
        )

        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise RuntimeError(
                f"[OpenRouter] Unexpected response: {str(data)[:1000]}"
            ) from error

    def chat_json(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 4096
    ) -> dict:
        """Chat and parse a JSON response."""

        for attempt in range(2):
            content = self.chat(
                system_prompt,
                user_prompt,
                max_tokens=max_tokens,
            )

            cleaned = strip_code_fence(content)

            try:
                return json.loads(cleaned)
            except (json.JSONDecodeError, ValueError):
                pass

            match = _JSON_BLOCK_RE.search(cleaned)

            if match:
                try:
                    return json.loads(match.group())
                except (json.JSONDecodeError, ValueError):
                    pass

            if attempt == 0:
                logger.warning(
                    "[OpenRouter] JSON parsing failed. Retrying once."
                )
                continue

            raise ValueError(
                "[OpenRouter] Could not parse JSON response. "
                f"Response preview: {content[:300]}"
            )

        raise ValueError("[OpenRouter] Unexpected JSON parsing error.")

    def chat_multimodal(
        self,
        system_prompt: str,
        text_prompt: str,
        image_paths: List[str],
        max_tokens: int = 4096,
    ) -> str:
        """Chat with text and image inputs."""

        user_content = [
            {"type": "text", "text": text_prompt}
        ]

        for image_path in image_paths:
            if image_path.startswith(("http://", "https://")):
                image_url = image_path

            elif os.path.exists(image_path):
                image_url = self._image_to_b64_uri(image_path)

            else:
                logger.warning(
                    "[OpenRouter] Image not found: %s",
                    image_path,
                )
                continue

            user_content.append({
                "type": "image_url",
                "image_url": {"url": image_url},
            })

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

        logger.info(
            "[OpenRouter] Multimodal request with %s image(s).",
            len(user_content) - 1,
        )

        data = self._request_with_retry(
            {
                "model": FREE_MODEL,
                "messages": messages,
                "temperature": 0.7,
                "max_tokens": max_tokens,
            },
            timeout=300,
        )

        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise RuntimeError(
                f"[OpenRouter] Unexpected multimodal response: "
                f"{str(data)[:1000]}"
            ) from error
