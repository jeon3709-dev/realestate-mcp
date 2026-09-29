import logging
import urllib.parse

import httpx
import pytest
import respx

from realestate_mcp import common, config
from tests.conftest import FAKE_BLDRGST_KEY, FAKE_MOLIT_KEY, FAKE_VWORLD_KEY


def test_sanitize_param_forms(fake_keys):
    msg = (
        "GET https://api.vworld.kr/req/wfs?KEY=abc123&x=1 "
        "https://apis.data.go.kr/x?serviceKey=zzz999&LAWD_CD=11110 key=qqq"
    )
    out = common.sanitize_error(msg)
    assert "abc123" not in out and "zzz999" not in out and "qqq" not in out
    assert "KEY=***" in out and "serviceKey=***" in out


@pytest.mark.parametrize("key", [FAKE_VWORLD_KEY, FAKE_BLDRGST_KEY, FAKE_MOLIT_KEY])
def test_sanitize_raw_and_encoded(fake_keys, key):
    encoded = urllib.parse.quote(key, safe="")
    httpx_form = str(httpx.QueryParams({"k": key}))[2:]
    for form in {key, encoded, httpx_form, urllib.parse.quote_plus(key)}:
        out = common.sanitize_error(f"error near {form} end")
        assert form not in out
        assert "***" in out


def test_sanitize_encoded_env_value(monkeypatch):
    """If the env holds the Encoding key, the decoded form must also be masked."""
    decoded = "abc+def/ghi==SECRET"
    monkeypatch.setenv("DATA_GO_KR_SERVICE_KEY", urllib.parse.quote(decoded, safe=""))
    out = common.sanitize_error(f"boom {decoded} boom")
    assert decoded not in out


def test_sanitize_empty():
    assert common.sanitize_error("") == ""
    assert common.sanitize_error(None) == ""


def test_log_filter_masks(fake_keys, caplog):
    logger = logging.getLogger("test-sanitize")
    handler = logging.Handler()
    records = []
    handler.emit = records.append  # type: ignore[method-assign]
    handler.addFilter(common.SanitizingLogFilter())
    logger.addHandler(handler)
    try:
        logger.warning("url %s", f"https://x/?serviceKey={FAKE_MOLIT_KEY}")
    finally:
        logger.removeHandler(handler)
    assert records and FAKE_MOLIT_KEY not in records[0].getMessage()


def test_data_go_kr_fallback(monkeypatch):
    monkeypatch.setenv("DATA_GO_KR_SERVICE_KEY", "shared%2Bkey")
    assert config.get_bldrgst_service_key() == "shared+key"
    assert config.get_molit_service_key() == "shared+key"
    monkeypatch.setenv("BLDRGST_API_KEY", "own-bld-key")
    assert config.get_bldrgst_service_key() == "own-bld-key"
    assert config.get_molit_service_key() == "shared+key"


def test_missing_keys_raise():
    for fn, name in (
        (config.get_vworld_api_key, "VWORLD_API_KEY"),
        (config.get_bldrgst_service_key, "BLDRGST_API_KEY"),
        (config.get_molit_service_key, "MOLIT_SERVICE_KEY"),
    ):
        with pytest.raises(ValueError, match=name):
            fn()


def test_placeholder_is_missing(monkeypatch):
    monkeypatch.setenv("VWORLD_API_KEY", "your_api_key_here")
    with pytest.raises(ValueError):
        config.get_vworld_api_key()


def test_rtms_concurrency(monkeypatch):
    assert config.rtms_concurrency() == 5
    monkeypatch.setenv("RTMS_CONCURRENCY", "3")
    assert config.rtms_concurrency() == 3
    monkeypatch.setenv("RTMS_CONCURRENCY", "0")
    assert config.rtms_concurrency() == 5
    monkeypatch.setenv("RTMS_CONCURRENCY", "abc")
    assert config.rtms_concurrency() == 5


def test_headers_per_api(monkeypatch):
    assert common.get_api_headers("vworld")["Referer"] == "http://localhost/"
    monkeypatch.setenv("VWORLD_DOMAIN", "my-app.cloudtype.app")
    assert common.get_api_headers("vworld")["Referer"] == "https://my-app.cloudtype.app/"
    assert "xml" in common.get_api_headers("rtms")["Accept"]
    assert "Referer" not in common.get_api_headers("bldrgst")


@respx.mock
async def test_retry_on_5xx_then_success():
    route = respx.get("https://example.test/a").mock(
        side_effect=[httpx.Response(502), httpx.Response(200, text="ok")]
    )
    async with httpx.AsyncClient() as client:
        resp = await common.get_with_retry(client, "https://example.test/a")
    assert resp.status_code == 200
    assert route.call_count == 2


@respx.mock
async def test_retry_on_network_error_then_raise():
    route = respx.get("https://example.test/b").mock(side_effect=httpx.ConnectError("down"))
    async with httpx.AsyncClient() as client:
        with pytest.raises(httpx.ConnectError):
            await common.get_with_retry(client, "https://example.test/b")
    assert route.call_count == 2


@respx.mock
async def test_no_retry_on_4xx():
    route = respx.get("https://example.test/c").mock(return_value=httpx.Response(401))
    async with httpx.AsyncClient() as client:
        resp = await common.get_with_retry(client, "https://example.test/c")
    assert resp.status_code == 401
    assert route.call_count == 1


@respx.mock
async def test_5xx_after_retry_returned():
    route = respx.get("https://example.test/d").mock(return_value=httpx.Response(503))
    async with httpx.AsyncClient() as client:
        resp = await common.get_with_retry(client, "https://example.test/d")
    assert resp.status_code == 503
    assert route.call_count == 2
