# CLAUDE.md — realestate-mcp

VWorld, 건축HUB 건축물대장, 국토부 실거래가(RTMS) 세 API를 묶은 단일 FastMCP 서버입니다. 도구는 21개입니다.

## 구조

```
server.py                      # FastMCP 인스턴스 1개(create_server), HTTP 앱(build_http_app), main(stdio / HTTP)
realestate_mcp/
  config.py                    # 환경변수·키 조회 (DATA_GO_KR_SERVICE_KEY 폴백), 포트, RTMS_CONCURRENCY
  common.py                    # sanitize_error(모든 키, 원문+인코딩), 로그 마스킹 필터, make_client(api), get_with_retry
  pnu.py                       # PNU 검증/분해/조립, LAWD_CD, 원본 parse_pnu(건축물대장)
  tools/__init__.py            # TOOL_MODULES 순서대로 register(mcp) 호출
  tools/vworld.py              # vworld_* 6 + _vworld_health + vworld_find_parcel_by_point(내부)
  tools/bldrgst.py             # br_* 10 + _bldrgst_health
  tools/rtms.py                # rtms_* 3 + _rtms_health, code_bdong.json 로딩/lookup, 월별 병렬 fetch
  tools/composite.py           # site_profile, health_check
data/code_bdong.json           # 법정동 코드 DB (scripts/download_db.py 로 재생성)
tests/                         # pytest (respx 목킹). tests/live_smoke.py 는 기본 수집 제외
```

- 도구는 모듈 수준의 일반 `async def`로 정의하고, 각 모듈의 `register(mcp)`에서 `mcp.tool()(fn)`으로 등록합니다. 그래서 `site_profile`과 테스트에서 도구 함수를 직접 호출할 수 있습니다.
- 도구를 새로 추가하면 해당 모듈의 `TOOLS` 튜플과 `tests/test_registration.py`의 `EXPECTED_TOOLS`를 함께 고쳐야 합니다.

## 명령

```bash
source .venv/bin/activate          # (없으면) python -m venv .venv && pip install -r requirements-dev.txt
pytest                             # 전체 테스트 (실제 API 키 불필요)
pyrefly check                      # 타입 검사, 오류 0개 유지
pytest tests/live_smoke.py -v      # 실제 API 스모크 (키가 있는 API만)
python server.py stdio             # stdio 모드
PORT=8080 python server.py sse     # HTTP 모드 (/mcp, /sse, GET /)
```

## 코딩 규칙

1. **원본 로직 보존**: `vworld_*`, `br_*`, `rtms_*`의 파라미터, 반환 키, 상태 코드, 에러 문구, 한글 Markdown 형식은 원본 저장소와 같게 유지합니다. 원본은 jeon3709-dev/vworld-mcp, BDLedger_MCP, LandPrice_MCP입니다. 바꿔야 하면 MIGRATION.md에 적습니다.
2. **추측 금지**: API 엔드포인트, 파라미터, 응답 필드명은 원본 코드나 공식 문서, 실제 응답으로 확인한 것만 씁니다. 확인되지 않은 것은 TODO로 남기고, README "검증 현황"의 "아직 실응답으로 확인하지 못한 항목"에 추가하고, 실응답으로 확인하면 확인일과 함께 "실응답으로 확인한 항목"으로 옮깁니다.
3. **요약 값**: `site_profile` 요약에는 추정값이나 대체값을 넣지 않습니다. 값이 없으면 `null`입니다. 평 환산(`× 0.3025`)만 허용합니다.
4. **키 마스킹**: 예외 메시지와 로그에 들어가는 문자열은 모두 `common.sanitize_error()`를 거칩니다. 키를 코드, 테스트 픽스처, 커밋에 넣지 않습니다. 테스트에서는 `tests/conftest.py`의 가짜 키만 씁니다.
5. **HTTP**: 새 요청은 `make_client(api)`와 `get_with_retry()`를 사용합니다. 재시도는 5xx와 네트워크 오류일 때 1회뿐이고, 4xx와 인증 오류는 재시도하지 않습니다.
6. **의존성**: `mcp>=1.9.0,<2.0.0` 상한 고정을 유지합니다. mcp 2.x에는 `mcp.server.fastmcp`가 없습니다.
7. **VWorld 정책**: 좌표와 주소를 저장하거나 캐싱하지 않습니다.
