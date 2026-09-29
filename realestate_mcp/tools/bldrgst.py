"""건축HUB 건축물대장정보 서비스 도구 (원본: jeon3709-dev/BDLedger_MCP server.py).

원본 로직·파라미터·반환 형식을 그대로 옮겼다. 변경점:
- 키/HTTP 클라이언트/마스킹/parse_pnu 는 config·common·pnu 공용 함수를 사용
  (키는 BLDRGST_API_KEY, 없으면 DATA_GO_KR_SERVICE_KEY)
- 데이터 조회 요청은 get_with_retry(5xx·네트워크 오류 1회 재시도)로 보냄
- br_health_check 는 통합 health_check 의 내부 함수 _bldrgst_health 로 이동
"""
import logging
import re
import time
from typing import Any, Dict, Optional

import httpx
from mcp.server.fastmcp import FastMCP

from .. import config
from ..common import get_with_retry, make_client, sanitize_error
from ..pnu import parse_pnu

logger = logging.getLogger("bdledger-mcp")

BASE_URL = "https://apis.data.go.kr/1613000/BldRgstHubService"


def get_http_client() -> httpx.AsyncClient:
    """Return an httpx AsyncClient with optional proxy configuration."""
    return make_client("bldrgst")


def get_service_key() -> str:
    """Retrieve and decode the API service key to ensure single-encoding by httpx."""
    return config.get_bldrgst_service_key()


def parse_api_response(response: httpx.Response) -> Dict[str, Any]:
    """Parse JSON/XML from data.go.kr, normalize lists, and standardise status codes."""
    text = response.text
    # If the response is XML (usually happens for auth errors)
    if text.strip().startswith("<") or "OpenAPI_ServiceResponse" in text:
        err_msg_match = re.search(r"<errMsg>(.*?)</errMsg>", text)
        return_reason_match = re.search(r"<returnReasonCode>(.*?)</returnReasonCode>", text)
        err_msg = err_msg_match.group(1) if err_msg_match else "Unknown OpenAPI Error"
        reason_code = return_reason_match.group(1) if return_reason_match else "UNKNOWN"
        if "SERVICE_KEY_IS_NOT_REGISTERED_ERROR" in text or reason_code == "30":
            return {
                "status": "ERROR",
                "message": f"OpenAPI Authentication Error [{reason_code}]: {err_msg}. "
                           "Please check if your BLDRGST_API_KEY is correctly configured."
            }
        return {"status": "ERROR", "message": f"OpenAPI Error [{reason_code}]: {err_msg}"}
    
    try:
        data = response.json()
    except ValueError:
        return {"status": "ERROR", "message": f"Failed to parse JSON response: {sanitize_error(text[:200])}"}

    res_envelope = data.get("response", {})
    header = res_envelope.get("header", {})
    result_code = header.get("resultCode")
    result_msg = header.get("resultMsg", "No message provided")

    # Handle result codes. "00" = Successful, "03" = No Data
    if result_code == "03":
        return {
            "status": "NOT_FOUND",
            "message": f"No data found: {result_msg}",
            "results": [],
            "totalCount": 0
        }
    elif result_code != "00":
        return {"status": "ERROR", "message": f"API Error [{result_code}]: {result_msg}"}

    body = res_envelope.get("body", {})
    items_node = body.get("items")
    results = []
    if items_node:
        item = items_node.get("item")
        if item is not None:
            if isinstance(item, list):
                results = item
            elif isinstance(item, dict):
                results = [item]
    
    total_count = body.get("totalCount")
    try:
        total_count = int(total_count) if total_count is not None else len(results)
    except ValueError:
        total_count = len(results)

    if not results:
        return {
            "status": "NOT_FOUND",
            "message": "No records found.",
            "results": [],
            "totalCount": 0
        }

    return {
        "status": "OK",
        "results": results,
        "totalCount": total_count
    }

async def fetch_building_ledger_data(
    endpoint: str,
    sigunguCd: str,
    bjdongCd: str,
    platGbCd: str,
    bun: str,
    ji: str,
    numOfRows: int = 100,
    pageNo: int = 1,
    extra_params: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Execute the async HTTP call to data.go.kr Building Ledger API."""
    try:
        api_key = get_service_key()
    except Exception as e:
        return {"status": "ERROR", "message": f"Configuration error: {sanitize_error(str(e))}"}

    params = {
        "serviceKey": api_key,
        "sigunguCd": sigunguCd,
        "bjdongCd": bjdongCd,
        "platGbCd": platGbCd,
        "bun": str(bun).zfill(4),
        "ji": str(ji).zfill(4),
        "numOfRows": str(numOfRows),
        "pageNo": str(pageNo),
        "_type": "json"
    }
    if extra_params:
        params.update({k: str(v) for k, v in extra_params.items() if v is not None})
        
    async with get_http_client() as client:
        url = f"{BASE_URL}/{endpoint}"
        try:
            logger.info(f"Requesting {url} with params: {sanitize_error(str(params))}")
            response = await get_with_retry(client, url, params=params)
            response.raise_for_status()
            return parse_api_response(response)
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP status error for {endpoint}: {sanitize_error(str(e))}")
            return {"status": "NETWORK_ERROR", "message": f"HTTP status error: {sanitize_error(str(e))}"}
        except httpx.HTTPError as e:
            logger.error(f"Network error for {endpoint}: {sanitize_error(str(e))}")
            return {"status": "NETWORK_ERROR", "message": f"Network request failed: {sanitize_error(str(e))}"}
        except Exception as e:
            logger.error(f"Unexpected error for {endpoint}: {sanitize_error(str(e))}")
            return {"status": "ERROR", "message": f"An unexpected error occurred: {sanitize_error(str(e))}"}

# --- MCP Tools ---

async def br_get_basis_ouln(
    pnu: Optional[str] = None,
    sigunguCd: Optional[str] = None,
    bjdongCd: Optional[str] = None,
    platGbCd: Optional[str] = None,
    bun: Optional[str] = None,
    ji: Optional[str] = None,
    numOfRows: int = 100,
    pageNo: int = 1
) -> Dict[str, Any]:
    """
    건축물대장 기본개요(getBrBasisOulnInfo) 정보를 조회합니다.
    PNU 19자리 또는 개별 행정코드를 입력받아 건물의 기본 개요 및 위치 코드를 제공합니다.

    반환하는 주요 필드:
    - mgmBldrgstPk: 관리건축물대장PK (건물 식별 키)
    - platPlc: 대지위치
    - newPlatPlc: 도로명대지위치
    - bldNm: 건물명
    - sigunguCd / bjdongCd: 시군구코드 / 법정동코드
    - platGbCd: 대지구분코드
    - regstrGbCdNm / regstrKindCdNm: 대장구분코드명 / 대장종류코드명
    """
    try:
        s_cd, b_cd, p_cd, b_val, j_val = parse_pnu(pnu, sigunguCd, bjdongCd, platGbCd, bun, ji)
    except ValueError as e:
        return {"status": "ERROR", "message": str(e)}
        
    return await fetch_building_ledger_data(
        "getBrBasisOulnInfo", s_cd, b_cd, p_cd, b_val, j_val, numOfRows, pageNo
    )

async def br_get_recap_title(
    pnu: Optional[str] = None,
    sigunguCd: Optional[str] = None,
    bjdongCd: Optional[str] = None,
    platGbCd: Optional[str] = None,
    bun: Optional[str] = None,
    ji: Optional[str] = None,
    numOfRows: int = 100,
    pageNo: int = 1
) -> Dict[str, Any]:
    """
    건축물대장 총괄표제부(getBrRecapTitleInfo) 정보를 조회합니다.
    한 대지 내에 여러 동의 건물이 있는 경우 대지 전체의 현황 및 각 건물들의 총괄 내역을 조회합니다.

    반환하는 주요 필드:
    - platArea: 대지면적
    - archArea: 건축면적
    - totArea: 연면적
    - bcRat / vlRat: 건폐율 / 용적률
    - mainPurpsCdNm: 주용도코드명
    - mainBldCnt: 주건축물수
    - totPkngCnt: 총주차수
    """
    try:
        s_cd, b_cd, p_cd, b_val, j_val = parse_pnu(pnu, sigunguCd, bjdongCd, platGbCd, bun, ji)
    except ValueError as e:
        return {"status": "ERROR", "message": str(e)}
        
    return await fetch_building_ledger_data(
        "getBrRecapTitleInfo", s_cd, b_cd, p_cd, b_val, j_val, numOfRows, pageNo
    )

async def br_get_title(
    pnu: Optional[str] = None,
    dongNm: Optional[str] = None,
    sigunguCd: Optional[str] = None,
    bjdongCd: Optional[str] = None,
    platGbCd: Optional[str] = None,
    bun: Optional[str] = None,
    ji: Optional[str] = None,
    numOfRows: int = 100,
    pageNo: int = 1
) -> Dict[str, Any]:
    """
    건축물대장 표제부(getBrTitleInfo) 정보를 조회합니다.
    동별 건물의 이름, 주용도, 구조, 층수, 건폐율/용적률 및 내진설계적용 여부 등을 조회할 수 있습니다.
    
    추가 조회인자:
    - dongNm: 동 명칭 (예: '101동')

    반환하는 주요 필드:
    - bldNm: 건물명
    - dongNm: 동명칭
    - grndFlrCnt / ugrndFlrCnt: 지상층수 / 지하층수
    - mainPurpsCdNm: 주용도코드명
    - strctCdNm: 구조코드명
    - platArea / archArea / totArea: 대지면적 / 건축면적 / 연면적
    - bcRat / vlRat: 건폐율 / 용적률
    - rserthqkDsgnApplyYn / rserthqkAblty: 내진설계적용여부 / 내진능력
    """
    try:
        s_cd, b_cd, p_cd, b_val, j_val = parse_pnu(pnu, sigunguCd, bjdongCd, platGbCd, bun, ji)
    except ValueError as e:
        return {"status": "ERROR", "message": str(e)}
        
    extra = {"dongNm": dongNm} if dongNm else None
    return await fetch_building_ledger_data(
        "getBrTitleInfo", s_cd, b_cd, p_cd, b_val, j_val, numOfRows, pageNo, extra
    )

async def br_get_floor_ouln(
    pnu: Optional[str] = None,
    dongNm: Optional[str] = None,
    flrGbCd: Optional[str] = None,
    flrNo: Optional[str] = None,
    sigunguCd: Optional[str] = None,
    bjdongCd: Optional[str] = None,
    platGbCd: Optional[str] = None,
    bun: Optional[str] = None,
    ji: Optional[str] = None,
    numOfRows: int = 100,
    pageNo: int = 1
) -> Dict[str, Any]:
    """
    건축물대장 층별개요(getBrFlrOulnInfo) 정보를 조회합니다.
    건물의 각 층별 면적, 주요 용도, 구조 등을 조회합니다.

    추가 조회인자:
    - dongNm: 동 명칭 (예: '101동')
    - flrGbCd: 층구분코드
    - flrNo: 층번호 (예: '1')

    반환하는 주요 필드:
    - dongNm: 동명칭
    - flrNoNm: 층번호명
    - area: 면적
    - mainPurpsCdNm: 주용도코드명
    - strctCdNm: 구조코드명
    """
    try:
        s_cd, b_cd, p_cd, b_val, j_val = parse_pnu(pnu, sigunguCd, bjdongCd, platGbCd, bun, ji)
    except ValueError as e:
        return {"status": "ERROR", "message": str(e)}
        
    extra = {}
    if dongNm: extra["dongNm"] = dongNm
    if flrGbCd: extra["flrGbCd"] = flrGbCd
    if flrNo: extra["flrNo"] = flrNo
    
    return await fetch_building_ledger_data(
        "getBrFlrOulnInfo", s_cd, b_cd, p_cd, b_val, j_val, numOfRows, pageNo, extra or None
    )

async def br_get_atch_jibun(
    pnu: Optional[str] = None,
    sigunguCd: Optional[str] = None,
    bjdongCd: Optional[str] = None,
    platGbCd: Optional[str] = None,
    bun: Optional[str] = None,
    ji: Optional[str] = None,
    numOfRows: int = 100,
    pageNo: int = 1
) -> Dict[str, Any]:
    """
    건축물대장 부속지번(getBrAtchJibunInfo) 정보를 조회합니다.
    건축물이 위치한 대표 지번 외의 부속 지번(관련 지번)에 대한 매핑 정보를 제공합니다.

    반환하는 주요 필드:
    - atchSigunguCd / atchBjdongCd: 부속지번의 시군구코드 / 법정동코드
    - atchBun / atchJi: 부속지번의 본번 / 부번
    - atchPlatGbCd: 부속지번의 대지구분코드
    """
    try:
        s_cd, b_cd, p_cd, b_val, j_val = parse_pnu(pnu, sigunguCd, bjdongCd, platGbCd, bun, ji)
    except ValueError as e:
        return {"status": "ERROR", "message": str(e)}
        
    return await fetch_building_ledger_data(
        "getBrAtchJibunInfo", s_cd, b_cd, p_cd, b_val, j_val, numOfRows, pageNo
    )

async def br_get_expos_pubuse_area(
    pnu: Optional[str] = None,
    dongNm: Optional[str] = None,
    hoNm: Optional[str] = None,
    sigunguCd: Optional[str] = None,
    bjdongCd: Optional[str] = None,
    platGbCd: Optional[str] = None,
    bun: Optional[str] = None,
    ji: Optional[str] = None,
    numOfRows: int = 100,
    pageNo: int = 1
) -> Dict[str, Any]:
    """
    건축물대장 전유공용면적(getBrExposPubuseAreaInfo) 정보를 조회합니다.
    집합건축물의 각 호별 전유부(전용면적)와 공용부(공동면적) 정보를 제공합니다.

    추가 조회인자:
    - dongNm: 동 명칭 (예: '101동')
    - hoNm: 호 명칭 (예: '101호')

    반환하는 주요 필드:
    - dongNm: 동명칭
    - hoNm: 호명칭
    - flrNoNm: 층번호명
    - exposPubuseGbCdNm: 전유공용구분명 (예: 전유, 공용)
    - area: 면적
    - mainPurpsCdNm: 주용도코드명
    """
    try:
        s_cd, b_cd, p_cd, b_val, j_val = parse_pnu(pnu, sigunguCd, bjdongCd, platGbCd, bun, ji)
    except ValueError as e:
        return {"status": "ERROR", "message": str(e)}
        
    extra = {}
    if dongNm: extra["dongNm"] = dongNm
    if hoNm: extra["hoNm"] = hoNm
    
    return await fetch_building_ledger_data(
        "getBrExposPubuseAreaInfo", s_cd, b_cd, p_cd, b_val, j_val, numOfRows, pageNo, extra or None
    )

async def br_get_wclf(
    pnu: Optional[str] = None,
    sigunguCd: Optional[str] = None,
    bjdongCd: Optional[str] = None,
    platGbCd: Optional[str] = None,
    bun: Optional[str] = None,
    ji: Optional[str] = None,
    numOfRows: int = 100,
    pageNo: int = 1
) -> Dict[str, Any]:
    """
    건축물대장 오수정화시설(getBrWclfInfo) 정보를 조회합니다.
    건축물 내 설치된 정화조 및 오수처리시설의 종류, 용량(루베/인용) 등의 규격을 조회합니다.

    반환하는 주요 필드:
    - modeCdNm: 오수정화시설 형식코드명
    - capaLube / capaPsper: 용량(루베) / 용량(인용)
    - unitGbCdNm: 단위구분코드명
    """
    try:
        s_cd, b_cd, p_cd, b_val, j_val = parse_pnu(pnu, sigunguCd, bjdongCd, platGbCd, bun, ji)
    except ValueError as e:
        return {"status": "ERROR", "message": str(e)}
        
    return await fetch_building_ledger_data(
        "getBrWclfInfo", s_cd, b_cd, p_cd, b_val, j_val, numOfRows, pageNo
    )

async def br_get_house_price(
    pnu: Optional[str] = None,
    sigunguCd: Optional[str] = None,
    bjdongCd: Optional[str] = None,
    platGbCd: Optional[str] = None,
    bun: Optional[str] = None,
    ji: Optional[str] = None,
    numOfRows: int = 100,
    pageNo: int = 1
) -> Dict[str, Any]:
    """
    건축물대장 공동주택가격(getBrHsprcInfo) 정보를 조회합니다.
    해당 필지에 공시된 공동주택(아파트, 빌라 등)의 공시가격을 조회합니다.

    반환하는 주요 필드:
    - hsprc: 공시주택가격 (원)
    - bylotCnt: 외필지수
    - crtnDay: 공시생성일자
    """
    try:
        s_cd, b_cd, p_cd, b_val, j_val = parse_pnu(pnu, sigunguCd, bjdongCd, platGbCd, bun, ji)
    except ValueError as e:
        return {"status": "ERROR", "message": str(e)}
        
    return await fetch_building_ledger_data(
        "getBrHsprcInfo", s_cd, b_cd, p_cd, b_val, j_val, numOfRows, pageNo
    )

async def br_get_expos(
    pnu: Optional[str] = None,
    dongNm: Optional[str] = None,
    hoNm: Optional[str] = None,
    sigunguCd: Optional[str] = None,
    bjdongCd: Optional[str] = None,
    platGbCd: Optional[str] = None,
    bun: Optional[str] = None,
    ji: Optional[str] = None,
    numOfRows: int = 100,
    pageNo: int = 1
) -> Dict[str, Any]:
    """
    건축물대장 전유부(getBrExposInfo) 정보를 조회합니다.
    집합건축물의 호별개요 및 층, 호 정보를 조회할 때 사용합니다.

    추가 조회인자:
    - dongNm: 동 명칭 (예: '101동')
    - hoNm: 호 명칭 (예: '101호')

    반환하는 주요 필드:
    - dongNm: 동명칭
    - flrNo: 층번호
    - hoNm: 호명칭
    - mgmBldrgstPk: 관리건축물대장PK
    """
    try:
        s_cd, b_cd, p_cd, b_val, j_val = parse_pnu(pnu, sigunguCd, bjdongCd, platGbCd, bun, ji)
    except ValueError as e:
        return {"status": "ERROR", "message": str(e)}
        
    extra = {}
    if dongNm: extra["dongNm"] = dongNm
    if hoNm: extra["hoNm"] = hoNm
    
    return await fetch_building_ledger_data(
        "getBrExposInfo", s_cd, b_cd, p_cd, b_val, j_val, numOfRows, pageNo, extra or None
    )

async def br_get_jijigu(
    pnu: Optional[str] = None,
    sigunguCd: Optional[str] = None,
    bjdongCd: Optional[str] = None,
    platGbCd: Optional[str] = None,
    bun: Optional[str] = None,
    ji: Optional[str] = None,
    numOfRows: int = 100,
    pageNo: int = 1
) -> Dict[str, Any]:
    """
    건축물대장 지역지구구역(getBrJijiguInfo) 정보를 조회합니다.
    건축물 및 토지에 지정된 도시지역, 제3종일반주거지역 등 용도지역, 용도지구, 용도구역을 조회합니다.

    반환하는 주요 필드:
    - jijiguCdNm: 지역지구구역코드명 (예: 일반상업지역, 역사문화환경보존지역 등)
    - jijiguGbCdNm: 지역지구구역구분명 (예: 국토계획법, 건축법, 기타)
    - reprYn: 대표지정 여부
    """
    try:
        s_cd, b_cd, p_cd, b_val, j_val = parse_pnu(pnu, sigunguCd, bjdongCd, platGbCd, bun, ji)
    except ValueError as e:
        return {"status": "ERROR", "message": str(e)}
        
    return await fetch_building_ledger_data(
        "getBrJijiguInfo", s_cd, b_cd, p_cd, b_val, j_val, numOfRows, pageNo
    )

async def _bldrgst_health() -> Dict[str, Any]:
    """
    (internal, was `br_health_check`) 인증키/네트워크/응답 연결성 진단 도구.
    가벼운 샘플 요청(서울 강남구 역삼동 대장 조회)을 보내 HTTP 상태, 소요시간, 본문 프리뷰를 반환합니다.
    """
    # Sample PNU: 1168010100108220002 (서울 강남구 역삼동 822-2)
    sigunguCd = "11680"
    bjdongCd = "10100"
    platGbCd = "0"
    bun = "0822"
    ji = "0002"
    
    start_time = time.time()
    try:
        api_key = get_service_key()
    except Exception as e:
        return {
            "status": "ERROR",
            "message": f"Configuration error: {sanitize_error(str(e))}"
        }
        
    params = {
        "serviceKey": api_key,
        "sigunguCd": sigunguCd,
        "bjdongCd": bjdongCd,
        "platGbCd": platGbCd,
        "bun": bun,
        "ji": ji,
        "numOfRows": "1",
        "pageNo": "1",
        "_type": "json"
    }
    
    async with get_http_client() as client:
        url = f"{BASE_URL}/getBrBasisOulnInfo"
        try:
            response = await client.get(url, params=params)
            elapsed = round(time.time() - start_time, 3)
            status_code = response.status_code
            
            preview = response.text[:300]
            result = parse_api_response(response)
            
            return {
                "status": "OK" if result.get("status") in ["OK", "NOT_FOUND"] else "ERROR",
                "http_status_code": status_code,
                "elapsed_seconds": elapsed,
                "api_response_status": result.get("status"),
                "api_response_message": result.get("message"),
                "response_preview": sanitize_error(preview),
                "message": "Connection diagnostic completed."
            }
        except Exception as e:
            elapsed = round(time.time() - start_time, 3)
            return {
                "status": "NETWORK_ERROR",
                "elapsed_seconds": elapsed,
                "message": f"Connectivity check failed: {sanitize_error(str(e))}"
            }


TOOLS = (
    br_get_basis_ouln,
    br_get_recap_title,
    br_get_title,
    br_get_floor_ouln,
    br_get_atch_jibun,
    br_get_expos_pubuse_area,
    br_get_wclf,
    br_get_house_price,
    br_get_expos,
    br_get_jijigu,
)


def register(mcp: FastMCP) -> None:
    for fn in TOOLS:
        mcp.tool()(fn)
