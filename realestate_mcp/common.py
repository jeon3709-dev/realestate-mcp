"""공용 유틸리티: 키 마스킹, httpx 클라이언트 팩토리, 재시도, 로깅 필터.

원본 3개 서버에 따로 있던 sanitize_error / get_api_headers / get_http_client 를 한 곳으로
모았다. API 별 헤더·타임아웃·프록시는 원본 값을 그대로 유지한다.
"""
import asyncio
import logging
import re
import urllib.parse
from typing import Any, Dict, List, Literal, Mapping, Optional

import httpx

from . import config

logger = logging.getLogger("realestate-mcp")

ApiName = Literal["vworld", "bldrgst", "rtms"]

MASK = "***"

# key=..., KEY=..., serviceKey=... 등 쿼리 파라미터 형태의 키를 가린다(대소문자 무시).
# 원본 VWorld 는 소문자 `key=` 만 가려서 WFS 요청의 `KEY=` 가 노출될 수 있었다.
_KEY_PARAM_RE = re.compile(r"((?:service)?key=)[^&'\"\s]+", re.IGNORECASE)

# 너무 짧은 문자열 치환은 메시지를 훼손할 수 있으므로 건너뛴다.
_MIN_SECRET_LEN = 4

# 재시도 사이 대기(초). 테스트에서 0 으로 바꿀 수 있다.
RETRY_BACKOFF_SECONDS = 0.5

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# 원본 서버별 타임아웃(초)
DEFAULT_TIMEOUTS: Dict[str, float] = {
    "vworld": 15.0,
    "bldrgst": 15.0,
    "rtms": 20.0,
}


# --- Key masking ---

def _secret_forms(secret: str) -> List[str]:
    """All textual forms a key may take in URLs, logs or exception messages."""
    decoded = urllib.parse.unquote(secret)
    forms = {
        secret,
        decoded,
        urllib.parse.quote(secret, safe=""),
        urllib.parse.quote(decoded, safe=""),
        urllib.parse.quote_plus(decoded),
    }
    # httpx's own query-string encoding (what actually appears in request URLs)
    try:
        forms.add(str(httpx.QueryParams({"k": decoded}))[2:])
        forms.add(str(httpx.QueryParams({"k": secret}))[2:])
    except Exception:
        pass
    return sorted((f for f in forms if f and len(f) >= _MIN_SECRET_LEN), key=len, reverse=True)


def sanitize_error(msg: Any) -> str:
    """Mask every configured API key (raw and URL-encoded forms) in a message."""
    if not msg:
        return ""
    text = str(msg)
    text = _KEY_PARAM_RE.sub(r"\g<1>" + MASK, text)
    for secret in config.all_secret_values():
        for form in _secret_forms(secret):
            text = text.replace(form, MASK)
    return text


class SanitizingLogFilter(logging.Filter):
    """Logging filter that masks API keys in every record passing a handler."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True
        record.msg = sanitize_error(message)
        record.args = None
        return True


def configure_logging(level: int = logging.INFO) -> None:
    """basicConfig + key-masking filter on every root handler.

    httpx 는 INFO 레벨에서 요청 URL(서비스키 포함)을 로깅하므로 WARNING 으로 올린다.
    """
    logging.basicConfig(level=level, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    root = logging.getLogger()
    for handler in root.handlers:
        if not any(isinstance(f, SanitizingLogFilter) for f in handler.filters):
            handler.addFilter(SanitizingLogFilter())


# --- HTTP clients ---

def get_api_headers(api: ApiName) -> Dict[str, str]:
    """Return common HTTP headers per API (browser-like, to avoid cloud WAF blocks)."""
    if api == "vworld":
        domain = config.vworld_domain()
        return {
            "User-Agent": BROWSER_UA,
            "Referer": f"https://{domain}/" if domain != "localhost" else "http://localhost/",
            "Accept": "application/json, text/plain, */*",
        }
    if api == "bldrgst":
        return {
            "User-Agent": BROWSER_UA,
            "Accept": "application/json, text/plain, */*",
        }
    return {
        "User-Agent": BROWSER_UA,
        "Accept": "application/xml, text/xml, */*",
    }


def _proxy_url(api: ApiName) -> Optional[str]:
    if api == "vworld":
        return config.vworld_proxy_url()
    if api == "bldrgst":
        return config.bldrgst_proxy_url()
    return None  # 원본 RTMS 서버는 프록시 설정이 없다.


def make_client(api: ApiName, timeout: Optional[float] = None) -> httpx.AsyncClient:
    """Return an httpx AsyncClient with the original per-API headers/timeout/proxy."""
    kwargs: Dict[str, Any] = {
        "timeout": timeout if timeout is not None else DEFAULT_TIMEOUTS[api],
        "headers": get_api_headers(api),
    }
    proxy = _proxy_url(api)
    if proxy:
        kwargs["proxy"] = proxy
    return httpx.AsyncClient(**kwargs)


async def get_with_retry(
    client: httpx.AsyncClient,
    url: str,
    params: Optional[Mapping[str, Any]] = None,
    retries: int = 1,
) -> httpx.Response:
    """GET with at most `retries` retry on 5xx or network (transport) errors.

    4xx 및 인증 오류(공공데이터포털은 HTTP 200 + XML 로 반환)는 재시도하지 않는다.
    마지막 시도의 응답을 그대로 돌려주거나 마지막 예외를 다시 던진다.
    """
    attempt = 0
    while True:
        try:
            response = await client.get(url, params=params)
        except httpx.TransportError as e:
            if attempt < retries:
                attempt += 1
                logger.warning(f"Network error on {url}, retrying ({attempt}/{retries}): {sanitize_error(str(e))}")
                if RETRY_BACKOFF_SECONDS:
                    await asyncio.sleep(RETRY_BACKOFF_SECONDS)
                continue
            raise
        if response.status_code >= 500 and attempt < retries:
            attempt += 1
            logger.warning(f"HTTP {response.status_code} from {url}, retrying ({attempt}/{retries})")
            if RETRY_BACKOFF_SECONDS:
                await asyncio.sleep(RETRY_BACKOFF_SECONDS)
            continue
        return response
