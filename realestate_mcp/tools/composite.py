"""통합 도구: site_profile (PNU 기준 3개 API 동시 조회) + health_check (3개 API 동시 점검).

원칙
- 원본 도구 함수(vworld_* / br_* / rtms_*)를 그대로 호출해 재사용한다.
- 섹션별 부분 실패를 허용한다: 각 섹션은 status(OK / NOT_FOUND / ERROR / SKIPPED)와 message 를 가진다.
- 요약 값은 원본 응답에서 확인된 필드만 사용하고, 값이 없으면 null 로 둔다(추정·대체값 없음).
  단위 환산(㎡→평 = ×0.3025, 원/㎡→원/평 = ÷0.3025)만 수행한다(원본 calc_price_per_pyung 과 동일 계수).
"""
import asyncio
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Dict, List, Literal, Optional, Tuple

from mcp.server.fastmcp import FastMCP

from .. import config
from ..common import sanitize_error
from ..pnu import normalize_pnu, split_pnu
from . import bldrgst, rtms, vworld

logger = logging.getLogger("realestate-mcp")

KST = timezone(timedelta(hours=9))
PYUNG_PER_M2 = 0.3025  # 원본 LandPrice_MCP calc_price_per_pyung 과 동일
RECENT_TX_LIMIT = 10
DISCLAIMER = "공공 API 원자료 기준이며 등기부·현장 확인이 필요함"

# 도로명 주소 패턴("테헤란로 152", "강남대로84길 23"). 일치하면 도로명 먼저, 아니면 지번 먼저 지오코딩.
ROAD_ADDRESS_RE = re.compile(r"(로|길)\s*\d")

TransactionType = Literal["land", "commercial", "apartment"]

TX_CONFIG: Dict[str, Dict[str, Any]] = {
    "land": {
        "label": "토지",
        "asset_type": "토지",
        "endpoint": rtms.ENDPOINTS["land"],
        "tool": rtms.rtms_search_land_transactions,
    },
    "commercial": {
        "label": "상업업무용",
        "asset_type": "상업업무용",
        "endpoint": rtms.ENDPOINTS["commercial"],
        "tool": rtms.rtms_search_commercial_transactions,
    },
    "apartment": {
        "label": "아파트",
        "asset_type": "아파트(상세)",
        "endpoint": rtms.ENDPOINTS["apartment"],
        "tool": rtms.rtms_search_apartment_transactions,
    },
}

# 건축물대장에서 요약·섹션에 쓰는 필드 (원본 BDLedger_MCP docstring 에 명시된 필드만)
RECAP_FIELDS = ("platArea", "archArea", "totArea", "bcRat", "vlRat", "mainPurpsCdNm", "mainBldCnt", "totPkngCnt")
TITLE_FIELDS = (
    "bldNm", "dongNm", "grndFlrCnt", "ugrndFlrCnt", "mainPurpsCdNm", "strctCdNm",
    "platArea", "archArea", "totArea", "bcRat", "vlRat", "rserthqkDsgnApplyYn", "rserthqkAblty",
    "useAprDay",  # 사용승인일: docstring 에는 없으나 2026-09-30 실응답(getBrTitleInfo)으로 확인
)
JIJIGU_FIELDS = ("jijiguCdNm", "jijiguGbCdNm", "reprYn")


# --- Small helpers ---

def _now_iso() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


def _to_float(val: Any) -> Optional[float]:
    if val is None or isinstance(val, bool):
        return None
    if isinstance(val, (int, float)):
        return float(val)
    text = str(val).replace(",", "").strip()
    if not text or text.lower() in ("nan", "none", "null"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _to_int(val: Any) -> Optional[int]:
    f = _to_float(val)
    return int(f) if f is not None else None


def _fmt_yyyymmdd(val: Any) -> Optional[str]:
    """'19920117' → '1992-01-17'. 빈 값(공백 포함)은 None, 형식이 다르면 원문 그대로."""
    if val is None:
        return None
    text = str(val).strip()
    if not text:
        return None
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return text


def _m2_to_pyung(m2: Optional[float]) -> Optional[float]:
    return round(m2 * PYUNG_PER_M2, 2) if m2 is not None else None


def _per_m2_to_per_pyung(price_per_m2: Optional[float]) -> Optional[int]:
    return round(price_per_m2 / PYUNG_PER_M2) if price_per_m2 is not None else None


def _section_status(raw_status: Optional[str]) -> str:
    """Map original tool statuses onto OK / NOT_FOUND / ERROR."""
    if raw_status == "OK":
        return "OK"
    if raw_status in ("NOT_FOUND", "NO_DATA"):
        return "NOT_FOUND"
    return "ERROR"


def _combine_status(statuses: List[str]) -> str:
    if not statuses:
        return "SKIPPED"
    if any(s == "OK" for s in statuses):
        return "OK"
    if any(s == "ERROR" for s in statuses):
        return "ERROR"
    return "NOT_FOUND"


def _skipped(message: str) -> Dict[str, Any]:
    return {"status": "SKIPPED", "message": message, "data": None}


async def _safe(coro: Awaitable[Dict[str, Any]]) -> Dict[str, Any]:
    """Run a tool coroutine; convert raised exceptions (e.g. missing VWORLD_API_KEY) into ERROR dicts."""
    try:
        return await coro
    except Exception as e:
        logger.error(f"site_profile sub-call failed: {sanitize_error(str(e))}")
        return {"status": "ERROR", "message": sanitize_error(str(e))}


def _pick(record: Dict[str, Any], fields: Tuple[str, ...]) -> Dict[str, Any]:
    return {f: record.get(f) for f in fields}


def _fmt_num(val: Optional[float], digits: int = 2) -> str:
    if val is None:
        return "N/A"
    if float(val).is_integer():
        return f"{int(val):,}"
    return f"{val:,.{digits}f}"


# --- Step 1: address → PNU ---

async def _resolve_address(address: str) -> Dict[str, Any]:
    """Geocode (road/parcel) → parcel by point → PNU."""
    order: List[Literal["road", "parcel"]] = (
        ["road", "parcel"] if ROAD_ADDRESS_RE.search(address) else ["parcel", "road"]
    )
    attempts: List[Dict[str, Any]] = []
    geo: Optional[Dict[str, Any]] = None
    for address_type in order:
        res = await _safe(vworld.vworld_geocode(address, address_type))
        attempts.append({"address_type": address_type, "status": res.get("status"), "message": res.get("message")})
        coords = res.get("coordinates") or {}
        if res.get("status") == "OK" and coords.get("lat") is not None and coords.get("lon") is not None:
            geo = res
            geo["address_type"] = address_type
            break

    if geo is None:
        status = "NOT_FOUND" if all(a["status"] == "NOT_FOUND" for a in attempts) else "ERROR"
        return {
            "status": status,
            "message": "Address could not be geocoded (tried: " + ", ".join(
                f"{a['address_type']}={a['status']}" for a in attempts) + ").",
            "attempts": attempts,
        }

    coords = geo["coordinates"]
    parcel = await _safe(vworld.vworld_find_parcel_by_point(coords["lat"], coords["lon"]))
    if parcel.get("status") != "OK":
        return {
            "status": _section_status(parcel.get("status")),
            "message": f"Geocoded, but no parcel (PNU) found at the coordinates: {parcel.get('message')}",
            "attempts": attempts,
            "coordinates": coords,
        }
    return {
        "status": "OK",
        "pnu": parcel["pnu"],
        "coordinates": coords,
        "refined_address": geo.get("address"),
        "address_type": geo["address_type"],
        "attempts": attempts,
    }


# --- Step 2: sections ---

async def _parcel_with_address(pnu: str) -> Dict[str, Any]:
    """vworld_get_parcel → centroid → vworld_reverse_geocode (지번·도로명 주소)."""
    parcel = await _safe(vworld.vworld_get_parcel(pnu))
    if parcel.get("status") != "OK":
        return {"parcel": parcel, "centroid": None, "reverse": None}
    centroid: Optional[Dict[str, float]] = None
    reverse: Optional[Dict[str, Any]] = None
    try:
        lat, lon = vworld.calculate_centroid(parcel.get("geometry") or {})
        centroid = {"lat": lat, "lon": lon}
        reverse = await _safe(vworld.vworld_reverse_geocode(lat, lon))
    except Exception as e:
        reverse = {"status": "ERROR", "message": f"Centroid calculation failed: {sanitize_error(str(e))}"}
    return {"parcel": parcel, "centroid": centroid, "reverse": reverse}


def _build_parcel_section(pnu: str, parcel_bundle: Dict[str, Any], bdong: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    parcel = parcel_bundle["parcel"]
    reverse = parcel_bundle.get("reverse") or {}
    parts = split_pnu(pnu)

    props = parcel.get("properties") or {}
    jibun_address = None
    if bdong:
        jibun_address = " ".join(
            p for p in (bdong.get("sido"), bdong.get("sigungu"), bdong.get("dong"), bdong.get("ri"), parts.jibun) if p
        )
    elif props.get("addr"):
        # 법정동코드 DB 에 없을 때만 연속지적도 속성 addr 사용 (실응답으로 확인된 필드)
        jibun_address = props.get("addr")

    road_address = None
    parcel_address_vworld = None
    if reverse.get("status") == "OK":
        for a in reverse.get("addresses", []):
            if a.get("type") == "road" and not road_address:
                road_address = a.get("text")
            if a.get("type") == "parcel" and not parcel_address_vworld:
                parcel_address_vworld = a.get("text")

    status = _section_status(parcel.get("status"))
    message = parcel.get("message") or ("OK" if status == "OK" else "")
    if status == "OK" and reverse and reverse.get("status") != "OK":
        message = f"필지 조회 OK, 역지오코딩 {reverse.get('status')}: {reverse.get('message')}"

    return {
        "status": status,
        "message": message,
        "data": {
            "pnu": pnu,
            "legal_dong_code": parts.bdong_cd,
            "legal_dong": bdong,
            "jibun": parts.jibun,
            "jibun_address": jibun_address,
            "road_address": road_address,
            "parcel_address_vworld": parcel_address_vworld,
            "cadastral_addr": props.get("addr"),
            "cadastral_gosi_year_month": (
                f"{props.get('gosi_year')}-{props.get('gosi_month')}"
                if props.get("gosi_year") and props.get("gosi_month") else None
            ),
            "centroid": parcel_bundle.get("centroid"),
            "properties": parcel.get("properties") if status == "OK" else None,
        },
    }


def _build_landuse_section(res: Dict[str, Any]) -> Dict[str, Any]:
    status = _section_status(res.get("status"))
    zones = []
    if status == "OK":
        for z in res.get("zoning_info", []):
            zones.append({k: z.get(k) for k in ("layer_id", "layer_type", "code", "name")})
        if not zones:
            status = "NOT_FOUND"
    return {
        "status": status,
        "message": res.get("message") or ("OK" if status == "OK" else "No land use zone features at the parcel centroid."),
        "data": {
            "zones": zones,
            "queried_coordinates": res.get("queried_coordinates"),
        } if res.get("status") == "OK" else None,
    }


def _build_land_price_section(res: Dict[str, Any]) -> Dict[str, Any]:
    status = _section_status(res.get("status"))
    data = None
    if status == "OK":
        price = _to_float(res.get("individual_public_price"))
        area = _to_float(res.get("land_area"))
        data = {
            "year": res.get("year"),
            "price_per_m2": _to_int(price),
            "price_per_pyung": _per_m2_to_per_pyung(price),
            "land_area_m2": area,
            "land_area_pyung": _m2_to_pyung(area),
            "jimok": res.get("ji_mok"),
            "land_use_status": res.get("land_use_status"),
        }
    return {"status": status, "message": res.get("message") or "OK", "data": data}


def _build_building_section(recap: Dict[str, Any], title: Dict[str, Any], jijigu: Dict[str, Any]) -> Dict[str, Any]:
    sub = {
        "recap_title": _section_status(recap.get("status")),
        "title": _section_status(title.get("status")),
        "jijigu": _section_status(jijigu.get("status")),
    }
    messages = {
        "recap_title": recap.get("message") or recap.get("status"),
        "title": title.get("message") or title.get("status"),
        "jijigu": jijigu.get("message") or jijigu.get("status"),
    }
    recap_records = recap.get("results", []) if sub["recap_title"] == "OK" else []
    title_records = title.get("results", []) if sub["title"] == "OK" else []
    jijigu_records = jijigu.get("results", []) if sub["jijigu"] == "OK" else []

    status = _combine_status(list(sub.values()))
    message = "; ".join(f"{k}: {v}" for k, v in messages.items() if sub[k] != "OK") or "OK"
    return {
        "status": status,
        "message": message,
        "data": {
            "sub_status": sub,
            "recap_title": [_pick(r, RECAP_FIELDS) for r in recap_records],
            "titles": [_pick(r, TITLE_FIELDS) for r in title_records],
            "title_total_count": title.get("totalCount") if sub["title"] == "OK" else 0,
            "jijigu": [_pick(r, JIJIGU_FIELDS) for r in jijigu_records],
        },
    }


def _build_transaction_entry(tx_type: str, res: Dict[str, Any], lawd_cd: str, dong: Optional[str], months: List[str]) -> Dict[str, Any]:
    cfg = TX_CONFIG[tx_type]
    status = _section_status(res.get("status"))
    summary = res.get("summary") or {}
    records = res.get("transactions") or []

    medians: Dict[str, Optional[float]] = {}
    if tx_type == "commercial":
        land_stats = summary.get("land_price_stats") or {}
        bld_stats = summary.get("building_price_stats") or {}
        medians["median_land_price_per_pyung"] = land_stats.get("median") or None
        medians["median_building_price_per_pyung"] = bld_stats.get("median") or None
    else:
        stats = summary.get("price_stats") or {}
        medians["median_price_per_pyung"] = stats.get("median") or None

    summary_md = None
    if status == "OK" and records:
        _, summary_md = rtms.create_summary_block(records, summary.get("filter_details", ""), cfg["asset_type"])

    return {
        "status": status,
        "message": "OK" if status == "OK" else (res.get("message") or ""),
        "label": cfg["label"],
        "lawd_cd": lawd_cd,
        "dong_filter": dong,
        "deal_ymd_range": f"{months[-1]}~{months[0]}" if months else None,
        "period": summary.get("period"),
        "total_count": summary.get("total_count", 0 if status != "ERROR" else None),
        "valid_count": summary.get("valid_count", 0 if status != "ERROR" else None),
        **medians,
        "unit": "만원/평",
        "summary_markdown": summary_md,
        "recent_transactions": records[:RECENT_TX_LIMIT],
    }


# --- Summary ---

def _building_basis(building: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Optional[str], Optional[Dict[str, Any]]]:
    """Return (area/ratio source record, basis label, single title record or None)."""
    data = building.get("data") or {}
    recaps = data.get("recap_title") or []
    titles = data.get("titles") or []
    single_title = titles[0] if len(titles) == 1 else None
    if recaps:
        return recaps[0], "총괄표제부", single_title
    if single_title:
        return single_title, "표제부(단일 동)", single_title
    return None, None, None


def _build_summary(sections: Dict[str, Any], tx_types: List[str]) -> Dict[str, Any]:
    price = (sections["land_price"].get("data") or {})
    landuse = (sections["landuse"].get("data") or {})
    building = sections["building"]
    bdata = building.get("data") or {}
    basis_rec, basis_label, single_title = _building_basis(building)

    zoning = []
    for z in landuse.get("zones", []):
        if z.get("name") and z["name"] not in zoning:
            zoning.append(z["name"])
    districts = []
    for j in bdata.get("jijigu", []):
        name = j.get("jijiguCdNm")
        if name and name not in districts:
            districts.append(name)

    ledger_plat = _to_float(basis_rec.get("platArea")) if basis_rec else None
    tot_area = _to_float(basis_rec.get("totArea")) if basis_rec else None

    tx_summary: Dict[str, Any] = {}
    tx_section = sections["transactions"]
    for t in tx_types:
        entry = (tx_section.get("data") or {}).get(t)
        if not entry:
            continue
        item = {"status": entry["status"], "valid_count": entry.get("valid_count")}
        for k in ("median_price_per_pyung", "median_land_price_per_pyung", "median_building_price_per_pyung"):
            if k in entry:
                item[k] = entry[k]
        tx_summary[t] = item

    indicators = {
        "land_area_m2": price.get("land_area_m2"),
        "land_area_pyung": price.get("land_area_pyung"),
        "ledger_plat_area_m2": ledger_plat,
        "ledger_plat_area_pyung": _m2_to_pyung(ledger_plat),
        "jimok": price.get("jimok"),
        "zoning": zoning or None,
        "zoning_districts": districts or None,
        "land_price_per_m2": price.get("price_per_m2"),
        "land_price_per_pyung": price.get("price_per_pyung"),
        "land_price_year": price.get("year"),
        "main_purpose": basis_rec.get("mainPurpsCdNm") if basis_rec else None,
        "total_floor_area_m2": tot_area,
        "total_floor_area_pyung": _m2_to_pyung(tot_area),
        "building_coverage_ratio": _to_float(basis_rec.get("bcRat")) if basis_rec else None,
        "floor_area_ratio": _to_float(basis_rec.get("vlRat")) if basis_rec else None,
        "ground_floors": _to_int(single_title.get("grndFlrCnt")) if single_title else None,
        "underground_floors": _to_int(single_title.get("ugrndFlrCnt")) if single_title else None,
        "use_approval_date": _fmt_yyyymmdd(single_title.get("useAprDay")) if single_title else None,
        "building_count": _to_int(bdata["recap_title"][0].get("mainBldCnt")) if bdata.get("recap_title") else None,
        "building_basis": basis_label,
        "transactions": tx_summary,
    }
    return indicators


def _render_markdown(result: Dict[str, Any], indicators: Dict[str, Any]) -> str:
    sections = result["sections"]
    parcel = sections["parcel"].get("data") or {}
    coords = result.get("coordinates") or {}

    def val(v: Any, suffix: str = "") -> str:
        if v is None:
            return "N/A"
        if isinstance(v, (int, float)):
            return f"{_fmt_num(float(v))}{suffix}"
        return f"{v}{suffix}"

    md = f"## 📍 부지 종합 프로파일 (PNU {result['pnu']})\n\n"
    md += f"- **지번 주소**: {val(result['address'].get('jibun'))}\n"
    md += f"- **도로명 주소**: {val(result['address'].get('road'))}\n"
    if coords.get("lat") is not None:
        md += f"- **좌표**: {coords['lat']:.6f}, {coords['lon']:.6f} ({coords.get('source')})\n"
    md += "\n### 📊 핵심 지표\n"
    md += "| 구분 | 값 | 출처 |\n| :--- | :--- | :--- |\n"

    area = "N/A" if indicators["land_area_m2"] is None else (
        f"{_fmt_num(indicators['land_area_m2'])}㎡ / {_fmt_num(indicators['land_area_pyung'])}평")
    md += f"| 대지면적(필지) | {area} | VWorld 토지특성(lndpclAr) |\n"
    ledger = "N/A" if indicators["ledger_plat_area_m2"] is None else (
        f"{_fmt_num(indicators['ledger_plat_area_m2'])}㎡ / {_fmt_num(indicators['ledger_plat_area_pyung'])}평")
    md += f"| 대지면적(건축물대장) | {ledger} | 건축물대장 {indicators['building_basis'] or '-'}(platArea) |\n"
    md += f"| 지목 | {val(indicators['jimok'])} | VWorld 토지특성(lndcgrCodeNm) |\n"
    md += f"| 용도지역 | {', '.join(indicators['zoning']) if indicators['zoning'] else 'N/A'} | VWorld WFS(lt_c_uq111~114) |\n"
    md += (f"| 지역·지구·구역 | {', '.join(indicators['zoning_districts']) if indicators['zoning_districts'] else 'N/A'} "
           "| 건축물대장 지역지구구역(jijiguCdNm) |\n")
    if indicators["land_price_per_m2"] is None:
        lp = "N/A"
    else:
        lp = (f"{indicators['land_price_per_m2']:,}원/㎡ ({indicators['land_price_per_pyung']:,}원/평, "
              f"{indicators['land_price_year']}년 기준)")
    md += f"| 개별공시지가 | {lp} | VWorld 토지특성(pblntfPclnd) |\n"
    basis = f"건축물대장 {indicators['building_basis']}" if indicators["building_basis"] else "건축물대장"
    md += f"| 주용도 | {val(indicators['main_purpose'])} | {basis}(mainPurpsCdNm) |\n"
    tfa = "N/A" if indicators["total_floor_area_m2"] is None else (
        f"{_fmt_num(indicators['total_floor_area_m2'])}㎡ / {_fmt_num(indicators['total_floor_area_pyung'])}평")
    md += f"| 연면적 | {tfa} | {basis}(totArea) |\n"
    md += f"| 건폐율 / 용적률 | {val(indicators['building_coverage_ratio'], '%')} / {val(indicators['floor_area_ratio'], '%')} | {basis}(bcRat/vlRat) |\n"
    md += (f"| 층수(지상/지하) | {val(indicators['ground_floors'], '층')} / {val(indicators['underground_floors'], '층')} "
           "| 건축물대장 표제부(단일 동일 때만) |\n")
    md += (f"| 사용승인일 | {val(indicators['use_approval_date'])} "
           "| 건축물대장 표제부(단일 동일 때만, useAprDay) |\n")
    md += f"| 동 수(주건축물) | {val(indicators['building_count'], '동')} | 건축물대장 총괄표제부(mainBldCnt) |\n"
    for t, item in indicators["transactions"].items():
        label = TX_CONFIG[t]["label"]
        if item["status"] == "NOT_FOUND":
            md += f"| 인근 실거래({label}) | 조회 기간 내 거래 없음 (NOT_FOUND) | 국토부 실거래가 |\n"
            continue
        if item["status"] != "OK":
            md += f"| 인근 실거래({label}) | 조회 실패 ({item['status']}) | 국토부 실거래가 |\n"
            continue
        if t == "commercial":
            text = (f"유효 {item['valid_count']}건, 대지 평단가 중위 {val(item.get('median_land_price_per_pyung'), ' 만원/평')}, "
                    f"건물 평단가 중위 {val(item.get('median_building_price_per_pyung'), ' 만원/평')}")
        else:
            text = f"유효 {item['valid_count']}건, 평단가 중위 {val(item.get('median_price_per_pyung'), ' 만원/평')}"
        md += f"| 인근 실거래({label}) | {text} | 국토부 실거래가 |\n"

    md += "\n### 🧾 섹션별 조회 상태\n"
    md += "| 섹션 | 상태 | 메시지 |\n| :--- | :---: | :--- |\n"
    for name in ("parcel", "landuse", "land_price", "building", "transactions"):
        s = sections[name]
        msg = str(s.get("message") or "").replace("\n", " ").replace("|", "/")
        md += f"| {name} | {s['status']} | {msg[:200]} |\n"

    tx_data = sections["transactions"].get("data") or {}
    blocks = [e["summary_markdown"] for e in tx_data.values() if e.get("summary_markdown")]
    if blocks:
        md += "\n" + "\n".join(blocks)

    if parcel.get("legal_dong") and parcel["legal_dong"].get("ri"):
        md += "\n> ℹ️ 리(里) 단위 필지: 인근 실거래는 '읍·면 + 리' 단위(umdNm)로 필터링함\n"
    md += f"\n> ⚠️ {DISCLAIMER}\n"
    return md


# --- Tools ---

async def site_profile(
    address: Optional[str] = None,
    pnu: Optional[str] = None,
    include_building: bool = True,
    include_transactions: bool = True,
    transaction_types: List[TransactionType] = ["land", "commercial"],
    months_back: int = 12,
) -> Dict[str, Any]:
    """
    부지(필지) 종합 프로파일을 한 번에 조회합니다. PNU 를 연결 키로 VWorld·건축물대장·실거래가를 병렬 조회합니다.

    address: 지번 또는 도로명 주소 (pnu 와 둘 중 하나 필수). VWorld 지오코딩 → 좌표 → 필지 PNU 순으로 변환
    pnu: 19자리 필지고유번호 (address 보다 우선)
    include_building: 건축물대장(총괄표제부·표제부·지역지구구역) 조회 여부 (기본 True)
    include_transactions: 실거래가 조회 여부 (기본 True)
    transaction_types: 실거래 유형 목록 "land" / "commercial" / "apartment" (기본 ["land", "commercial"])
    months_back: 실거래가 조회 기간(최근 N개월, 기본 12 — 공공데이터포털 일일 트래픽 고려)

    반환: pnu, address(지번/도로명), coordinates, summary(핵심 지표 + 한글 Markdown),
          sections(parcel/landuse/land_price/building/transactions, 섹션별 status·message), sources.
    섹션 하나가 실패해도 전체 응답을 반환합니다(부분 실패 허용). 값이 없으면 null.
    """
    queried_at = _now_iso()
    resolution: Dict[str, Any] = {"input": {"address": address, "pnu": pnu}}
    coordinates: Optional[Dict[str, Any]] = None
    refined_address: Optional[str] = None

    empty_sections = {
        name: _skipped("PNU 미확정으로 조회하지 않음")
        for name in ("parcel", "landuse", "land_price", "building", "transactions")
    }

    def failure(status: str, message: str) -> Dict[str, Any]:
        return {
            "status": status,
            "message": message,
            "pnu": None,
            "address": {"input": address, "refined": None, "jibun": None, "road": None},
            "coordinates": coordinates,
            "resolution": resolution,
            "summary": None,
            "sections": empty_sections,
            "sources": {},
            "queried_at": queried_at,
            "disclaimer": DISCLAIMER,
        }

    # --- 1. PNU 확정 ---
    if pnu:
        try:
            pnu = normalize_pnu(pnu)
        except ValueError as e:
            return failure("ERROR", str(e))
        resolution["method"] = "pnu"
    elif address and address.strip():
        resolved = await _resolve_address(address.strip())
        resolution.update({"method": "address", **{k: v for k, v in resolved.items() if k not in ("pnu",)}})
        if resolved.get("coordinates"):
            coordinates = {**resolved["coordinates"], "source": "vworld_geocode"}
        if resolved["status"] != "OK":
            return failure(resolved["status"], resolved["message"])
        pnu = resolved["pnu"]
        refined_address = resolved.get("refined_address")
    else:
        return failure("ERROR", "Either 'address' or 'pnu' must be provided.")

    assert pnu is not None
    parts = split_pnu(pnu)
    lawd_cd = parts.lawd_cd

    # 법정동명 (D1: code_bdong.json 에서 PNU[0:10] 법정동코드로 조회)
    bdong: Optional[Dict[str, Any]] = None
    bdong_note: Optional[str] = None
    try:
        bdong = rtms.lookup_bdong(parts.bdong_cd)
        if bdong is None:
            bdong_note = f"법정동코드 {parts.bdong_cd} 를 code_bdong.json 에서 찾지 못해 실거래가는 시군구 전체 기준으로 조회"
    except Exception as e:
        bdong_note = f"법정동코드 DB 조회 실패({sanitize_error(str(e))}); 실거래가는 시군구 전체 기준으로 조회"
    # 실거래 법정동 필터: 동 지역은 읍면동명, 리 지역은 "읍면명 리명" (umdNm 표기와 동일)
    dong_name: Optional[str] = None
    if bdong and bdong.get("dong"):
        dong_name = f"{bdong['dong']} {bdong['ri']}" if bdong.get("ri") else bdong["dong"]

    tx_types: List[str] = []
    for t in transaction_types or []:
        if t in TX_CONFIG and t not in tx_types:
            tx_types.append(t)
    months = rtms.get_months_list(months_back)

    # --- 2. 병렬 조회 ---
    jobs: Dict[str, Awaitable[Dict[str, Any]]] = {
        "parcel": _parcel_with_address(pnu),
        "landuse": _safe(vworld.vworld_get_landuse_zone(pnu=pnu)),
        "land_price": _safe(vworld.vworld_get_individual_price(pnu)),
    }
    if include_building:
        jobs["recap"] = _safe(bldrgst.br_get_recap_title(pnu=pnu))
        jobs["title"] = _safe(bldrgst.br_get_title(pnu=pnu))
        jobs["jijigu"] = _safe(bldrgst.br_get_jijigu(pnu=pnu))
    if include_transactions:
        for t in tx_types:
            jobs[f"tx_{t}"] = _safe(TX_CONFIG[t]["tool"](pnu=pnu, dong=dong_name, months_back=months_back))

    names = list(jobs.keys())
    outputs = await asyncio.gather(*jobs.values())
    results: Dict[str, Dict[str, Any]] = dict(zip(names, outputs))

    # --- 3. 섹션 정리 ---
    sections: Dict[str, Any] = {
        "parcel": _build_parcel_section(pnu, results["parcel"], bdong),
        "landuse": _build_landuse_section(results["landuse"]),
        "land_price": _build_land_price_section(results["land_price"]),
    }
    if include_building:
        sections["building"] = _build_building_section(results["recap"], results["title"], results["jijigu"])
    else:
        sections["building"] = _skipped("include_building=False")

    if not include_transactions:
        sections["transactions"] = _skipped("include_transactions=False")
    elif not tx_types:
        sections["transactions"] = _skipped("transaction_types 가 비어 있음")
    else:
        tx_data = {
            t: _build_transaction_entry(t, results[f"tx_{t}"], lawd_cd, dong_name, months) for t in tx_types
        }
        tx_status = _combine_status([e["status"] for e in tx_data.values()])
        tx_msg = "; ".join(f"{t}: {e['status']}" + (f" ({e['message'][:120]})" if e["status"] == "ERROR" else "")
                           for t, e in tx_data.items())
        if bdong_note:
            tx_msg += f" | {bdong_note}"
        sections["transactions"] = {"status": tx_status, "message": tx_msg, "data": tx_data}

    # 좌표: 주소 입력이면 지오코딩 좌표, PNU 입력이면 필지 경계 중심점
    if coordinates is None and results["parcel"].get("centroid"):
        coordinates = {**results["parcel"]["centroid"], "source": "parcel_centroid"}

    parcel_data = sections["parcel"].get("data") or {}
    result: Dict[str, Any] = {
        "status": "",
        "pnu": pnu,
        "address": {
            "input": address,
            "refined": refined_address,
            "jibun": parcel_data.get("jibun_address"),
            "road": parcel_data.get("road_address"),
        },
        "coordinates": coordinates,
        "resolution": resolution,
        "summary": {},
        "sections": sections,
        "sources": {},
        "queried_at": queried_at,
        "disclaimer": DISCLAIMER,
        "_policy_notice": "CAUTION: Storing or caching coordinates/addresses retrieved from VWorld is strictly prohibited.",
    }

    active = [s["status"] for s in sections.values() if s["status"] != "SKIPPED"]
    if active and all(s == "OK" for s in active):
        result["status"] = "OK"
    elif any(s == "OK" for s in active):
        result["status"] = "PARTIAL"
    else:
        result["status"] = "ERROR" if any(s == "ERROR" for s in active) else "NOT_FOUND"

    # --- 4. sources ---
    price_data = sections["land_price"].get("data") or {}
    sources: Dict[str, Any] = {
        "parcel": {
            "apis": ["VWorld 2D 데이터 API (LP_PA_CBND_BUBUN 연속지적도)", "VWorld Geocoder API (getAddress 역지오코딩)",
                     "법정동코드 DB (data/code_bdong.json)"],
            # 연속지적도 속성 gosi_year / gosi_month 원문값 (고시 연·월). 없으면 null
            "reference_year_month": parcel_data.get("cadastral_gosi_year_month"),
            "queried_at": queried_at,
        },
        "landuse": {
            "apis": ["VWorld WFS API (lt_c_uq111~lt_c_uq114 용도지역)"],
            "reference_date": None,  # TODO: 기준일자 필드명 미확인
            "queried_at": queried_at,
        },
        "land_price": {
            "apis": ["VWorld 토지특성 속성조회 (ned/data/getLandCharacteristics)"],
            "reference_year": price_data.get("year"),
            "queried_at": queried_at,
        },
    }
    if include_building:
        sources["building"] = {
            "apis": ["건축HUB 건축물대장정보 서비스 (getBrRecapTitleInfo, getBrTitleInfo, getBrJijiguInfo)"],
            "reference_date": None,  # crtnDay(생성일자)는 실응답에 있으나 "기준일자"인지 공식 정의 미확인 → null 유지
            "queried_at": queried_at,
        }
    if include_transactions and tx_types:
        sources["transactions"] = {
            "apis": [f"국토교통부 실거래가 공개 API ({TX_CONFIG[t]['endpoint']})" for t in tx_types],
            "lawd_cd": lawd_cd,
            "dong_filter": dong_name,
            "deal_ymd_range": f"{months[-1]}~{months[0]}" if months else None,
            "months_back": months_back,
            "queried_at": queried_at,
        }
    if resolution.get("method") == "address":
        sources["resolution"] = {
            "apis": ["VWorld Geocoder API (getcoord)", "VWorld 2D 데이터 API (LP_PA_CBND_BUBUN, geomFilter)"],
            "queried_at": queried_at,
        }
    result["sources"] = sources

    # --- 5. summary ---
    indicators = _build_summary(sections, tx_types if include_transactions else [])
    result["summary"] = {"indicators": indicators, "markdown": "", "disclaimer": DISCLAIMER}
    result["summary"]["markdown"] = _render_markdown(result, indicators)
    return result


async def health_check() -> Dict[str, Any]:
    """
    통합 연결성 진단 도구. VWorld·건축물대장·실거래가 3개 API 를 동시에 점검해 API 별 상태를 반환합니다.
    (기존 vworld_health_check / br_health_check / health_check 를 통합)

    - vworld: 검색 API 경량 요청(HTTP 상태, 응답시간, 응답 본문 status)
    - bldrgst: 서울 강남구 역삼동 822-2 기본개요 1건 조회
    - rtms: 법정동코드 DB 확인 + 서울 중구 소공동 최근 1개월 아파트 거래 조회
    """
    checked_at = _now_iso()
    vw, br, rt = await asyncio.gather(
        _safe(vworld._vworld_health()),
        _safe(bldrgst._bldrgst_health()),
        _safe(rtms._rtms_health()),
    )
    apis: Dict[str, Any] = {"vworld": vw, "bldrgst": br, "rtms": rt}
    # 응답 프리뷰까지 포함해 키가 새지 않도록 전체를 한 번 더 마스킹한다.
    try:
        apis = json.loads(sanitize_error(json.dumps(apis, ensure_ascii=False, default=str)))
    except ValueError:
        pass
    oks = [r.get("status") == "OK" for r in apis.values()]
    if all(oks):
        status = "OK"
    elif any(oks):
        status = "DEGRADED"
    else:
        status = "ERROR"
    return {
        "status": status,
        "checked_at": checked_at,
        "keys_configured": {
            "VWORLD_API_KEY": config.vworld_key_raw() is not None,
            "BLDRGST_API_KEY (or DATA_GO_KR_SERVICE_KEY)": config.bldrgst_key_raw() is not None,
            "MOLIT_SERVICE_KEY (or DATA_GO_KR_SERVICE_KEY)": config.molit_key_raw() is not None,
        },
        "apis": apis,
        "message": {
            "OK": "All APIs reachable and authenticated.",
            "DEGRADED": "Some APIs failed. See 'apis' for per-API status.",
            "ERROR": "All API checks failed. See 'apis' for details.",
        }[status],
    }


TOOLS = (site_profile, health_check)


def register(mcp: FastMCP) -> None:
    for fn in TOOLS:
        mcp.tool()(fn)
