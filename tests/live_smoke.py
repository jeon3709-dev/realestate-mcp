"""실제 API 스모크 테스트 (pytest 기본 수집 대상 아님).

환경변수(.env 포함)에 키가 있는 API 만 실제로 호출하고, 없는 API 는 skip 한다.
실행:
    pytest tests/live_smoke.py -v          # pytest 로 명시 실행
    python tests/live_smoke.py              # 스크립트 실행(결과 요약 출력)

주의: 공공데이터포털 일일 트래픽을 소모한다. 출력에는 키가 포함되지 않는다(sanitize_error 적용).
"""
import asyncio
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from realestate_mcp import config  # noqa: E402
from realestate_mcp.common import sanitize_error  # noqa: E402
from realestate_mcp.tools import bldrgst, composite, rtms, vworld  # noqa: E402

SAMPLE_PNU = "1168010100108220002"  # 서울 강남구 역삼동 822-2 (원본 BDLedger 헬스체크 샘플)

needs_vworld = pytest.mark.skipif(config.vworld_key_raw() is None, reason="VWORLD_API_KEY not set")
needs_bldrgst = pytest.mark.skipif(config.bldrgst_key_raw() is None, reason="BLDRGST_API_KEY not set")
needs_molit = pytest.mark.skipif(config.molit_key_raw() is None, reason="MOLIT_SERVICE_KEY not set")
needs_all = pytest.mark.skipif(
    None in (config.vworld_key_raw(), config.bldrgst_key_raw(), config.molit_key_raw()),
    reason="all three API keys are required",
)


@needs_vworld
async def test_live_vworld_parcel_and_price():
    parcel = await vworld.vworld_get_parcel(SAMPLE_PNU)
    assert parcel["status"] in ("OK", "NOT_FOUND"), parcel
    price = await vworld.vworld_get_individual_price(SAMPLE_PNU)
    assert price["status"] in ("OK", "NOT_FOUND"), price


@needs_vworld
async def test_live_vworld_point_to_pnu():
    geo = await vworld.vworld_geocode("서울특별시 강남구 역삼동 822-2", "parcel")
    assert geo["status"] == "OK", geo
    found = await vworld.vworld_find_parcel_by_point(geo["coordinates"]["lat"], geo["coordinates"]["lon"])
    # geomFilter 파라미터 실검증 포인트
    assert found["status"] == "OK", found


@needs_bldrgst
async def test_live_bldrgst_title():
    res = await bldrgst.br_get_title(pnu=SAMPLE_PNU)
    assert res["status"] in ("OK", "NOT_FOUND"), res
    if res["status"] == "OK":
        print("title keys:", sorted(res["results"][0].keys()))


@needs_molit
async def test_live_rtms_pnu_path():
    res = await rtms.rtms_search_land_transactions(pnu=SAMPLE_PNU, dong="역삼동", months_back=3)
    assert res["status"] in ("OK", "NO_DATA"), res


@needs_all
async def test_live_site_profile():
    res = await composite.site_profile(pnu=SAMPLE_PNU, months_back=3)
    assert res["status"] in ("OK", "PARTIAL"), res["summary"]
    print(res["summary"]["markdown"])


async def _main() -> None:
    print(json.dumps(await composite.health_check(), ensure_ascii=False, indent=2, default=str))
    if None not in (config.vworld_key_raw(), config.bldrgst_key_raw(), config.molit_key_raw()):
        res = await composite.site_profile(pnu=SAMPLE_PNU, months_back=3)
        print(res["summary"]["markdown"])


if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except Exception as e:  # never print raw keys
        print("live smoke failed:", sanitize_error(str(e)))
        sys.exit(1)
