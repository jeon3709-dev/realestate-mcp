"""환경변수 로딩과 API 인증키 조회.

- 인증키는 호출 시점마다 os.environ 에서 읽는다(원본 서버들과 동일). 키가 빠진 API 가
  있어도 서버는 기동하고, 해당 도구만 에러를 반환한다.
- DATA_GO_KR_SERVICE_KEY 는 BLDRGST_API_KEY / MOLIT_SERVICE_KEY 가 비어 있을 때만
  대신 쓴다. 개별 키가 있으면 개별 키가 우선한다.
"""
import os
import urllib.parse
from typing import List, Optional

from dotenv import load_dotenv

load_dotenv()

# .env.example / 원본 저장소의 자리표시자 값은 "미설정"으로 취급한다.
PLACEHOLDER_VALUES = frozenset({
    "your_api_key_here",
    "your_service_key_here",
    "your_decoding_api_key_here",
})

SECRET_ENV_VARS = (
    "VWORLD_API_KEY",
    "BLDRGST_API_KEY",
    "MOLIT_SERVICE_KEY",
    "DATA_GO_KR_SERVICE_KEY",
)

DEFAULT_PORT = 8080
DEFAULT_RTMS_CONCURRENCY = 5


def _env(name: str) -> Optional[str]:
    """Return a stripped env value, or None when empty / a placeholder."""
    val = os.environ.get(name)
    if val is None:
        return None
    val = val.strip()
    if not val or val in PLACEHOLDER_VALUES:
        return None
    return val


# --- Raw key lookups (no decoding) ---

def vworld_key_raw() -> Optional[str]:
    return _env("VWORLD_API_KEY")


def bldrgst_key_raw() -> Optional[str]:
    return _env("BLDRGST_API_KEY") or _env("DATA_GO_KR_SERVICE_KEY")


def molit_key_raw() -> Optional[str]:
    return _env("MOLIT_SERVICE_KEY") or _env("DATA_GO_KR_SERVICE_KEY")


def all_secret_values() -> List[str]:
    """Every configured secret value (used by sanitize_error)."""
    values = []
    for name in SECRET_ENV_VARS:
        val = os.environ.get(name)
        if val and val.strip():
            values.append(val.strip())
    return values


# --- Keys as used by each API client (same semantics as the original servers) ---

def get_vworld_api_key() -> str:
    """Helper to retrieve VWorld API key and raise a user-friendly error if missing."""
    key = vworld_key_raw()
    if not key:
        raise ValueError(
            "VWORLD_API_KEY is not set in the environment variables. "
            "Please configure VWORLD_API_KEY in your environment or .env file."
        )
    return key


def get_bldrgst_service_key() -> str:
    """Retrieve and decode the Building Ledger service key to ensure single-encoding by httpx."""
    key = bldrgst_key_raw()
    if not key:
        raise ValueError(
            "BLDRGST_API_KEY is not set in the environment variables. "
            "Please configure BLDRGST_API_KEY (or DATA_GO_KR_SERVICE_KEY) in your environment or .env file."
        )
    # Decode to raw key to avoid double-encoding issues in httpx params dict
    return urllib.parse.unquote(key)


def get_molit_service_key() -> str:
    """Retrieve and decode the MOLIT service key to ensure single-encoding by httpx."""
    key = molit_key_raw()
    if not key:
        raise ValueError(
            "MOLIT_SERVICE_KEY is not set in the environment variables. "
            "Please configure MOLIT_SERVICE_KEY (or DATA_GO_KR_SERVICE_KEY) in your environment or .env file."
        )
    return urllib.parse.unquote(key)


# --- Other settings ---

def vworld_domain() -> str:
    return os.environ.get("VWORLD_DOMAIN", "localhost")


def vworld_proxy_url() -> Optional[str]:
    return os.environ.get("VWORLD_PROXY_URL") or None


def bldrgst_proxy_url() -> Optional[str]:
    return os.environ.get("BLDRGST_PROXY_URL") or None


def rtms_concurrency() -> int:
    raw = os.environ.get("RTMS_CONCURRENCY")
    if not raw:
        return DEFAULT_RTMS_CONCURRENCY
    try:
        val = int(raw)
    except ValueError:
        return DEFAULT_RTMS_CONCURRENCY
    return val if val >= 1 else DEFAULT_RTMS_CONCURRENCY


def port() -> int:
    raw = os.environ.get("PORT")
    if not raw:
        return DEFAULT_PORT
    try:
        return int(raw)
    except ValueError:
        return DEFAULT_PORT
