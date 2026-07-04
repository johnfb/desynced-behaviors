"""Shared fixtures. Tests need the external game-data extract -- see CLAUDE.md's "What This
Is" for why it lives outside this repo. GAME_DATA_DIR matches the path documented there; if
you've moved it, update both places (or better: this is the one spot worth making
configurable via an env var if that ever becomes annoying)."""

import os

import pytest

from desynced_toolkit import LupaEngine, open_asset_source

GAME_DATA_DIR = os.environ.get(
    "DESYNCED_GAME_DATA", "/home/johnfb/workspaces/desynced-game-data"
)


@pytest.fixture(scope="session")
def engine():
    if not os.path.exists(GAME_DATA_DIR):
        pytest.skip(
            f"game data extract not found at {GAME_DATA_DIR} (set DESYNCED_GAME_DATA)"
        )
    src = open_asset_source(GAME_DATA_DIR)
    return LupaEngine(src)
