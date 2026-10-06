from __future__ import annotations

import gzip
import hashlib
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.robotparser import RobotFileParser

import httpx

from .config import FetchConfig
from .urls import host_of

HTML_TYPES = ("text/html", "application/xhtml+xml", "text/plain", "application/xml", "text/xml")


@dataclass(frozen=True)
class FetchResult:
    status: int
    final_url: str
    content_type: str
    body: bytes
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and 200 <= self.status < 300 and bool(self.body)

    @property
    def is_pdf(self) -> bool:
        return "application/pdf" in self.content_type or self.final_url.lower().endswith(".pdf")

    @property
    def is_html(self) -> bool:
        return any(kind in self.content_type for kind in HTML_TYPES) or not self.content_type


@dataclass
class Fetcher:
    config: FetchConfig
    client: httpx.Client = field(init=False)
    robots: dict[str, RobotFileParser | None] = field(default_factory=dict)
    last_request: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.client = httpx.Client(
            headers={"User-Agent": self.config.user_agent, "Accept-Language": "en,mn,ru,ja,ko,zh,de,tr;q=0.8"},
            timeout=self.config.timeout_seconds,
            follow_redirects=True,
            http2=False,
        )

    def close(self) -> None:
        self.client.close()

    def allowed(self, url: str) -> bool:
        host = host_of(url)
        if host not in self.robots:
            self.robots[host] = self._load_robots(url)
        parser = self.robots[host]
        return parser.can_fetch(self.config.user_agent, url) if parser else True

    def _load_robots(self, url: str) -> RobotFileParser | None:
        robots_url = f"{httpx.URL(url).scheme}://{host_of(url)}/robots.txt"
        try:
            response = self.client.get(robots_url, timeout=10)
        except httpx.HTTPError:
            return None
        if response.status_code != 200 or len(response.content) > 500_000:
            return None
        parser = RobotFileParser()
        parser.parse(response.text.splitlines())
        return parser

    def _wait_for_host(self, url: str) -> None:
        host = host_of(url)
        elapsed = time.monotonic() - self.last_request.get(host, 0.0)
        if elapsed < self.config.per_host_delay_seconds:
            time.sleep(self.config.per_host_delay_seconds - elapsed)
        self.last_request[host] = time.monotonic()

    def fetch(self, url: str) -> FetchResult:
        if not self.allowed(url):
            return FetchResult(status=0, final_url=url, content_type="", body=b"", error="robots_disallow")
        attempts = 0
        while True:
            attempts += 1
            self._wait_for_host(url)
            try:
                return self._get(url)
            except httpx.TimeoutException:
                error = "timeout"
            except httpx.HTTPError as exc:
                error = f"http_error:{type(exc).__name__}"
            if attempts >= 3:
                return FetchResult(status=0, final_url=url, content_type="", body=b"", error=error)
            time.sleep(2.0 * attempts)

    def _get(self, url: str) -> FetchResult:
        with self.client.stream("GET", url) as response:
            content_type = response.headers.get("content-type", "").lower()
            if response.status_code >= 500:
                raise httpx.HTTPStatusError("server error", request=response.request, response=response)
            chunks = []
            size = 0
            for chunk in response.iter_bytes():
                chunks.append(chunk)
                size += len(chunk)
                if size > self.config.max_bytes:
                    return FetchResult(status=response.status_code, final_url=str(response.url), content_type=content_type, body=b"", error="too_large")
            return FetchResult(status=response.status_code, final_url=str(response.url), content_type=content_type, body=b"".join(chunks))


def content_hash(body: bytes) -> str:
    return hashlib.sha1(body).hexdigest()


def store_raw(raw_dir: Path, digest: str, body: bytes, suffix: str) -> Path:
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = raw_dir / f"{digest}{suffix}.gz"
    if not path.exists():
        path.write_bytes(gzip.compress(body))
    return path


def store_text(text_dir: Path, digest: str, text: str) -> Path:
    text_dir.mkdir(parents=True, exist_ok=True)
    path = text_dir / f"{digest}.txt"
    if not path.exists():
        path.write_text(text, encoding="utf-8")
    return path
