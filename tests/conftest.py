"""공용 픽스처. 실제 API 키 없이 동작한다(모든 HTTP 는 respx 로 목킹)."""
import pytest

from realestate_mcp import common

# 가짜 키. 실제 키가 아니며, 마스킹 검증용으로 URL 인코딩이 필요한 문자를 포함한다.
FAKE_VWORLD_KEY = "FAKE-VWORLD-KEY-0000-TEST"
FAKE_BLDRGST_KEY = "fakeBldKey+abc/def==TEST"
FAKE_MOLIT_KEY = "fakeMolitKey+xyz/uvw==TEST"

ALL_KEY_VARS = (
    "VWORLD_API_KEY",
    "BLDRGST_API_KEY",
    "MOLIT_SERVICE_KEY",
    "DATA_GO_KR_SERVICE_KEY",
    "VWORLD_PROXY_URL",
    "BLDRGST_PROXY_URL",
    "VWORLD_DOMAIN",
    "RTMS_CONCURRENCY",
)


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch):
    """Remove any real keys that a local .env may have loaded; disable retry backoff."""
    for name in ALL_KEY_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(common, "RETRY_BACKOFF_SECONDS", 0)
    yield


@pytest.fixture
def fake_keys(monkeypatch):
    monkeypatch.setenv("VWORLD_API_KEY", FAKE_VWORLD_KEY)
    monkeypatch.setenv("BLDRGST_API_KEY", FAKE_BLDRGST_KEY)
    monkeypatch.setenv("MOLIT_SERVICE_KEY", FAKE_MOLIT_KEY)
    return {
        "vworld": FAKE_VWORLD_KEY,
        "bldrgst": FAKE_BLDRGST_KEY,
        "molit": FAKE_MOLIT_KEY,
    }
