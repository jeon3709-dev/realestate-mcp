import pytest

from realestate_mcp import pnu as pnu_mod

GENERAL = "1168010100108220002"  # 서울 강남구 역삼동 822-2 (일반)
MOUNTAIN = "1168010100200120000"  # 산 12


def test_split_general():
    parts = pnu_mod.split_pnu(GENERAL)
    assert parts.sigungu_cd == "11680"
    assert parts.bjdong_cd == "10100"
    assert parts.land_type == "1"
    assert parts.bun == "0822"
    assert parts.ji == "0002"
    assert parts.lawd_cd == "11680"
    assert parts.bdong_cd == "1168010100"
    assert parts.plat_gb_cd == "0"
    assert parts.is_mountain is False
    assert parts.jibun == "822-2"


def test_split_mountain():
    parts = pnu_mod.split_pnu(MOUNTAIN)
    assert parts.land_type == "2"
    assert parts.plat_gb_cd == "1"
    assert parts.is_mountain is True
    assert parts.jibun == "산 12"


@pytest.mark.parametrize("bad", ["", "123", "11680101001082200021", "116801010010822000A", None])
def test_invalid_pnu(bad):
    assert pnu_mod.is_valid_pnu(bad) is False
    with pytest.raises(ValueError, match="19 digits"):
        pnu_mod.normalize_pnu(bad)


def test_normalize_strips_whitespace():
    assert pnu_mod.normalize_pnu(f"  {GENERAL}\n") == GENERAL


def test_build_roundtrip():
    assert pnu_mod.build_pnu("1168010100", "1", 822, 2) == GENERAL
    assert pnu_mod.build_pnu("1168010100", "2", "12", "0") == MOUNTAIN
    with pytest.raises(ValueError):
        pnu_mod.build_pnu("11680", "1", 1, 0)
    with pytest.raises(ValueError):
        pnu_mod.build_pnu("1168010100", "3", 1, 0)
    with pytest.raises(ValueError):
        pnu_mod.build_pnu("1168010100", "1", 12345, 0)


def test_pnu_to_lawd_cd():
    assert pnu_mod.pnu_to_lawd_cd(GENERAL) == "11680"
    with pytest.raises(ValueError):
        pnu_mod.pnu_to_lawd_cd("1168")


def test_normalize_lawd_cd():
    assert pnu_mod.normalize_lawd_cd(" 11140 ") == "11140"
    for bad in ("1114", "111400", "1114A", None):
        with pytest.raises(ValueError):
            pnu_mod.normalize_lawd_cd(bad)


def test_parse_pnu_matches_original_semantics():
    assert pnu_mod.parse_pnu(GENERAL) == ("11680", "10100", "0", "0822", "0002")
    assert pnu_mod.parse_pnu(MOUNTAIN) == ("11680", "10100", "1", "0012", "0000")
    # 전체 오버라이드가 있으면 PNU 없이도 그대로 반환
    assert pnu_mod.parse_pnu(None, "11110", "10100", "0", "1", "2") == ("11110", "10100", "0", "1", "2")
    # 일부 오버라이드
    assert pnu_mod.parse_pnu(GENERAL, bun="0001") == ("11680", "10100", "0", "0001", "0002")
    with pytest.raises(ValueError, match="Either 'pnu'"):
        pnu_mod.parse_pnu(None)
    with pytest.raises(ValueError, match="19 digits"):
        pnu_mod.parse_pnu("123")
