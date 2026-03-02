"""Shared pytest fixtures for GenesisTools test suite."""
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _no_sleep(request):
    """Auto-patch time.sleep in gemini_cli to keep retry tests fast."""
    if "test_gemini_cli" in request.fspath.basename:
        with patch("genesis_tools.gemini_cli.time.sleep"):
            yield
    else:
        yield
