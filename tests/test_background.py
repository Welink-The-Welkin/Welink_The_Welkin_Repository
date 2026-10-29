from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.main import create_app


ROOT = Path(__file__).parents[1]
BACKGROUND_DIR = ROOT / "assets" / "backgrounds"


@pytest.mark.parametrize(
    ("route", "filename"),
    [
        ("home", "过去与现在.jpeg"),
        ("stories", "过去与现在.jpeg"),
        ("game", "流浪者正面.jpeg"),
        ("intro", "流浪者背面.jpeg"),
    ],
)
def test_fixed_background_routes_return_the_requested_image(tmp_path, route, filename):
    client = TestClient(create_app(database_path_override=tmp_path / "background.db", demo_mode_override="offline"))

    response = client.get(f"/api/background/{route}")

    assert response.status_code == 200
    assert response.content == (BACKGROUND_DIR / filename).read_bytes()


def test_chat_background_is_fresh_for_each_request(tmp_path):
    client = TestClient(create_app(database_path_override=tmp_path / "chat-background.db", demo_mode_override="offline"))
    allowed = {
        (BACKGROUND_DIR / filename).read_bytes()
        for filename in (
            "流浪者与兰那罗3.jpeg",
            "流浪者背面.jpeg",
            "流浪者正面.jpeg",
            "倾帽.jpg",
            "咕咕嘎嘎.jpg",
        )
    }

    responses = [client.get("/api/background/chat") for _ in range(3)]

    assert all(response.status_code == 200 for response in responses)
    assert all(response.content in allowed for response in responses)
    assert all(response.headers["cache-control"] == "no-store" for response in responses)


def test_frontend_cache_busts_random_chat_background_requests():
    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert "function backgroundUrl(routeKey)" in script
    chat_url_block = script.split("function backgroundUrl(routeKey)", 1)[1].split("function applyBackground", 1)[0]
    assert "routeKey === \"chat\"" in chat_url_block
    assert "Date.now()" in chat_url_block


def test_random_chat_pool_uses_the_replacement_asset_name():
    background_script = (ROOT / "backend" / "app" / "api" / "routes" / "background.py").read_text(encoding="utf-8")
    legacy_filename = "流浪者与兰那罗" + "2" + ".jpeg"

    assert "流浪者与兰那罗3.jpeg" in background_script
    assert legacy_filename not in background_script
    assert not (BACKGROUND_DIR / legacy_filename).exists()
    assert (BACKGROUND_DIR / "流浪者与兰那罗3.jpeg").exists()
