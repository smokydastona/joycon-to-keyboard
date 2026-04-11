"""Tests for _version.py auto-generated metadata."""

from __future__ import annotations

import re

from joycon_helper._version import __build_date__, __version__


class TestVersion:
    def test_semver_format(self):
        """Version string must look like MAJOR.MINOR.PATCH."""
        assert re.match(r"^\d+\.\d+\.\d+$", __version__), (
            f"Unexpected version format: {__version__}"
        )

    def test_build_date_iso8601(self):
        """Build date should be ISO-8601 UTC ending with Z."""
        assert __build_date__.endswith("Z")
        assert "T" in __build_date__
