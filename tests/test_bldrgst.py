import httpx
import respx

from realestate_mcp.tools import bldrgst
from tests import fixtures as fx

TITLE_URL = f"{bldrgst.BASE_URL}/getBrTitleInfo"
RECAP_URL = f"{bldrgst.BASE_URL}/getBrRecapTitleInfo"


@respx.mock
async def test_get_title_ok_and_params(fake_keys):
    route = respx.get(TITLE_URL).mock(return_value=httpx.Response(
        200, json=fx.br_json([{"bldNm": "테스트빌딩", "grndFlrCnt": 20, "ugrndFlrCnt": 5}])
    ))
    res = await bldrgst.br_get_title(pnu=fx.PNU, dongNm="101동")
    assert res["status"] == "OK"
    assert res["totalCount"] == 1
    assert res["results"][0]["bldNm"] == "테스트빌딩"
    p = route.calls.last.request.url.params
    assert (p["sigunguCd"], p["bjdongCd"], p["platGbCd"], p["bun"], p["ji"]) == ("11680", "10100", "0", "0822", "0002")
    assert p["dongNm"] == "101동" and p["_type"] == "json"
    # Decoding key 는 httpx 가 한 번만 인코딩해 전송한다
    assert p["serviceKey"] == fake_keys["bldrgst"]


@respx.mock
async def test_recap_no_data_code_03(fake_keys):
    respx.get(RECAP_URL).mock(return_value=httpx.Response(200, json=fx.br_json(None, result_code="03")))
    res = await bldrgst.br_get_recap_title(pnu=fx.PNU)
    assert res["status"] == "NOT_FOUND" and res["totalCount"] == 0


@respx.mock
async def test_auth_error_xml(fake_keys):
    respx.get(TITLE_URL).mock(return_value=httpx.Response(200, text=fx.BR_AUTH_ERROR_XML))
    res = await bldrgst.br_get_title(pnu=fx.PNU)
    assert res["status"] == "ERROR"
    assert "Authentication Error [30]" in res["message"]


async def test_missing_key_returns_error():
    res = await bldrgst.br_get_title(pnu=fx.PNU)
    assert res["status"] == "ERROR" and "BLDRGST_API_KEY" in res["message"]


async def test_invalid_pnu():
    res = await bldrgst.br_get_basis_ouln(pnu="12")
    assert res == {"status": "ERROR", "message": "PNU must be exactly 19 digits."}


@respx.mock
async def test_http_500_retried_then_network_error(fake_keys):
    route = respx.get(TITLE_URL).mock(return_value=httpx.Response(500))
    res = await bldrgst.br_get_title(pnu=fx.PNU)
    assert res["status"] == "NETWORK_ERROR"
    assert route.call_count == 2
    assert fake_keys["bldrgst"] not in res["message"]


@respx.mock
async def test_http_4xx_not_retried(fake_keys):
    route = respx.get(TITLE_URL).mock(return_value=httpx.Response(403))
    res = await bldrgst.br_get_title(pnu=fx.PNU)
    assert res["status"] == "NETWORK_ERROR"
    assert route.call_count == 1


@respx.mock
async def test_data_go_kr_shared_key(monkeypatch):
    monkeypatch.setenv("DATA_GO_KR_SERVICE_KEY", "shared-key-value-123")
    route = respx.get(TITLE_URL).mock(return_value=httpx.Response(200, json=fx.br_json([{"bldNm": "x"}])))
    res = await bldrgst.br_get_title(pnu=fx.PNU)
    assert res["status"] == "OK"
    assert route.calls.last.request.url.params["serviceKey"] == "shared-key-value-123"
