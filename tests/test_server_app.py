from starlette.testclient import TestClient

import server


def test_http_app_health_and_oauth_404():
    app = server.build_http_app(server.create_server(["server.py", "sse"]))
    with TestClient(app) as client:
        r = client.get("/")
        assert r.status_code == 200 and r.text == "ok"
        assert r.headers.get("x-accel-buffering") == "no"
        for path in (
            "/.well-known/oauth-authorization-server",
            "/.well-known/oauth-protected-resource",
            "/.well-known/mcp-configuration",
        ):
            r = client.get(path)
            assert r.status_code == 404
            assert r.json()["status"] == "no_auth_required"
