# 부동산 통합 조회 MCP 서버 (realestate-mcp)

VWorld(지오코딩·필지·용도지역·공시지가), 건축HUB 건축물대장, 국토교통부 실거래가(RTMS) 세 공공 API를 **단일 MCP 서버**로 묶은 프로젝트입니다. **PNU(필지고유번호 19자리)**를 연결 키로 세 API를 한 번에 조회하는 통합 도구 `site_profile`을 제공합니다.

기존에 따로 운영하던 MCP 서버 3개를 통합했습니다. 기존 도구의 파라미터와 반환 형식은 그대로 유지하며, 도구 이름 변경 내역은 [MIGRATION.md](MIGRATION.md)를 참고하십시오.

| 원본 저장소 | 도메인 |
| :--- | :--- |
| [jeon3709-dev/vworld-mcp](https://github.com/jeon3709-dev/vworld-mcp) | VWorld Open API |
| [jeon3709-dev/BDLedger_MCP](https://github.com/jeon3709-dev/BDLedger_MCP) | 건축HUB 건축물대장정보 서비스 (공공데이터포털) |
| [jeon3709-dev/LandPrice_MCP](https://github.com/jeon3709-dev/LandPrice_MCP) | 국토교통부 실거래가 공개 API (공공데이터포털) |

---

## 🛠️ 제공 도구 (총 21개)

### 통합 도구

| 도구 | 설명 | 주요 파라미터 |
| :--- | :--- | :--- |
| **`site_profile`** | 주소 또는 PNU 하나로 필지·용도지역·공시지가·건축물대장·인근 실거래를 **병렬 조회**하고 핵심 지표 요약과 한글 Markdown 리포트를 반환 | `address` 또는 `pnu`(둘 중 하나 필수), `include_building`(기본 True), `include_transactions`(기본 True), `transaction_types`(기본 `["land","commercial"]`), `months_back`(기본 12) |
| **`health_check`** | 세 API의 연결성·인증 상태를 동시에 점검하고 API별 상태를 반환 (기존 헬스체크 3개 통합) | 없음 |

### VWorld (`vworld_*`)

| 도구 | 설명 | 주요 파라미터 |
| :--- | :--- | :--- |
| `vworld_search` | 주소/장소 통합 검색 | `query`, `category`(`address`/`place`) |
| `vworld_geocode` | 주소 → 좌표 (저장·캐싱 금지) | `address`, `address_type`(`road`/`parcel`) |
| `vworld_reverse_geocode` | 좌표 → 도로명·지번 주소 (저장·캐싱 금지) | `lat`, `lon` |
| `vworld_get_parcel` | 연속지적도(LP_PA_CBND_BUBUN) 필지 경계(GeoJSON)·속성 | `pnu` |
| `vworld_get_landuse_zone` | 용도지역(lt_c_uq111~114, WFS) | `pnu` 또는 `lat`+`lon` |
| `vworld_get_individual_price` | 개별공시지가(원/㎡). 올해부터 최대 3년 전까지 거슬러 조회 | `pnu` |

### 건축물대장 (`br_*`)

모든 도구는 `pnu`(19자리)를 받습니다. `sigunguCd`, `bjdongCd`, `platGbCd`, `bun`, `ji`로 개별 지정할 수도 있고, `numOfRows`와 `pageNo`로 페이지를 지정합니다. PNU의 필지구분 1(일반)은 `platGbCd=0`, 2(산)는 `platGbCd=1`로 바뀌어 전송됩니다.

| 도구 | API | 설명 / 추가 파라미터 |
| :--- | :--- | :--- |
| `br_get_basis_ouln` | getBrBasisOulnInfo | 기본개요 |
| `br_get_recap_title` | getBrRecapTitleInfo | 총괄표제부 (대지 전체: 대지면적, 연면적, 건폐율, 용적률, 주건축물수) |
| `br_get_title` | getBrTitleInfo | 표제부 (동별 주용도·구조·층수) / `dongNm` |
| `br_get_floor_ouln` | getBrFlrOulnInfo | 층별개요 / `dongNm`, `flrGbCd`, `flrNo` |
| `br_get_atch_jibun` | getBrAtchJibunInfo | 부속지번 |
| `br_get_expos_pubuse_area` | getBrExposPubuseAreaInfo | 전유공용면적 / `dongNm`, `hoNm` |
| `br_get_wclf` | getBrWclfInfo | 오수정화시설 |
| `br_get_house_price` | getBrHsprcInfo | 공동주택가격 |
| `br_get_expos` | getBrExposInfo | 전유부 / `dongNm`, `hoNm` |
| `br_get_jijigu` | getBrJijiguInfo | 지역지구구역 |

### 실거래가 (`rtms_*`)

| 도구 | API | 설명 / 추가 파라미터 |
| :--- | :--- | :--- |
| `rtms_search_land_transactions` | RTMSDataSvcLandTrade | 토지 매매 / `zone_filter`(용도지역) |
| `rtms_search_commercial_transactions` | RTMSDataSvcNrgTrade | 상업업무용 매매. 대지 평단가와 연면적 평단가를 함께 제공 / `building_use_filter` |
| `rtms_search_apartment_transactions` | RTMSDataSvcAptTradeDev | 아파트 매매 상세 / `min_area`, `max_area`, `buyer_type_filter` |

세 도구가 공통으로 받는 파라미터는 다음과 같습니다.

- 지역 지정: `sigungu`, `dong`, `sido`(선택)
- 조회 옵션: `months_back`(기본 36), `exclude_share_deals`, `exclude_cancelled`
- **신규** `pnu` / `lawd_cd`: 지역을 코드로 지정합니다. 우선순위는 `pnu` > `lawd_cd` > `sigungu`/`dong`입니다.
  - `pnu`를 주면 앞 5자리를 LAWD_CD로 쓰고, 법정동 코드 DB(`code_bdong.json`)는 거치지 않습니다.
  - 이때 `dong`은 법정동명 필터로 쓰입니다(접두어 일치, 예: `광희동` → `광희동1가`·`광희동2가`). `dong`을 생략하면 시군구 전체를 조회합니다.
  - 기존처럼 `sigungu`/`dong`만 주는 호출도 그대로 동작합니다.
- 평 환산은 `㎡ × 0.3025`, 금액 단위는 만원입니다.

---

## 🧭 `site_profile` 동작

1. **PNU 확정**: `pnu`가 없으면 `address`를 PNU로 바꿉니다.
   - VWorld 지오코딩을 순차로 시도합니다. 도로명 패턴(`…로/길 + 숫자`)이면 도로명을 먼저, 아니면 지번을 먼저 시도하고, 실패하면 다른 방식으로 한 번 더 시도합니다.
   - 얻은 좌표로 연속지적도 필지를 찾아 PNU를 구합니다(`geomFilter=POINT(lon lat)`).
2. **병렬 조회**(`asyncio.gather`)
   - VWorld: `vworld_get_parcel`, 역지오코딩(도로명 주소), `vworld_get_landuse_zone`, `vworld_get_individual_price`
   - 건축물대장: `br_get_recap_title`, `br_get_title`, `br_get_jijigu`(용도지구 확인용)
   - 실거래가: `transaction_types`별 `rtms_*`를 호출합니다. LAWD_CD는 `PNU[0:5]`, 법정동명은 `data/code_bdong.json`에서 `PNU[0:10]`(법정동코드)로 찾습니다.
3. **부분 실패 허용**: 섹션마다 `status`(`OK` / `NOT_FOUND` / `ERROR` / `SKIPPED`)와 `message`가 붙습니다. 일부 섹션이 실패해도 응답 전체를 반환하며, 최상위 `status`는 `OK` / `PARTIAL` / `ERROR` / `NOT_FOUND` 중 하나입니다.

반환 구조는 다음과 같습니다.

```text
{
  status, pnu,
  address: {input, refined, jibun, road},
  coordinates: {lat, lon, source},          # vworld_geocode 또는 parcel_centroid
  resolution,                               # 주소→PNU 변환 과정(시도 이력)
  summary: {indicators, markdown, disclaimer},
  sections: {parcel, landuse, land_price, building, transactions},   # 각 {status, message, data}
  sources: {섹션: {apis, reference_year | deal_ymd_range, queried_at, ...}},
  queried_at, disclaimer
}
```

**`summary.indicators`** 항목과 출처는 아래와 같습니다. 값이 없으면 `null`이며, 추정값이나 대체값은 넣지 않습니다.

| 지표 | 출처 |
| :--- | :--- |
| 대지면적(필지) ㎡/평, 지목 | VWorld 토지특성 `lndpclAr`, `lndcgrCodeNm` |
| 대지면적(건축물대장) ㎡/평 | 총괄표제부 `platArea`. 총괄표제부가 없으면 표제부가 1건일 때만 사용 |
| 용도지역 / 지역·지구·구역 | VWorld WFS `uname` / 건축물대장 `jijiguCdNm` |
| 개별공시지가 원/㎡·원/평, 기준연도 | VWorld 토지특성 `pblntfPclnd`. 원/평 = 원/㎡ ÷ 0.3025 |
| 주용도, 연면적, 건폐율, 용적률 | 총괄표제부. 없으면 단일 표제부 (`mainPurpsCdNm`, `totArea`, `bcRat`, `vlRat`) |
| 지상/지하 층수 | 표제부가 **1건일 때만** `grndFlrCnt`/`ugrndFlrCnt`. 여러 동이면 `null`이며 동별 값은 `sections.building.data.titles`에 있음 |
| 동 수 | 총괄표제부 `mainBldCnt` |
| 인근 실거래 | 유형별 유효 거래 건수와 평단가 중위값(만원/평). 상업업무용은 대지 기준과 연면적 기준을 모두 표시 |

> 사용승인일은 원본 코드에서 필드명을 확인할 수 없어 요약에서 제외했습니다(아래 "미검증 항목" 참고).

---

## ⚙️ 환경변수

| 변수 | 필수 | 설명 |
| :--- | :---: | :--- |
| `VWORLD_API_KEY` | △ | VWorld 인증키 |
| `BLDRGST_API_KEY` | △ | 건축물대장 인증키 (공공데이터포털 **Decoding** 키 권장) |
| `MOLIT_SERVICE_KEY` | △ | 실거래가 인증키 (공공데이터포털 **Decoding** 키 권장) |
| `DATA_GO_KR_SERVICE_KEY` | - | 공공데이터포털 공용 키. `BLDRGST_API_KEY`나 `MOLIT_SERVICE_KEY`가 비어 있을 때만 대신 사용하며, 개별 키가 있으면 개별 키가 우선합니다. |
| `VWORLD_DOMAIN` | - | VWorld `domain` 파라미터와 Referer 값 (기본 `localhost`) |
| `VWORLD_PROXY_URL` | - | VWorld 요청용 아웃바운드 프록시 |
| `BLDRGST_PROXY_URL` | - | 건축물대장 요청용 아웃바운드 프록시 |
| `RTMS_CONCURRENCY` | - | 실거래가 월별 호출 동시 실행 수 (기본 5) |
| `PORT` | - | HTTP 포트 (기본 8080, Cloudtype이 자동 주입) |

△: 키가 없어도 서버는 기동합니다. 키가 빠진 API의 도구만 에러 메시지를 돌려줍니다.

**보안**
- 에러 메시지와 로그에서는 설정된 **모든 키**를 가립니다. 원문뿐 아니라 URL 인코딩된 형태도 가립니다.
- httpx 요청 로그(URL에 키가 들어감)는 WARNING 레벨로 낮췄습니다.
- `.env`는 `.gitignore` 대상입니다.

---

## 🚀 로컬 실행

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt      # 개발/테스트까지: pip install -r requirements-dev.txt
cp .env.example .env                 # 키 입력
```

- **stdio** (Claude Desktop 등 로컬 클라이언트): `python server.py stdio`
- **HTTP** (Streamable HTTP `/mcp` + 레거시 SSE `/sse`): `python server.py sse` 또는 인자 없이 `python server.py`
  - `GET /`: 헬스 응답(`ok`)
  - `POST /`: `/mcp`로 전달
  - `/.well-known/oauth-*`, `/.well-known/mcp-configuration`: 404 JSON (OAuth 불필요 표시)

Claude Desktop(stdio) 설정 예시:

```json
{
  "mcpServers": {
    "realestate-mcp": {
      "command": "/절대경로/realestate-mcp/.venv/bin/python",
      "args": ["/절대경로/realestate-mcp/server.py", "stdio"],
      "env": {
        "VWORLD_API_KEY": "...",
        "BLDRGST_API_KEY": "...",
        "MOLIT_SERVICE_KEY": "..."
      }
    }
  }
}
```

### 테스트

```bash
pytest                          # 실제 API 키 없이 전부 통과 (HTTP는 respx로 목킹)
pyrefly check                   # 타입 검사
pytest tests/live_smoke.py -v   # (선택) 키가 있는 API만 실제 호출
python tests/live_smoke.py      # (선택) health_check + site_profile 결과 출력
```

---

## ☁️ Cloudtype 배포

VWorld Open API는 해외 IP 대역을 WAF로 차단합니다(원본 vworld-mcp README 기준). 그래서 한국 IP로 호스팅되는 Cloudtype에 배포합니다.

1. Cloudtype에서 새 프로젝트를 만들고 이 GitHub 저장소를 연결합니다. 종류는 **Python**입니다.
2. 빌드 명령은 `pip install -r requirements.txt`로 둡니다. 실행 명령은 비워 두면 `Procfile`(`web: python server.py sse`)이 적용됩니다.
3. 포트는 `8080`으로 둡니다. Cloudtype이 주입하는 `PORT` 값을 서버가 읽습니다.
4. 환경변수(Secrets)를 등록합니다.
   - `VWORLD_API_KEY`, `BLDRGST_API_KEY`, `MOLIT_SERVICE_KEY` (또는 `DATA_GO_KR_SERVICE_KEY`)
   - `VWORLD_DOMAIN`: Cloudtype 앱 도메인 (예: `my-app.cloudtype.app`). VWorld 인증키에 등록한 도메인과 맞춰야 합니다.
5. 배포한 뒤 다음을 확인합니다.
   - `https://<host>/` 가 `ok`를 반환하는지
   - MCP로 `health_check`를 실행했을 때 세 API가 모두 `OK`인지

> `code_bdong.json`(약 11.8MB, 법정동 코드)은 `data/`에 포함되어 있습니다. 새로 만들려면 `python scripts/download_db.py`를 실행합니다.

## 🔌 claude.ai 커스텀 커넥터 등록

- 설정 → 커넥터 → 커스텀 커넥터 추가 → URL에 **`https://<host>/mcp`**를 입력합니다.
- OAuth 없이 연결됩니다. 서버가 OAuth discovery 요청에 404로 응답하기 때문입니다.
- 레거시 SSE 클라이언트는 `https://<host>/sse`를 사용합니다.

## 💬 사용 예시 프롬프트

- "서울 강남구 역삼동 822-2 부지 프로파일 뽑아줘. 토지·상업업무용 실거래는 최근 12개월로."
- "PNU 1168010100108220002의 용도지역, 공시지가, 건폐율·용적률, 인근 토지 실거래 평단가 중위값을 표로 정리해줘."
- "테헤란로 ○○○ 건물의 총괄표제부와 층별개요 보여줘." (`site_profile`로 PNU 확인 → `br_get_floor_ouln`)
- "중구 광희동 최근 36개월 상업업무용 실거래, 제2종근린생활만." (`rtms_search_commercial_transactions`)
- "PNU <19자리> 기준으로 해당 시군구 전체 토지 거래를 조회해줘." (`rtms_search_land_transactions(pnu=...)`)
- "세 API 연결 상태 점검해줘." (`health_check`)

---

## ⚠️ 이용 정책

- **VWorld**: Geocoder·Reverse Geocoder는 일일 30,000건으로 제한됩니다. 조회한 좌표와 주소를 **저장하거나 캐싱하면 안 됩니다**. 이 서버는 모든 조회를 실시간으로 처리합니다.
- **공공데이터포털**: 키마다 일일 트래픽 한도가 있습니다. 실거래가는 **월마다 1회씩(페이지가 여러 개면 페이지마다)** 호출하므로 `months_back`이 클수록 호출 수가 늘어납니다.
  - 예: `site_profile` 기본값(토지+상업업무용, 12개월)이면 실거래가 호출만 최소 24회입니다.
- 모든 결과는 공공 API 원자료입니다. 권리관계와 현황은 **등기부와 현장 확인**이 필요합니다.

## 🧪 미검증 항목 (TODO)

이 저장소의 테스트는 원본 코드에 나오는 필드명만으로 만든 **합성 응답**으로 검증했습니다. 아래 항목은 실제 응답이나 공식 문서로 아직 확인하지 못했습니다. 개발 컨테이너에서는 `api.vworld.kr`, `apis.data.go.kr` 접근이 막혀 있었습니다.

1. **VWorld Data API의 `geomFilter=POINT(x y)`** (주소→PNU 변환): 원본 코드에 없는 파라미터입니다. 공식 문서에 접근하지 못했고, 다른 저장소의 실사용 코드로만 확인했습니다.
   - 실패해도 `site_profile(address=...)`가 `NOT_FOUND`/`ERROR`를 돌려줄 뿐 오동작하지는 않습니다.
   - `tests/live_smoke.py::test_live_vworld_point_to_pnu`로 검증할 수 있습니다.
2. **건축물대장 사용승인일(`useAprDay`)**: 원본 docstring에 없는 필드라 요약에서 뺐습니다. 참고로 PublicDataReader 문서에는 표제부 필드로 나옵니다.
3. VWorld 연속지적도 속성 중 `pnu`를 뺀 나머지 필드명과 기준일자는 확인하지 않았습니다. 그래서 속성 원본을 `sections.parcel.data.properties`에 그대로 넣기만 하고 해석하지 않습니다.
4. WFS `lt_c_uq111~114`의 `uname` 값이 세분 용도지역(예: 제3종일반주거지역)인지 대분류인지 확인하지 않았습니다.
5. 건축물대장 응답의 기준일자 필드(`crtnDay` 등)와 숫자 필드의 자료형(문자열인지 숫자인지)을 확인하지 않았습니다. 코드는 두 경우 모두 처리합니다.
6. 리(里) 단위 필지에서 실거래가 `umdNm`이 어떤 형식으로 오는지 확인하지 않았습니다. 현재는 읍·면 이름으로 접두어 필터를 적용합니다.
