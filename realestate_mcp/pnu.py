"""PNU(필지고유번호, 19자리) 검증·분해·조립과 API 별 파라미터 변환.

PNU 구조: 법정동코드 10자리(시군구 5 + 읍면동리 5) + 필지구분 1자리(1: 일반, 2: 산)
          + 본번 4자리 + 부번 4자리.
- 건축물대장 platGbCd: PNU 필지구분 1 → 0(대지), 2 → 1(산)  (원본 BDLedger parse_pnu)
- 실거래가 LAWD_CD: 시군구코드 5자리 = PNU 앞 5자리
"""
from dataclasses import dataclass
from typing import Optional

PNU_LENGTH = 19
LAWD_CD_LENGTH = 5
BDONG_CD_LENGTH = 10


@dataclass(frozen=True)
class PnuParts:
    sigungu_cd: str  # 0:5
    bjdong_cd: str  # 5:10
    land_type: str  # 10  (1: 일반, 2: 산)
    bun: str  # 11:15
    ji: str  # 15:19

    @property
    def lawd_cd(self) -> str:
        return self.sigungu_cd

    @property
    def bdong_cd(self) -> str:
        """10자리 법정동코드."""
        return self.sigungu_cd + self.bjdong_cd

    @property
    def is_mountain(self) -> bool:
        return self.land_type == "2"

    @property
    def plat_gb_cd(self) -> str:
        """건축물대장 대지구분코드 (1→0 일반, 2→1 산, 그 외 0)."""
        return "1" if self.land_type == "2" else "0"

    @property
    def jibun(self) -> str:
        """지번 문자열 (예: '822-2', '산 12')."""
        bun = int(self.bun)
        ji = int(self.ji)
        text = f"{bun}-{ji}" if ji else f"{bun}"
        return f"산 {text}" if self.is_mountain else text


def is_valid_pnu(pnu: Optional[str]) -> bool:
    if not pnu:
        return False
    pnu = pnu.strip()
    return len(pnu) == PNU_LENGTH and pnu.isdigit()


def normalize_pnu(pnu: Optional[str]) -> str:
    """Strip and validate a PNU; raise ValueError if not exactly 19 digits."""
    if not pnu:
        raise ValueError("PNU must be exactly 19 digits.")
    pnu = pnu.strip()
    if len(pnu) != PNU_LENGTH or not pnu.isdigit():
        raise ValueError("PNU must be exactly 19 digits.")
    return pnu


def split_pnu(pnu: str) -> PnuParts:
    pnu = normalize_pnu(pnu)
    return PnuParts(
        sigungu_cd=pnu[0:5],
        bjdong_cd=pnu[5:10],
        land_type=pnu[10],
        bun=pnu[11:15],
        ji=pnu[15:19],
    )


def build_pnu(bdong_cd: str, land_type: str, bun: str | int, ji: str | int) -> str:
    """Assemble a PNU from a 10-digit legal dong code, land type (1/2), bun and ji."""
    bdong_cd = str(bdong_cd).strip()
    if len(bdong_cd) != BDONG_CD_LENGTH or not bdong_cd.isdigit():
        raise ValueError("Legal dong code (법정동코드) must be exactly 10 digits.")
    land_type = str(land_type).strip()
    if land_type not in ("1", "2"):
        raise ValueError("Land type must be '1' (일반) or '2' (산).")
    bun_s = str(bun).strip().zfill(4)
    ji_s = str(ji).strip().zfill(4)
    if len(bun_s) != 4 or not bun_s.isdigit() or len(ji_s) != 4 or not ji_s.isdigit():
        raise ValueError("bun / ji must be numbers of at most 4 digits.")
    return normalize_pnu(f"{bdong_cd}{land_type}{bun_s}{ji_s}")


def pnu_to_lawd_cd(pnu: str) -> str:
    """RTMS LAWD_CD (시군구코드 5자리) = PNU 앞 5자리."""
    return normalize_pnu(pnu)[0:LAWD_CD_LENGTH]


def normalize_lawd_cd(lawd_cd: Optional[str]) -> str:
    if not lawd_cd:
        raise ValueError("LAWD_CD must be exactly 5 digits.")
    lawd_cd = lawd_cd.strip()
    if len(lawd_cd) != LAWD_CD_LENGTH or not lawd_cd.isdigit():
        raise ValueError("LAWD_CD must be exactly 5 digits.")
    return lawd_cd


def parse_pnu(
    pnu: Optional[str],
    sigunguCd: Optional[str] = None,
    bjdongCd: Optional[str] = None,
    platGbCd: Optional[str] = None,
    bun: Optional[str] = None,
    ji: Optional[str] = None
) -> tuple[str, str, str, str, str]:
    """Parse PNU (19 digits) to building ledger components, applying overrides and plate code mapping.

    (원본 BDLedger_MCP server.py 의 parse_pnu 를 그대로 옮김)
    """
    if sigunguCd and bjdongCd and platGbCd and bun and ji:
        return sigunguCd, bjdongCd, platGbCd, bun, ji

    if not pnu:
        raise ValueError("Either 'pnu' (19 digits) or all overrides (sigunguCd, bjdongCd, platGbCd, bun, ji) must be provided.")

    pnu = pnu.strip()
    if len(pnu) != 19 or not pnu.isdigit():
        raise ValueError("PNU must be exactly 19 digits.")

    extracted_sigungu = sigunguCd or pnu[0:5]
    extracted_bjdong = bjdongCd or pnu[5:10]

    # Map PNU type to platGbCd: 1(일반대지) -> 0, 2(산) -> 1
    pnu_plat = pnu[10]
    if platGbCd is not None:
        extracted_plat = platGbCd
    else:
        if pnu_plat == "1":
            extracted_plat = "0"
        elif pnu_plat == "2":
            extracted_plat = "1"
        else:
            extracted_plat = "0"

    extracted_bun = bun or pnu[11:15]
    extracted_ji = ji or pnu[15:19]

    return extracted_sigungu, extracted_bjdong, extracted_plat, extracted_bun, extracted_ji
