import json
from typing import Any, Dict

import httpx
import pytest
import respx

from realestate_mcp.tools import bldrgst, composite, rtms, vworld
from tests import fixtures as fx

BR_BASE = bldrgst.BASE_URL
LAND_URL = f"{rtms.BASE_URL}/RTMSDataSvcLandTrade/getRTMSDataSvcLandTrade"
NRG_URL = f"{rtms.BASE_URL}/RTMSDataSvcNrgTrade/getRTMSDataSvcNrgTrade"
APT_URL = f"{rtms.BASE_URL}/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev"

RECAP = {"platArea": "1000.5", "archArea": "550", "totArea": "12000", "bcRat": "55.2", "vlRat": "799.1",
         "mainPurpsCdNm": "업무시설", "mainBldCnt": "1", "totPkngCnt": "100"}
TITLE = {"bldNm": "테스트빌딩", "dongNm": "", "grndFlrCnt": "20", "ugrndFlrCnt": "5", "mainPurpsCdNm": "업무시설",
         "platArea": "1000.5", "totArea": "12000", "bcRat": "55.2", "vlRat": "799.1"}
JIJIGU = [{"jijiguCdNm": "일반상업지역", "jijiguGbCdNm": "국토계획법", "reprYn": "1"},
          {"jijiguCdNm": "방화지구", "jijiguGbCdNm": "국토계획법", "reprYn": "0"}]


def _mock_world(router: respx.MockRouter, *, building_status: int = 200, stats: Dict[str, int] | None = None) -> None:
    months = rtms.get_months_list(12)
    calls: Dict[str, int] = stats if stats is not None else {}

    def count(name: str) -> None:
        calls[name] = calls.get(name, 0) + 1

    def data_api(request: httpx.Request) -> httpx.Response:
        count("data")
        return httpx.Response(200, json=fx.vworld_parcel())

    def address_api(request: httpx.Request) -> httpx.Response:
        count("address")
        if request.url.params["request"] == "getcoord":
            if request.url.params["type"] == "ROAD":
                return httpx.Response(200, json=fx.vworld_status("NOT_FOUND"))
            return httpx.Response(200, json=fx.vworld_geocode())
        return httpx.Response(200, json=fx.vworld_reverse())

    def wfs(request: httpx.Request) -> httpx.Response:
        if request.url.params["TYPENAME"] == "lt_c_uq111":
            return httpx.Response(200, json=fx.wfs_features([
                {"uname": None, "ucode": "UQA01X"},  # 실응답에서 uname 이 null 인 도시지역 피처가 함께 옴
                {"uname": "일반상업지역", "ucode": "UQA220"},
            ]))
        return httpx.Response(200, json=fx.wfs_features([]))

    def br(request: httpx.Request) -> httpx.Response:
        count("br")
        if building_status != 200:
            return httpx.Response(building_status)
        op = request.url.path.rsplit("/", 1)[-1]
        payload = {"getBrRecapTitleInfo": [RECAP], "getBrTitleInfo": [TITLE], "getBrJijiguInfo": JIJIGU}[op]
        return httpx.Response(200, json=fx.br_json(payload))

    def land(request: httpx.Request) -> httpx.Response:
        count("rtms")
        assert request.url.params["LAWD_CD"] == "11680"
        if request.url.params["DEAL_YMD"] != months[0]:
            return httpx.Response(200, text=fx.rtms_xml([]))
        y, m = months[0][:4], months[0][4:]
        return httpx.Response(200, text=fx.rtms_xml([
            fx.land_item("역삼동", "1", "100,000", "330", y, m, "1"),
            fx.land_item("역삼동", "2", "300,000", "330", y, m, "2"),
            fx.land_item("삼성동", "3", "900,000", "330", y, m, "3"),
        ]))

    def nrg(request: httpx.Request) -> httpx.Response:
        count("rtms")
        return httpx.Response(200, text=fx.rtms_xml([]))

    router.get(vworld.DATA_API_URL).mock(side_effect=data_api)
    router.get(vworld.ADDRESS_API_URL).mock(side_effect=address_api)
    router.get(vworld.WFS_API_URL).mock(side_effect=wfs)
    router.get(vworld.NED_CHARACTERISTICS_URL).mock(return_value=httpx.Response(200, json=fx.ned_price("50000000", "1000")))
    router.route(method="GET", url__startswith=BR_BASE).mock(side_effect=br)
    router.get(LAND_URL).mock(side_effect=land)
    router.get(NRG_URL).mock(side_effect=nrg)


@respx.mock
async def test_site_profile_by_pnu_ok(fake_keys):
    stats: Dict[str, int] = {}
    _mock_world(respx.mock, stats=stats)
    res = await composite.site_profile(pnu=fx.PNU)

    assert res["status"] == "OK"
    assert res["pnu"] == fx.PNU
    assert res["address"]["jibun"] == "서울특별시 강남구 역삼동 822-2"
    assert res["address"]["road"] == "서울특별시 강남구 테헤란로 000"
    assert res["coordinates"]["source"] == "parcel_centroid"
    for name in ("parcel", "landuse", "land_price", "building", "transactions"):
        assert res["sections"][name]["status"] == "OK", name

    ind = res["summary"]["indicators"]
    assert ind["land_area_m2"] == 1000.0 and ind["land_area_pyung"] == 302.5
    assert ind["jimok"] == "대"
    assert ind["zoning"] == ["일반상업지역"]
    assert ind["zoning_districts"] == ["일반상업지역", "방화지구"]
    assert ind["land_price_per_m2"] == 50000000
    assert ind["land_price_per_pyung"] == round(50000000 / 0.3025)
    assert ind["main_purpose"] == "업무시설"
    assert ind["total_floor_area_m2"] == 12000.0
    assert ind["building_coverage_ratio"] == 55.2 and ind["floor_area_ratio"] == 799.1
    assert ind["ground_floors"] == 20 and ind["underground_floors"] == 5
    assert ind["building_count"] == 1
    assert ind["building_basis"] == "총괄표제부"
    assert "use_approval_date" not in ind  # 미확인 필드는 요약에서 제외

    land = ind["transactions"]["land"]
    assert land["valid_count"] == 2  # 삼성동 거래는 법정동 필터로 제외
    assert land["median_price_per_pyung"] == rtms.calculate_median([
        rtms.calc_price_per_pyung(100000, 330.0), rtms.calc_price_per_pyung(300000, 330.0)])
    assert ind["transactions"]["commercial"]["status"] == "NOT_FOUND"
    assert ind["transactions"]["commercial"]["median_land_price_per_pyung"] is None

    md = res["summary"]["markdown"]
    assert md.startswith(f"## 📍 부지 종합 프로파일 (PNU {fx.PNU})")
    assert "### 📊 거래 분석 요약 (토지)" in md
    assert md.rstrip().endswith("공공 API 원자료 기준이며 등기부·현장 확인이 필요함")

    assert res["sections"]["parcel"]["data"]["cadastral_addr"] == "서울특별시 강남구 역삼동 822-2"
    src = res["sources"]
    assert src["parcel"]["reference_year_month"] == "2025-01"
    assert src["land_price"]["reference_year"] == res["sections"]["land_price"]["data"]["year"]
    months = rtms.get_months_list(12)
    assert src["transactions"]["deal_ymd_range"] == f"{months[-1]}~{months[0]}"
    assert src["transactions"]["dong_filter"] == "역삼동"
    assert stats["rtms"] == 24  # land + commercial × 12개월
    assert stats["br"] == 3
    json.dumps(res, ensure_ascii=False)  # JSON 직렬화 가능


@respx.mock
async def test_site_profile_building_fails_partial(fake_keys):
    _mock_world(respx.mock, building_status=500)
    res = await composite.site_profile(pnu=fx.PNU)

    assert res["status"] == "PARTIAL"
    assert res["sections"]["building"]["status"] == "ERROR"
    for name in ("parcel", "landuse", "land_price", "transactions"):
        assert res["sections"][name]["status"] == "OK", name
    ind = res["summary"]["indicators"]
    assert ind["main_purpose"] is None
    assert ind["total_floor_area_m2"] is None
    assert ind["ground_floors"] is None
    assert ind["building_count"] is None
    assert ind["land_price_per_m2"] == 50000000
    assert "| building | ERROR |" in res["summary"]["markdown"]


@respx.mock
async def test_site_profile_by_address(fake_keys):
    _mock_world(respx.mock)
    res = await composite.site_profile(address="서울특별시 강남구 역삼동 822-2", transaction_types=["land"], include_building=False)
    assert res["status"] == "OK"
    assert res["pnu"] == fx.PNU
    assert res["resolution"]["method"] == "address"
    assert res["resolution"]["address_type"] == "parcel"
    assert res["coordinates"]["source"] == "vworld_geocode"
    assert res["address"]["refined"] == "서울특별시 강남구 역삼동 822-2"
    assert res["sections"]["building"]["status"] == "SKIPPED"
    assert list(res["sections"]["transactions"]["data"]) == ["land"]


@respx.mock
async def test_site_profile_road_address_falls_back_to_parcel(fake_keys):
    _mock_world(respx.mock)
    res = await composite.site_profile(address="테헤란로 000", include_building=False, include_transactions=False)
    tried = [a["address_type"] for a in res["resolution"]["attempts"]]
    assert tried == ["road", "parcel"]
    assert res["pnu"] == fx.PNU


async def test_site_profile_requires_input():
    res = await composite.site_profile()
    assert res["status"] == "ERROR" and "must be provided" in res["message"]
    res = await composite.site_profile(pnu="123")
    assert res["status"] == "ERROR" and "19 digits" in res["message"]


async def test_site_profile_missing_vworld_key_for_address():
    res = await composite.site_profile(address="역삼동 822-2")
    assert res["status"] == "ERROR"
    assert all(s["status"] == "SKIPPED" for s in res["sections"].values())


@respx.mock
async def test_site_profile_missing_keys_by_pnu_all_sections_error():
    res = await composite.site_profile(pnu=fx.PNU)
    assert res["status"] == "ERROR"
    assert res["sections"]["parcel"]["status"] == "ERROR"
    assert "VWORLD_API_KEY" in res["sections"]["parcel"]["message"]
    assert res["sections"]["building"]["status"] == "ERROR"
    assert res["summary"]["indicators"]["land_area_m2"] is None


@respx.mock
async def test_health_check_per_api(fake_keys):
    respx.get(vworld.SEARCH_API_URL).mock(return_value=httpx.Response(200, json={"response": {"status": "OK"}}))
    respx.get(f"{BR_BASE}/getBrBasisOulnInfo").mock(return_value=httpx.Response(200, json=fx.br_json(None, "03")))
    respx.get(APT_URL).mock(return_value=httpx.Response(200, text=fx.RTMS_AUTH_ERROR_XML))
    res = await composite.health_check()
    assert res["status"] == "DEGRADED"
    assert res["apis"]["vworld"]["status"] == "OK"
    assert res["apis"]["bldrgst"]["status"] == "OK"
    assert res["apis"]["rtms"]["status"] == "AUTH_ERROR"
    assert all(res["keys_configured"].values())
    assert fake_keys["bldrgst"] not in json.dumps(res, ensure_ascii=False)


async def test_health_check_without_keys():
    res = await composite.health_check()
    assert res["status"] == "ERROR"
    for api in ("vworld", "bldrgst", "rtms"):
        assert res["apis"][api]["status"] == "ERROR"
        assert "Configuration error" in res["apis"][api]["message"]
    assert not any(res["keys_configured"].values())


@pytest.mark.parametrize("value,expected", [("1,000.5", 1000.5), ("", None), (None, None), ("abc", None), (3, 3.0)])
def test_to_float(value: Any, expected: Any):
    assert composite._to_float(value) == expected
