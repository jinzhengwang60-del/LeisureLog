"""All entry points must deliver the wardrobe assets from an installed application."""

pytest_plugins = ["tests.test_pipeline"]


def test_all_pages_and_independent_skin_assets_are_served(app_context):
    client, _, _, _, _ = app_context
    for url in [
        "/", "/review", "/unclassified", "/statistics", "/projects", "/games",
        "/game-preferences", "/library",
    ]:
        response = client.get(url)
        assert response.status_code == 200, url
        assert 'id="skin-stylesheet"' in response.text
        assert "/static/appearance-init.js" in response.text
        assert "/static/sky-clock.js" in response.text
        assert "/static/appearance.css" in response.text
        assert "/static/motion.js" in response.text
        assert 'id="motion-stylesheet"' in response.text
    for asset in [
        "appearance-init.js", "sky-clock.js", "theme.js", "appearance.css", "skin-base.css",
        "motion.js", "motion.css",
        "style.css",
        "skins/minimal.css", "skins/terminal.css", "retro-disk.svg",
        "skins/sunny.css", "skins/editorial.css", "skins/arcade.css",
        "sunny-afternoon.png", "arcade-world.svg",
        "skins/sunny.css", "skins/editorial.css", "skins/arcade.css",
        "sunny-afternoon.png", "arcade-world.svg",
    ]:
        response = client.get(f"/static/{asset}")
        assert response.status_code == 200, asset
        if asset.startswith("skins/"):
            assert "skin-base.css" in response.text
            assert "style.css" not in response.text
