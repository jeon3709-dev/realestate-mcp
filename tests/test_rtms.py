import asyncio
import urllib.parse

import httpx
import pytest
import respx

from realestate_mcp.tools import rtms
from tests import fixtures as fx

LAND_URL = f"{rtms.BASE_URL}/RTMSDataSvcLandTrade/getRTMSDataSvcLandTrade"
NRG_URL = f"{rtms.BASE_URL}/RTMSDataSvcNrgTrade/getRTMSDataSvcNrgTrade"
APT_URL = f"{rtms.BASE_URL}/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev"


# --- Pure helpers (original formulas) ---

def test_price_and_pyung():
    assert rtms.calc_price_per_pyung(100000, 330.0) == round(100000 / (330.0 * 0.3025), 1)
    assert rtms.calc_price_per_pyung(100000, 0) == 0.0
    assert rtms.clean_amount("12,345") == 12345
    assert rtms.clean_amount("") == 0
    assert rtms.clean_area(" 99.5 ") == 99.5
    assert rtms.format_price(123456) == "12억 3,456만원"
    assert rtms.format_price(20000) == "2억원"
    assert rtms.format_price(9500) == "9,500만원"


def test_median():
    assert rtms.calculate_median([]) == 0.0
    assert rtms.calculate_median([3.0, 1.0, 2.0]) == 2.0
    assert rtms.calculate_median([4.0, 1.0, 2.0, 3.0]) == 2.5


def test_months_list_format():
    months = rtms.get_months_list(14)
    assert len(months) == 14 and all(len(m) == 6 for m in months)
    assert months == sorted(months, reverse=True)


def test_resolve_lawd_cd_and_lookup():
    res = rtms.resolve_lawd_cd("서울특별시", "중구", "광희동")
    assert res["status"] == "OK" and res["lawd_cd"] == "11140"
    assert set(res["matched_dongs"]) == {"광희동1가", "광희동2가"}
    assert rtms.resolve_lawd_cd(None, "없는구", "없는동")["status"] == "NOT_FOUND"
    info = rtms.lookup_bdong("1168010100")
    assert info is not None and info["dong"] == "역삼동"
    assert rtms.lookup_bdong("0000000000") is None


def test_dong_name_matches():
    assert rtms.dong_name_matches("광희동1가", "광희동")
    assert rtms.dong_name_matches("역삼동", "역삼동")
    assert not rtms.dong_name_matches("삼성동", "역삼동")
    assert not rtms.dong_name_matches("", "역삼동")


def test_resolve_region_priority():
    region, err = rtms.resolve_region(None, "중구", "광희동", fx.PNU, None)
    assert err is None and region is not None and region.lawd_cd == "11680"
    region, err = rtms.resolve_region(None, None, None, None, "11140")
    assert region is not None and region.lawd_cd == "11140" and region.matches("아무동")
    region, err = rtms.resolve_region(None, None, None, "123", None)
    assert region is None and err is not None and err["status"] == "ERROR"
    region, err = rtms.resolve_region(None, None, None, None, None)
    assert region is None and err is not None and "must be provided" in err["message"]


# --- Tool tests (HTTP mocked) ---

@respx.mock
async def test_land_legacy_call_filters_dong(fake_keys):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["LAWD_CD"] == "11140"
        return httpx.Response(200, text=fx.rtms_xml([
            fx.land_item("광희동1가", "1", "100,000", "330", "2026", "8", "5"),
            fx.land_item("을지로6가", "2", "50,000", "100", "2026", "8", "6"),
        ]))

    respx.get(LAND_URL).mock(side_effect=handler)
    res = await rtms.rtms_search_land_transactions("중구", "광희동", months_back=1)
    assert res["status"] == "OK"
    assert [t["address"] for t in res["transactions"]] == ["광희동1가 1"]
    assert res["report"].startswith("## 🗺️ 토지 실거래가 조회 결과 (중구 광희동)")
    assert res["summary"]["price_stats"]["median"] == rtms.calc_price_per_pyung(100000, 330.0)


@respx.mock
async def test_land_pnu_path_skips_db_and_filters(fake_keys, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("code_bdong.json must not be used when pnu is given")

    monkeypatch.setattr(rtms, "resolve_lawd_cd", boom)
    route = respx.get(LAND_URL).mock(return_value=httpx.Response(200, text=fx.rtms_xml([
        fx.land_item("역삼동", "1", "100,000", "330", "2026", "8", "5"),
        fx.land_item("삼성동", "2", "50,000", "100", "2026", "8", "6"),
    ])))
    res = await rtms.rtms_search_land_transactions(pnu=fx.PNU, dong="역삼동", months_back=1)
    assert route.calls.last.request.url.params["LAWD_CD"] == "11680"
    assert [t["address"] for t in res["transactions"]] == ["역삼동 1"]
    assert "(LAWD_CD 11680 역삼동)" in res["report"]

    res_all = await rtms.rtms_search_land_transactions(pnu=fx.PNU, months_back=1)
    assert len(res_all["transactions"]) == 2


@respx.mock
async def test_commercial_dual_price(fake_keys):
    respx.get(NRG_URL).mock(return_value=httpx.Response(200, text=fx.rtms_xml([
        fx.nrg_item("역삼동", "1**", "500,000", "330", "1000", "2026", "7", "1"),
    ])))
    res = await rtms.rtms_search_commercial_transactions(lawd_cd="11680", dong="역삼동", months_back=1)
    assert res["status"] == "OK"
    s = res["summary"]
    assert s["land_price_stats"]["median"] == rtms.calc_price_per_pyung(500000, 330.0)
    assert s["building_price_stats"]["median"] == rtms.calc_price_per_pyung(500000, 1000.0)


@respx.mock
async def test_empty_result_fallback_message(fake_keys):
    respx.get(APT_URL).mock(return_value=httpx.Response(200, text=fx.rtms_xml([])))
    res = await rtms.rtms_search_apartment_transactions("중구", "광희동", months_back=2)
    assert res["status"] == "NO_DATA"
    assert "⚠️ **조회 결과 거래 사례가 0건입니다.**" in res["message"]
    assert "- 지역:  중구 광희동" in res["message"]


@respx.mock
async def test_auth_error(fake_keys):
    respx.get(LAND_URL).mock(return_value=httpx.Response(200, text=fx.RTMS_AUTH_ERROR_XML))
    res = await rtms.rtms_search_land_transactions(pnu=fx.PNU, months_back=3)
    assert res["status"] == "ERROR"
    assert res["message"] == "OpenAPI Authentication Failure: SERVICE ERROR"


async def test_missing_key():
    res = await rtms.rtms_search_land_transactions(pnu=fx.PNU, months_back=1)
    assert res["status"] == "ERROR" and "MOLIT_SERVICE_KEY" in res["message"]


@respx.mock
async def test_parallel_months_preserve_original_order(fake_keys, monkeypatch):
    """Later months answer first, yet items are concatenated in month order (== sequential)."""
    monkeypatch.setenv("RTMS_CONCURRENCY", "3")
    months = rtms.get_months_list(6)
    delay = {ymd: 0.05 * (len(months) - i) for i, ymd in enumerate(months)}
    in_flight = 0
    peak = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        ymd = request.url.params["DEAL_YMD"]
        page = int(request.url.params["pageNo"])
        await asyncio.sleep(delay[ymd])
        in_flight -= 1
        # every month has 2 pages (100 rows/page, total 101)
        items = [fx.land_item("역삼동", f"{ymd}-{page}", "10,000", "100", ymd[:4], ymd[4:], "15")]
        return httpx.Response(200, text=fx.rtms_xml(items, total=101, num_rows=100))

    respx.get(LAND_URL).mock(side_effect=handler)
    status, items = await rtms.fetch_api_data("RTMSDataSvcLandTrade", "11680", months)
    assert status == "OK"
    assert [it["jibun"] for it in items] == [f"{m}-{p}" for m in months for p in (1, 2)]
    assert 1 < peak <= 3


@respx.mock
async def test_month_error_skips_only_that_month(fake_keys):
    months = rtms.get_months_list(3)

    def handler(request: httpx.Request) -> httpx.Response:
        ymd = request.url.params["DEAL_YMD"]
        if ymd == months[1]:
            return httpx.Response(200, text=fx.rtms_xml([], result_code="99"))
        return httpx.Response(200, text=fx.rtms_xml([fx.land_item("역삼동", ymd, "1", "1", ymd[:4], ymd[4:], "1")]))

    respx.get(LAND_URL).mock(side_effect=handler)
    status, items = await rtms.fetch_api_data("RTMSDataSvcLandTrade", "11680", months)
    assert status == "OK"
    assert [it["jibun"] for it in items] == [months[0], months[2]]


@respx.mock
async def test_service_key_sent_decoded_once(monkeypatch):
    encoded = urllib.parse.quote("abc+def/ghi==", safe="")
    monkeypatch.setenv("MOLIT_SERVICE_KEY", encoded)
    route = respx.get(LAND_URL).mock(return_value=httpx.Response(200, text=fx.rtms_xml([])))
    await rtms.fetch_api_data("RTMSDataSvcLandTrade", "11680", rtms.get_months_list(1))
    assert route.calls.last.request.url.params["serviceKey"] == "abc+def/ghi=="


@pytest.mark.parametrize("bad", [{"pnu": "1"}, {"lawd_cd": "1"}, {"pnu": fx.PNU, "lawd_cd": "11140"}])
async def test_region_errors(fake_keys, bad):
    res = await rtms.rtms_search_land_transactions(months_back=1, **bad)
    assert res["status"] == "ERROR"
