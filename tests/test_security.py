import io
import logging
from pathlib import Path

import httpx
import respx

from realestate_mcp import common
from realestate_mcp.tools import bldrgst
from tests import fixtures as fx

ROOT = Path(__file__).resolve().parent.parent


def test_logs_are_masked_and_httpx_quiet(fake_keys):
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    root = logging.getLogger()
    root.addHandler(handler)
    try:
        common.configure_logging()
        assert logging.getLogger("httpx").level == logging.WARNING
        logging.getLogger("bdledger-mcp").error(
            "Requesting %s with params: %s", "https://apis.data.go.kr/x", {"serviceKey": fake_keys["bldrgst"]}
        )
    finally:
        root.removeHandler(handler)
    out = stream.getvalue()
    assert "Requesting" in out
    for key in fake_keys.values():
        assert key not in out


@respx.mock
async def test_tool_error_messages_never_contain_keys(fake_keys, caplog):
    caplog.set_level(logging.INFO)
    respx.get(f"{bldrgst.BASE_URL}/getBrTitleInfo").mock(
        side_effect=httpx.ConnectError(f"proxy refused serviceKey={fake_keys['bldrgst']}")
    )
    res = await bldrgst.br_get_title(pnu=fx.PNU)
    assert res["status"] == "NETWORK_ERROR"
    assert fake_keys["bldrgst"] not in res["message"]


def test_env_file_is_gitignored():
    lines = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in lines
    assert "!.env.example" in lines


def test_env_example_has_no_real_keys():
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.startswith(("VWORLD_API_KEY=", "BLDRGST_API_KEY=", "MOLIT_SERVICE_KEY=")):
            assert line.split("=", 1)[1] in {"your_api_key_here", "your_service_key_here"}
