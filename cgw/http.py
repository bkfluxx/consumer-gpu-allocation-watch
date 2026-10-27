"""Polite HTTP fetching with provenance metadata.

Every response is returned together with the facts needed to audit it later
(url, fetch time, status, sha256 of the body). The pipeline stores that audit
record alongside the parsed values so any number in the newsletter/API can be
traced back to the exact bytes it came from.
"""
from __future__ import annotations

import hashlib
import random
import time
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse

import requests

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
DEFAULT_HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


@dataclass
class FetchResult:
    url: str
    status: int
    text: str
    fetched_at: float
    sha256: str
    error: Optional[str] = None
    headers: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.error is None and 200 <= self.status < 300


class Fetcher:
    """Small wrapper that rate-limits, retries and hashes responses.

    Per-host politeness: some hosts (Reddit) rate-limit aggressively, so the
    interval is tracked per host rather than globally, and 429/503 responses
    back off for longer before the next attempt.
    """

    def __init__(self, min_interval: float = 1.0, timeout: float = 30.0,
                 max_attempts: int = 3, session: Optional[requests.Session] = None,
                 host_intervals: Optional[dict[str, float]] = None):
        self.min_interval = min_interval
        self.timeout = timeout
        self.max_attempts = max_attempts
        self.session = session or requests.Session()
        self.host_intervals = {"www.reddit.com": 4.0, "old.reddit.com": 4.0}
        if host_intervals:
            self.host_intervals.update(host_intervals)
        self._last_call: dict[str, float] = {}
        self.calls: list[dict] = []

    def _throttle(self, host: str) -> None:
        interval = self.host_intervals.get(host, self.min_interval)
        gap = time.time() - self._last_call.get(host, 0.0)
        if gap < interval:
            time.sleep(interval - gap)
        self._last_call[host] = time.time()

    def get(self, url: str, headers: Optional[dict] = None, params: Optional[dict] = None) -> FetchResult:
        hdrs = dict(DEFAULT_HEADERS)
        if headers:
            hdrs.update(headers)
        host = urlparse(url).netloc
        last_err = None
        for attempt in range(self.max_attempts):
            self._throttle(host)
            try:
                r = self.session.get(url, headers=hdrs, params=params,
                                     timeout=self.timeout, allow_redirects=True)
                body = r.text
                res = FetchResult(
                    url=r.url, status=r.status_code, text=body,
                    fetched_at=time.time(),
                    sha256=hashlib.sha256(body.encode("utf-8", "replace")).hexdigest(),
                    headers=dict(r.headers),
                )
                self.calls.append({"url": url, "status": r.status_code,
                                   "bytes": len(body), "fetched_at": res.fetched_at})
                if r.status_code in (429, 503) and attempt + 1 < self.max_attempts:
                    wait = float(r.headers.get("Retry-After") or 0) or (6.0 + 3 * attempt)
                    time.sleep(min(wait, 30.0))
                    continue
                return res
            except Exception as exc:  # noqa: BLE001 - recorded, not swallowed
                last_err = f"{type(exc).__name__}: {exc}"
                time.sleep(0.5 + attempt + random.random())
        self.calls.append({"url": url, "status": 0, "error": last_err,
                           "fetched_at": time.time()})
        return FetchResult(url=url, status=0, text="", fetched_at=time.time(),
                            sha256="", error=last_err)
