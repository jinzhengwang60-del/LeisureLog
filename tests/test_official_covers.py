"""An application name alone cannot satisfy a title-scoped identification rule."""

import pytest

from leisurelog.plugin_api import Game
from leisurelog_plugins.playnite import CoverIndex


@pytest.mark.parametrize("app", ["javaw.exe", "msedge.exe", "launcher.exe"])
def test_cover_requires_title_evidence_for_a_conditional_program(app):
    game = Game("one", "Example Game", True, "", (), ((app, "Example"),))
    index = CoverIndex((game,), {})
    assert index.game_for("Unrelated title", [app]) is None
    assert index.game_for("Example Game", [app]) is game


def test_an_unconditional_program_can_still_identify_a_renamed_game(tmp_path):
    conditional = Game("one", "Conditional", True, "", (), (("game.exe", "Example"),))
    direct = Game("two", "Translated title", True, "", (), (("game.exe", ""),))
    cover = tmp_path / "cover.jpg"
    index = CoverIndex((conditional, direct), {"two": cover})
    assert index.cover_for("Old localized title", ["GAME.EXE"]) == ("two", cover)
