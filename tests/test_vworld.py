import httpx
import pytest
import respx

from realestate_mcp.tools import vworld
from tests import fixtures as fx


@respx.mock
async def test_get_parcel_ok(fake_keys):
    route = respx.get(vworld.DATA_API_URL).mock(return_value=httpx.Response(200, json=fx.vworld_parcel()))
    res = await vworld.vworld_get_parcel(fx.PNU)
    assert res["status"] == "OK"
    assert res["pnu"] == fx.PNU
    assert res["geometry"]["type"] == "MultiPolygon"
    params = route.calls.last.request.url.params
    assert params["attrFilter"] == f"pnu:=:{fx.PNU}"
    assert params["data"] == "LP_PA_CBND_BUBUN"
    assert params["domain"] == "localhost"


async def test_get_parcel_bad_length(fake_keys):
    res = await vworld.vworld_get_parcel("123")
    assert res == {"status": "ERROR", "message": "PNU must be exactly 19 digits."}


async def test_missing_key_raises():
    with pytest.raises(ValueError, match="VWORLD_API_KEY"):
        await vworld.vworld_get_parcel(fx.PNU)


@respx.mock
async def test_get_parcel_error_envelope(fake_keys):
    respx.get(vworld.DATA_API_URL).mock(
        return_value=httpx.Response(200, json=fx.vworld_status("ERROR", "INCORRECT_KEY", "인증키 정보가 올바르지 않습니다."))
    )
    res = await vworld.vworld_get_parcel(fx.PNU)
    assert res["status"] == "ERROR"
    assert res["message"] == "VWorld Error [INCORRECT_KEY]: 인증키 정보가 올바르지 않습니다."


@respx.mock
async def test_network_error_is_masked(fake_keys):
    respx.get(vworld.DATA_API_URL).mock(side_effect=httpx.ConnectError(f"failed key={fake_keys['vworld']}"))
    res = await vworld.vworld_get_parcel(fx.PNU)
    assert res["status"] == "NETWORK_ERROR"
    assert fake_keys["vworld"] not in res["message"]


@respx.mock
async def test_geocode_retries_once_on_5xx(fake_keys):
    route = respx.get(vworld.ADDRESS_API_URL).mock(
        side_effect=[httpx.Response(502), httpx.Response(200, json=fx.vworld_geocode())]
    )
    res = await vworld.vworld_geocode("테헤란로 000")
    assert res["status"] == "OK"
    assert res["coordinates"] == {"lat": 37.5001, "lon": 127.0361}
    assert route.call_count == 2
    assert route.calls.last.request.url.params["type"] == "ROAD"


@respx.mock
async def test_individual_price_year_fallback(fake_keys):
    empty = {"landCharacteristicss": {"field": []}}
    route = respx.get(vworld.NED_CHARACTERISTICS_URL).mock(
        side_effect=[httpx.Response(200, json=empty), httpx.Response(200, json=fx.ned_price("12345000"))]
    )
    res = await vworld.vworld_get_individual_price(fx.PNU)
    assert res["status"] == "OK"
    assert res["individual_public_price"] == 12345000
    assert res["unit"] == "KRW/㎡"
    years = [int(c.request.url.params["stdrYear"]) for c in route.calls]
    assert years[1] == years[0] - 1
    assert res["year"] == str(years[1])


@respx.mock
async def test_landuse_zone_by_pnu(fake_keys):
    respx.get(vworld.DATA_API_URL).mock(return_value=httpx.Response(200, json=fx.vworld_parcel()))

    def wfs(request: httpx.Request) -> httpx.Response:
        layer = request.url.params["TYPENAME"]
        assert request.url.params["KEY"] == fake_keys["vworld"]
        if layer == "lt_c_uq111":
            return httpx.Response(200, json=fx.wfs_features([{"uname": "일반상업지역", "ucode": "UQA220"}]))
        return httpx.Response(200, json=fx.wfs_features([]))

    respx.get(vworld.WFS_API_URL).mock(side_effect=wfs)
    res = await vworld.vworld_get_landuse_zone(pnu=fx.PNU)
    assert res["status"] == "OK"
    assert [z["name"] for z in res["zoning_info"]] == ["일반상업지역"]
    assert res["queried_coordinates"]["lat"] == pytest.approx(37.5001)


@respx.mock
async def test_find_parcel_by_point(fake_keys):
    route = respx.get(vworld.DATA_API_URL).mock(return_value=httpx.Response(200, json=fx.vworld_parcel()))
    res = await vworld.vworld_find_parcel_by_point(37.5001, 127.0361)
    assert res["status"] == "OK" and res["pnu"] == fx.PNU
    assert route.calls.last.request.url.params["geomFilter"] == "POINT(127.0361 37.5001)"


@respx.mock
async def test_search_address_merges_and_dedupes(fake_keys):
    item = {"id": "1", "title": "t", "address": {"road": "r"}, "category": "road", "point": {"x": "127", "y": "37"}}
    body = {"response": {"status": "OK", "result": {"items": [item]}}}
    respx.get(vworld.SEARCH_API_URL).mock(return_value=httpx.Response(200, json=body))
    res = await vworld.vworld_search("테헤란로")
    assert res["status"] == "OK" and len(res["results"]) == 1
