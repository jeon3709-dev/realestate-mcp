"""합성 API 응답 픽스처.

주의: 실제 API 응답을 캡처한 것이 아니다. 원본 서버 코드(vworld-mcp / BDLedger_MCP /
LandPrice_MCP)가 읽는 필드명만으로 구성한 합성 데이터이며, 인증키를 포함하지 않는다.
"""
from typing import Any, Dict, List, Optional

PNU = "1168010100108220002"  # 서울특별시 강남구 역삼동 822-2

PARCEL_GEOMETRY = {
    "type": "MultiPolygon",
    "coordinates": [[[
        [127.0360, 37.5000],
        [127.0362, 37.5000],
        [127.0362, 37.5002],
        [127.0360, 37.5002],
    ]]],
}


def vworld_parcel(pnu: str = PNU) -> Dict[str, Any]:
    return {
        "response": {
            "status": "OK",
            "result": {
                "featureCollection": {
                    "type": "FeatureCollection",
                    "features": [{
                        "type": "Feature",
                        "geometry": PARCEL_GEOMETRY,
                        "properties": {"pnu": pnu},
                    }],
                }
            },
        }
    }


def vworld_status(status: str, code: str = "", text: str = "") -> Dict[str, Any]:
    body: Dict[str, Any] = {"status": status}
    if status == "ERROR":
        body["error"] = {"code": code, "text": text}
    return {"response": body}


def vworld_geocode(lon: float = 127.0361, lat: float = 37.5001, refined: str = "서울특별시 강남구 역삼동 822-2") -> Dict[str, Any]:
    return {
        "response": {
            "status": "OK",
            "refined": {"text": refined},
            "result": {"point": {"x": str(lon), "y": str(lat)}},
        }
    }


def vworld_reverse(parcel_text: str = "서울특별시 강남구 역삼동 822-2", road_text: str = "서울특별시 강남구 테헤란로 000") -> Dict[str, Any]:
    return {
        "response": {
            "status": "OK",
            "result": [
                {"type": "parcel", "text": parcel_text, "structure": {}},
                {"type": "road", "text": road_text, "structure": {}},
            ],
        }
    }


def wfs_features(features: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": p} for p in features]}


def ned_price(price: str = "50000000", area: str = "1000", jimok: str = "대") -> Dict[str, Any]:
    return {
        "landCharacteristicss": {
            "field": [{
                "pblntfPclnd": price,
                "lndpclAr": area,
                "lndcgrCodeNm": jimok,
                "ladUseSittnNm": "업무용",
            }]
        }
    }


def br_json(items: Optional[List[Dict[str, Any]]], result_code: str = "00") -> Dict[str, Any]:
    body: Dict[str, Any] = {}
    if items is not None:
        body = {"items": {"item": items if len(items) != 1 else items[0]}, "totalCount": str(len(items))}
    return {"response": {"header": {"resultCode": result_code, "resultMsg": "NORMAL SERVICE."}, "body": body}}


BR_AUTH_ERROR_XML = (
    "<OpenAPI_ServiceResponse><cmmMsgHeader><errMsg>SERVICE ERROR</errMsg>"
    "<returnAuthMsg>SERVICE_KEY_IS_NOT_REGISTERED_ERROR</returnAuthMsg>"
    "<returnReasonCode>30</returnReasonCode></cmmMsgHeader></OpenAPI_ServiceResponse>"
)


def rtms_xml(items: List[Dict[str, Any]], total: Optional[int] = None, num_rows: int = 100, result_code: str = "000") -> str:
    parts = []
    for it in items:
        parts.append("<item>" + "".join(f"<{k}>{v}</{k}>" for k, v in it.items()) + "</item>")
    total = len(items) if total is None else total
    return (
        '<?xml version="1.0" encoding="UTF-8"?><response>'
        f"<header><resultCode>{result_code}</resultCode><resultMsg>OK</resultMsg></header>"
        f"<body><items>{''.join(parts)}</items><numOfRows>{num_rows}</numOfRows>"
        f"<pageNo>1</pageNo><totalCount>{total}</totalCount></body></response>"
    )


RTMS_AUTH_ERROR_XML = (
    "<OpenAPI_ServiceResponse><cmmMsgHeader><errMsg>SERVICE ERROR</errMsg>"
    "<returnAuthMsg>SERVICE_KEY_IS_NOT_REGISTERED_ERROR</returnAuthMsg></cmmMsgHeader></OpenAPI_ServiceResponse>"
)


def land_item(umd: str, jibun: str, amount: str, area: str, y: str, m: str, d: str, **extra: str) -> Dict[str, str]:
    item = {
        "umdNm": umd, "jibun": jibun, "dealAmount": amount, "dealArea": area,
        "dealYear": y, "dealMonth": m, "dealDay": d, "jimok": "대", "landUse": "일반상업지역",
    }
    item.update(extra)
    return item


def nrg_item(umd: str, jibun: str, amount: str, plottage: str, building: str, y: str, m: str, d: str, **extra: str) -> Dict[str, str]:
    item = {
        "umdNm": umd, "jibun": jibun, "dealAmount": amount, "plottageAr": plottage, "buildingAr": building,
        "dealYear": y, "dealMonth": m, "dealDay": d, "buildingUse": "업무", "buildingType": "일반",
    }
    item.update(extra)
    return item
