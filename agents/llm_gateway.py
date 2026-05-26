"""
agents/llm_gateway.py
Groq LLM gateway: rate limiting, daily token budgets, SHA256 response cache,
exponential backoff on 429, key rotation.
"""

import os
import time
import hashlib
import json
import logging
from collections import deque
from threading import Lock

try:
    from groq import Groq
except ImportError:
    Groq = None

logger = logging.getLogger(__name__)

# -- Token budgets (daily) ----------------------------------------------------
DAILY_BUDGETS = {
    "SOLOMON":         6000,
    "DANIEL":          6000,
    "AMOS":            5000,
    "RUTH":            5000,
    "JOHN":            6000,
    "AUGUSTINE":       6000,
    "MARCUS_AURELIUS": 6000,
    "HILDEGARD":       5000,
    "COUNCIL":         8000,
    "ORACLE":          8000,
}

TPM_LIMIT    = 13000   # 14 000 with safety margin
CACHE_TTL    = 3600    # 1 hour
MODEL        = "llama-3.3-70b-versatile"


class LLMGateway:
    """Singleton gateway for all Groq calls."""

    def __init__(self):
        self._lock          = Lock()
        self._minute_window = deque()          # timestamps of tokens used
        self._minute_tokens = 0                # rolling count

        self._daily_used: dict[str, int] = {k: 0 for k in DAILY_BUDGETS}
        self._day_stamp  = self._today()

        self._cache: dict[str, tuple[str, float]] = {}  # sha256 -> (response, ts)

        self._keys = self._load_keys()
        self._key_idx = 0

    # -- Key management ------------------------------------------------------

    @staticmethod
    def _load_keys() -> list[str]:
        keys = []
        key = os.getenv("GROQ_API_KEY")
        if key:
            keys.append(key)
        for i in range(2, 6):
            k = os.getenv(f"GROQ_API_KEY_{i}")
            if k:
                keys.append(k)
        return keys or ["__no_key__"]

    def _next_key(self) -> str:
        if not self._keys:
            return "__no_key__"
        k = self._keys[self._key_idx % len(self._keys)]
        self._key_idx += 1
        return k

    # -- Daily budget --------------------------------------------------------

    @staticmethod
    def _today() -> str:
        return time.strftime("%Y-%m-%d")

    def _check_day_rollover(self):
        today = self._today()
        if today != self._day_stamp:
            self._daily_used = {k: 0 for k in DAILY_BUDGETS}
            self._day_stamp  = today

    def can_spend(self, agent: str, tokens: int) -> bool:
        with self._lock:
            self._check_day_rollover()
            budget = DAILY_BUDGETS.get(agent.upper(), 0)
            used   = self._daily_used.get(agent.upper(), 0)
            return (used + tokens) <= budget

    def record_spend(self, agent: str, tokens: int):
        with self._lock:
            key = agent.upper()
            self._daily_used[key] = self._daily_used.get(key, 0) + tokens

    def budget_status(self) -> dict:
        with self._lock:
            self._check_day_rollover()
            return {
                a: {"budget": DAILY_BUDGETS[a], "used": self._daily_used.get(a, 0)}
                for a in DAILY_BUDGETS
            }

    # -- Rate limiter (rolling per-minute window) ----------------------------

    def _wait_for_tpm_capacity(self, tokens_needed: int):
        """Block until the rolling 60-second window has room."""
        while True:
            now = time.time()
            # Drop entries older than 60 s
            while self._minute_window and now - self._minute_window[0][0] > 60:
                _, t = self._minute_window.popleft()
                self._minute_tokens -= t

            if self._minute_tokens + tokens_needed <= TPM_LIMIT:
                break
            wait = 60 - (now - self._minute_window[0][0]) + 0.1
            logger.info("TPM cap reached -- sleeping %.1f s", wait)
            time.sleep(wait)

    def _record_tpm(self, tokens: int):
        self._minute_window.append((time.time(), tokens))
        self._minute_tokens += tokens

    # -- Cache ----------------------------------------------------------------

    @staticmethod
    def _cache_key(system: str, user: str, model: str, temperature: float) -> str:
        raw = json.dumps({"s": system, "u": user, "m": model, "t": temperature},
                         sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()

    def _cache_get(self, key: str) -> str | None:
        entry = self._cache.get(key)
        if entry and (time.time() - entry[1]) < CACHE_TTL:
            return entry[0]
        return None

    def _cache_set(self, key: str, value: str):
        self._cache[key] = (value, time.time())

    # -- Main call ------------------------------------------------------------

    def call(
        self,
        agent:       str,
        system:      str,
        user:        str,
        max_tokens:  int  = 1000,
        temperature: float = 0.7,
    ) -> str | None:
        """
        Route a completion through Groq with full guardrails.
        Returns the assistant text or None on failure / budget exhaustion.
        """
        if Groq is None:
            logger.error("groq package not installed")
            return None

        agent_upper = agent.upper()

        # Budget check
        if not self.can_spend(agent_upper, max_tokens):
            logger.warning("%s daily token budget exhausted", agent_upper)
            return None

        # Cache
        ck = self._cache_key(system, user, MODEL, temperature)
        cached = self._cache_get(ck)
        if cached:
            logger.debug("%s cache hit", agent_upper)
            return cached

        with self._lock:
            self._wait_for_tpm_capacity(max_tokens)

        # Exponential backoff loop
        backoff = 1
        for attempt in range(5):
            try:
                api_key = self._next_key()
                client  = Groq(api_key=api_key)
                resp = client.chat.completions.create(
                    model      = MODEL,
                    max_tokens = max_tokens,
                    temperature= temperature,
                    messages   = [
                        {"role": "system", "content": system},
                        {"role": "user",   "content": user},
                    ],
                )
                text       = resp.choices[0].message.content.strip()
                used_tokens = resp.usage.total_tokens if resp.usage else max_tokens

                with self._lock:
                    self._record_tpm(used_tokens)

                self.record_spend(agent_upper, used_tokens)
                self._cache_set(ck, text)

                logger.info("%s (%d tokens used)", agent_upper, used_tokens)
                return text

            except Exception as exc:
                err = str(exc)
                if "429" in err or "rate_limit" in err.lower():
                    wait = backoff * 2
                    logger.warning("%s 429 -- retrying in %ds (attempt %d)", agent_upper, wait, attempt + 1)
                    time.sleep(wait)
                    backoff = min(backoff * 2, 60)
                    self._key_idx += 1   # rotate to next key
                else:
                    logger.error("%s LLM error: %s", agent_upper, exc)
                    return None

        logger.error("%s exhausted all retries", agent_upper)
        return None


# Singleton
_gateway = LLMGateway()

def get_gateway() -> LLMGateway:
    return _gateway
