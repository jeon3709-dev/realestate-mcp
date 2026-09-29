import asyncio

import server

EXPECTED_TOOLS = {
    # VWorld (6)
    "vworld_search", "vworld_geocode", "vworld_reverse_geocode", "vworld_get_parcel",
    "vworld_get_landuse_zone", "vworld_get_individual_price",
    # 건축물대장 (10)
    "br_get_basis_ouln", "br_get_recap_title", "br_get_title", "br_get_floor_ouln", "br_get_atch_jibun",
    "br_get_expos_pubuse_area", "br_get_wclf", "br_get_house_price", "br_get_expos", "br_get_jijigu",
    # 실거래가 (3)
    "rtms_search_land_transactions", "rtms_search_commercial_transactions", "rtms_search_apartment_transactions",
    # 통합 (2)
    "site_profile", "health_check",
}


def test_registered_tools_exact():
    tools = asyncio.run(server.create_server(["server.py", "sse"]).list_tools())
    names = [t.name for t in tools]
    assert len(names) == 21
    assert set(names) == EXPECTED_TOOLS
    assert len(set(names)) == len(names)


def test_legacy_health_tools_removed():
    tools = asyncio.run(server.mcp.list_tools())
    names = {t.name for t in tools}
    assert not {"vworld_health_check", "br_health_check", "search_land_transactions"} & names


def test_rtms_schema_backward_compatible():
    tools = {t.name: t for t in asyncio.run(server.mcp.list_tools())}
    schema = tools["rtms_search_land_transactions"].inputSchema
    props = schema["properties"]
    for p in ("sigungu", "dong", "sido", "months_back", "exclude_share_deals", "exclude_cancelled", "zone_filter", "pnu", "lawd_cd"):
        assert p in props
    assert props["months_back"]["default"] == 36
    assert not schema.get("required")
