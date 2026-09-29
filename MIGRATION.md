# 마이그레이션 가이드: 커넥터 3개 → 통합 커넥터 1개

## 도구 이름 대응표

| 기존 서버 | 기존 도구 | 통합 서버 도구 | 변경 사항 |
| :--- | :--- | :--- | :--- |
| vworld-mcp | `vworld_search` | `vworld_search` | 없음 |
| vworld-mcp | `vworld_geocode` | `vworld_geocode` | 없음 |
| vworld-mcp | `vworld_reverse_geocode` | `vworld_reverse_geocode` | 없음 |
| vworld-mcp | `vworld_get_parcel` | `vworld_get_parcel` | 없음 |
| vworld-mcp | `vworld_get_landuse_zone` | `vworld_get_landuse_zone` | 없음 |
| vworld-mcp | `vworld_get_individual_price` | `vworld_get_individual_price` | 없음 |
| vworld-mcp | `vworld_health_check` | **`health_check`** | 통합 헬스체크로 흡수 (`apis.vworld`) |
| BDLedger_MCP | `br_get_basis_ouln` ~ `br_get_jijigu` (10개) | 동일 | 없음 |
| BDLedger_MCP | `br_health_check` | **`health_check`** | 통합 헬스체크로 흡수 (`apis.bldrgst`) |
| LandPrice_MCP | `search_land_transactions` | **`rtms_search_land_transactions`** | 이름 변경, `pnu`/`lawd_cd` 선택 파라미터 추가 |
| LandPrice_MCP | `search_commercial_transactions` | **`rtms_search_commercial_transactions`** | 이름 변경, `pnu`/`lawd_cd` 선택 파라미터 추가 |
| LandPrice_MCP | `search_apartment_transactions` | **`rtms_search_apartment_transactions`** | 이름 변경, `pnu`/`lawd_cd` 선택 파라미터 추가 |
| LandPrice_MCP | `health_check` | **`health_check`** | 통합 헬스체크 (`apis.rtms`) |
| (신규) | - | **`site_profile`** | PNU 기준 3개 API 통합 조회 |

## 호환성 메모

- **기존 파라미터와 반환 형식은 그대로입니다.** 상태 코드, 한글 Markdown 리포트, 경고 문구도 원본과 같습니다.
- `rtms_*`의 `sigungu`와 `dong`은 필수에서 선택으로 바뀌었습니다. 기존처럼 위치 인자나 키워드로 넘기는 호출은 그대로 동작합니다.
  - 셋 중 하나는 반드시 주어야 합니다: `pnu`, `lawd_cd`, 또는 `sigungu`+`dong`.
  - 셋 다 없으면 `status: "ERROR"`를 반환합니다.
- `health_check`의 반환 형식은 새로 정했습니다: `{status: OK|DEGRADED|ERROR, keys_configured, apis: {vworld, bldrgst, rtms}}`. 각 API 결과는 원본 헬스체크 응답과 같은 형태입니다.
- 차이점은 아래와 같습니다. 모두 정상 응답 형식에는 영향이 없습니다.
  - **재시도**: 모든 API 요청이 5xx·네트워크 오류일 때 1회 재시도합니다. 4xx와 인증 오류는 재시도하지 않습니다.
  - **실거래가 병렬 호출**: 월별 호출을 병렬로 처리합니다(`RTMS_CONCURRENCY`, 기본 5). 월 순서대로 결과를 합치므로 거래 목록과 정렬은 원본과 같습니다.
  - **키 마스킹 강화**: 에러와 로그 메시지에서 설정된 모든 키를 가립니다. 원본 VWorld 서버는 WFS 요청의 `KEY=`(대문자)를 가리지 못했습니다.
  - **VWorld 헬스체크**: HTTP 200이어도 응답 본문의 status가 ERROR이면(예: 인증키 오류) `ERROR`로 보고합니다.
  - **VWorld 도구의 키 누락 동작**: 원본과 같이 예외를 던지고, MCP 클라이언트에는 도구 오류로 표시됩니다.

## 커넥터 교체 절차

1. **통합 서버 배포**: Cloudtype에 이 저장소로 새 앱을 만들고 배포합니다(README "Cloudtype 배포" 참고).
   - 환경변수는 기존 앱 3개에 있던 값을 한곳에 모읍니다: `VWORLD_API_KEY`, `VWORLD_DOMAIN`(새 앱 도메인), `BLDRGST_API_KEY`, `MOLIT_SERVICE_KEY`
   - 같은 공공데이터포털 키를 쓰고 있다면 `DATA_GO_KR_SERVICE_KEY` 하나로 대신할 수 있습니다.
   - VWorld 인증키에 새 앱 도메인을 등록했는지 확인합니다.
2. **점검**: `https://<new-host>/`가 `ok`를 반환하는지 확인합니다.
3. **커넥터 추가**: claude.ai 설정 → 커넥터 → 커스텀 커넥터 추가 → `https://<new-host>/mcp`
4. **동작 확인**: 새 커넥터로 `health_check`를 실행해 세 API가 모두 `OK`인지 보고, `site_profile`을 한 번 시험 호출합니다.
5. **기존 커넥터 제거**: VWorld, BDLedger, LandPrice 커넥터 3개를 비활성화하거나 삭제합니다. 도구 이름이 겹치는 커넥터(`vworld_*`, `br_*`)가 동시에 켜져 있으면 모델이 어느 쪽을 호출할지 모호해집니다.
6. **프롬프트와 문서 수정**: 저장해 둔 프롬프트나 문서가 `search_*_transactions` 또는 `health_check`(LandPrice 버전)를 이름으로 가리키면 새 이름으로 바꿉니다.
7. **기존 앱 정리**: 일정 기간 병행 운영한 뒤 기존 Cloudtype 앱 3개를 중지합니다.
