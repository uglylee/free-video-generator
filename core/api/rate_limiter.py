"""core.api.rate_limiter — Agnes API 全局限速器（令牌桶算法）

所有 Agnes API 调用（Chat / Image / Video，含轮询）共享同一个令牌桶，
确保总调用频率不超过 Agnes API 的 20 次/分钟限制。

用法::

    from core.api.rate_limiter import get_rate_limiter

    # 在发起 HTTP 请求前获取令牌（同步，可能阻塞）
    limiter = get_rate_limiter()
    limiter.acquire()
    resp = requests.post(url, ...)

    # 异步版本（内部用 to_thread 包装）
    await limiter.acquire_async()

环境变量:
    AGNES_RATE_LIMIT: 每分钟最大调用次数，默认 20
"""

import asyncio
import logging
import os
import threading
import time

logger = logging.getLogger(__name__)

# Agnes API 所有接口共享的每分钟调用上限
_AGNES_RATE_LIMIT = int(os.environ.get("AGNES_RATE_LIMIT", "20"))
# 预留 20% 余量：实际允许 80% 的配额，即 16 次/分钟（3.75 秒/次）
_SAFETY_FACTOR = 0.8
_EFFECTIVE_RATE = _AGNES_RATE_LIMIT * _SAFETY_FACTOR  # 16 次/分钟


class AgnesRateLimiter:
    """令牌桶限速器（线程安全）。

    在多线程 / asyncio.to_thread / 纯同步场景下均可安全使用。
    当令牌不足时，``acquire()`` 会阻塞当前线程直到令牌可用。

    Attributes:
        max_tokens: 桶容量（突发上限）。
        refill_rate: 每秒补充的令牌数。
    """

    def __init__(self, rate_per_minute: float = _EFFECTIVE_RATE,
                 max_burst: int = 4):
        """初始化限速器。

        Args:
            rate_per_minute: 每分钟允许的调用次数。
            max_burst: 令牌桶最大容量（允许短时突发）。
        """
        self.max_tokens = min(max_burst, rate_per_minute)
        self.refill_rate = rate_per_minute / 60.0  # tokens per second
        self.tokens = float(self.max_tokens)
        self.last_refill = time.monotonic()
        self._lock = threading.Lock()
        self._total_waits = 0
        self._total_wait_seconds = 0.0

    def acquire(self) -> None:
        """阻塞式获取一个令牌。

        如果桶中有令牌，立即消耗并返回。
        否则计算等待时间并 ``time.sleep()`` 直到令牌可用。
        """
        with self._lock:
            now = time.monotonic()
            elapsed = now - self.last_refill
            self.tokens = min(
                self.max_tokens,
                self.tokens + elapsed * self.refill_rate,
            )
            self.last_refill = now

            if self.tokens >= 1.0:
                self.tokens -= 1.0
                return

            # 需要等待的时间
            wait_time = (1.0 - self.tokens) / self.refill_rate
            self.tokens = 0.0
            # 更新 refill 时间基准，防止 sleep 期间令牌被其他线程"偷走"
            self.last_refill = now + wait_time

        # sleep 在锁外执行，避免阻塞其他线程的 refill 计算
        if wait_time > 0.05:
            self._total_waits += 1
            self._total_wait_seconds += wait_time
            logger.info(
                f"[RateLimiter] 限速等待 {wait_time:.1f}s "
                f"(累计等待 {self._total_waits} 次, "
                f"{self._total_wait_seconds:.0f}s)"
            )
            time.sleep(wait_time)

    async def acquire_async(self) -> None:
        """异步获取令牌（内部使用 ``asyncio.to_thread``）。"""
        await asyncio.to_thread(self.acquire)

    @property
    def stats(self) -> dict:
        """返回限速器统计信息。"""
        return {
            "total_waits": self._total_waits,
            "total_wait_seconds": round(self._total_wait_seconds, 1),
            "effective_rate_per_min": round(_EFFECTIVE_RATE, 1),
            "max_burst": self.max_tokens,
        }


# ═══════════════════════════════════════════════════
# 全局单例
# ═══════════════════════════════════════════════════

_instance: AgnesRateLimiter | None = None
_instance_lock = threading.Lock()


def get_rate_limiter() -> AgnesRateLimiter:
    """获取全局速率限制器实例（线程安全单例）。"""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = AgnesRateLimiter()
                logger.info(
                    f"[RateLimiter] 初始化: {_EFFECTIVE_RATE:.0f} 次/分钟 "
                    f"(原始限制 {_AGNES_RATE_LIMIT}, 安全系数 {_SAFETY_FACTOR}), "
                    f"突发上限 {_instance.max_tokens}"
                )
    return _instance


def reset_rate_limiter() -> None:
    """重置全局限速器（仅用于测试）。"""
    global _instance
    with _instance_lock:
        _instance = None
