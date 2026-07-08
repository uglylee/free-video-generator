"""core.api.agnes_chat — Agnes Chat API 封装（从 core/screenwriter.py 提取）

P5: 健壮 JSON 解析（strip_code_fence + 正则提取 + 降级重试）
P11: chat/chat_multimodal 统一重试（5xx/超时/连接错 3 次指数退避，4xx 不重试）
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

from core.api.rate_limiter import get_rate_limiter

logger = logging.getLogger(__name__)

BASE_URL = "https://apihub.agnes-ai.com/v1"

# 重试配置
_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 15  # 秒，指数退避基数

# 正则：匹配首个 {…} 块（支持嵌套大括号）
_JSON_BLOCK_RE = re.compile(r"\{[\s\S]*\}")


def strip_code_fence(text: str) -> str:
    """去除 LLM 响应中的代码围栏标记。

    处理常见变体：```json ... ```、``` ... ```、前后有多余空白/换行。

    Args:
        text: LLM 原始响应文本。

    Returns:
        去除围栏后的文本。
    """
    text = text.strip()
    # 去除首行 ``` 或 ```json 等
    if text.startswith("```"):
        first_newline = text.index("\n") if "\n" in text else len(text)
        text = text[first_newline + 1:]
    # 去除尾部 ```
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


class AgnesChatAPI:
    """Agnes LLM Chat API 封装（text + multimodal）。"""

    def __init__(self, api_key: str, model: str = "agnes-2.0-flash"):
        self.api_key = api_key
        self.model = model
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def _image_to_b64_uri(self, path: str) -> str:
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
        mime = mimetypes.guess_type(path)[0] or "image/png"
        return f"data:{mime};base64,{b64}"

    @staticmethod
    def _should_retry(resp: requests.Response) -> bool:
        """判断 HTTP 响应是否应重试。

        重试条件：
        - 5xx 服务端错误
        - 429 限速
        - 404 偶发路由问题（Agnes API 有时会出现瞬时 404，实际服务正常）
        """
        return resp.status_code >= 500 or resp.status_code in (429, 404)

    def _request_with_retry(self, payload: dict, timeout: int = 120) -> dict:
        """带重试的 API 请求。

        对 5xx/429/超时/连接错误进行最多 3 次指数退避重试。
        4xx 错误（非 429）直接抛出不重试。
        每次请求前通过全局限速器控制调用频率。

        Args:
            payload: 请求 JSON body。
            timeout: 请求超时秒数。

        Returns:
            解析后的响应 JSON dict。

        Raises:
            requests.HTTPError: 4xx 客户端错误或重试耗尽。
        """
        last_exc = None
        for attempt in range(_MAX_RETRIES):
            try:
                get_rate_limiter().acquire()
                resp = requests.post(
                    f"{BASE_URL}/chat/completions",
                    headers=self.headers,
                    json=payload,
                    timeout=timeout,
                )
                if self._should_retry(resp) and attempt < _MAX_RETRIES - 1:
                    delay = _RETRY_BASE_DELAY * (attempt + 1)
                    logger.warning(
                        f"[AgnesChat] Server error {resp.status_code}, "
                        f"retry {attempt + 1}/{_MAX_RETRIES} in {delay}s..."
                    )
                    time.sleep(delay)
                    continue
                resp.raise_for_status()
                return resp.json()
            except (requests.ConnectionError, requests.Timeout) as e:
                last_exc = e
                if attempt < _MAX_RETRIES - 1:
                    delay = _RETRY_BASE_DELAY * (attempt + 1)
                    logger.warning(
                        f"[AgnesChat] {type(e).__name__}, "
                        f"retry {attempt + 1}/{_MAX_RETRIES} in {delay}s..."
                    )
                    time.sleep(delay)
                    continue
                raise
        # 重试耗尽
        if last_exc:
            raise last_exc
        resp.raise_for_status()  # type: ignore[possibly-undefined]
        return resp.json()  # type: ignore[possibly-undefined]

    def chat(self, system_prompt: str, user_prompt: str, max_tokens: int = 4096) -> str:
        """纯文本 Chat 调用（含重试）。"""
        logger.info(f"[AgnesChat] Calling chat ({self.model}), prompt: {len(user_prompt)} chars...")
        data = self._request_with_retry(
            {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.7,
                "max_tokens": max_tokens,
            },
            timeout=120,
        )
        return data["choices"][0]["message"]["content"]

    def chat_json(self, system_prompt: str, user_prompt: str, max_tokens: int = 4096) -> dict:
        """Chat 调用并解析 JSON 响应（健壮版）。

        处理流程：
        1. 调用 chat 获取文本
        2. strip_code_fence 去除围栏
        3. 尝试直接 json.loads
        4. 失败则用正则提取首个 {…} 块
        5. 仍失败则重试一次 chat 调用
        6. 最终失败抛出 ValueError

        Args:
            system_prompt: System 提示词。
            user_prompt: User 提示词。
            max_tokens: 最大生成 token 数。

        Returns:
            解析后的 JSON dict。

        Raises:
            ValueError: JSON 解析最终失败。
        """
        for retry in range(2):
            content = self.chat(system_prompt, user_prompt, max_tokens=max_tokens)
            # Step 1: 去围栏
            cleaned = strip_code_fence(content)
            # Step 2: 直接解析
            try:
                return json.loads(cleaned)
            except (json.JSONDecodeError, ValueError):
                pass
            # Step 3: 正则提取首个 {…} 块
            match = _JSON_BLOCK_RE.search(cleaned)
            if match:
                try:
                    return json.loads(match.group())
                except (json.JSONDecodeError, ValueError):
                    pass
            # Step 4: 首轮失败则重试一次 chat 调用
            if retry == 0:
                logger.warning("[AgnesChat] JSON parse failed, retrying chat call...")
                continue
            # 最终失败
            preview = content[:200]
            raise ValueError(
                f"[AgnesChat] Failed to parse JSON after 2 attempts. "
                f"Response preview: {preview}..."
            )
        # 不应到达此处，但保险起见
        raise ValueError("[AgnesChat] Unexpected flow in chat_json")

    def chat_multimodal(
        self,
        system_prompt: str,
        text_prompt: str,
        image_paths: List[str],
        max_tokens: int = 4096,
    ) -> str:
        """多模态 Chat 调用（文本 + 图片，含重试）。"""
        messages = [{"role": "system", "content": system_prompt}]

        user_content = [{"type": "text", "text": text_prompt}]
        for img_path in image_paths:
            if img_path.startswith(("http://", "https://")):
                user_content.append({
                    "type": "image_url",
                    "image_url": {"url": img_path},
                })
            elif os.path.exists(img_path):
                b64_uri = self._image_to_b64_uri(img_path)
                user_content.append({
                    "type": "image_url",
                    "image_url": {"url": b64_uri},
                })
        messages.append({"role": "user", "content": user_content})

        logger.info(
            f"[AgnesChat] Calling multimodal ({self.model}), "
            f"{len(image_paths)} image(s), prompt: {len(text_prompt)} chars..."
        )
        data = self._request_with_retry(
            {
                "model": self.model,
                "messages": messages,
                "temperature": 0.7,
                "max_tokens": max_tokens,
            },
            timeout=300,
        )
        return data["choices"][0]["message"]["content"]
