"""Tests for app-switcher rule validation and matching."""

from __future__ import annotations

import json
import os
from unittest.mock import patch

import pytest

from joycon_helper.app_switcher import _MAX_EXE_LEN, _MAX_RULES, load_rules


class TestLoadRules:
    """Verify rule loading with validation and limits."""

    def test_valid_rules(self, tmp_path):
        rules_file = tmp_path / "app_profiles.json"
        rules = [
            {"exe": "game.exe", "slot": 0},
            {"exe": "notepad.exe", "slot": 1},
        ]
        rules_file.write_text(json.dumps(rules), encoding="utf-8")
        with patch("joycon_helper.app_switcher._rules_path", return_value=rules_file):
            result = load_rules()
        assert len(result) == 2
        assert result[0]["exe"] == "game.exe"

    def test_invalid_slot_rejected(self, tmp_path):
        rules_file = tmp_path / "app_profiles.json"
        rules = [{"exe": "game.exe", "slot": 5}]
        rules_file.write_text(json.dumps(rules), encoding="utf-8")
        with patch("joycon_helper.app_switcher._rules_path", return_value=rules_file):
            result = load_rules()
        assert len(result) == 0

    def test_missing_exe_rejected(self, tmp_path):
        rules_file = tmp_path / "app_profiles.json"
        rules = [{"slot": 0}]
        rules_file.write_text(json.dumps(rules), encoding="utf-8")
        with patch("joycon_helper.app_switcher._rules_path", return_value=rules_file):
            result = load_rules()
        assert len(result) == 0

    def test_exe_too_long_rejected(self, tmp_path):
        rules_file = tmp_path / "app_profiles.json"
        rules = [{"exe": "a" * (_MAX_EXE_LEN + 1), "slot": 0}]
        rules_file.write_text(json.dumps(rules), encoding="utf-8")
        with patch("joycon_helper.app_switcher._rules_path", return_value=rules_file):
            result = load_rules()
        assert len(result) == 0

    def test_max_rules_cap(self, tmp_path):
        rules_file = tmp_path / "app_profiles.json"
        rules = [{"exe": f"app{i}.exe", "slot": i % 4} for i in range(_MAX_RULES + 10)]
        rules_file.write_text(json.dumps(rules), encoding="utf-8")
        with patch("joycon_helper.app_switcher._rules_path", return_value=rules_file):
            result = load_rules()
        assert len(result) == _MAX_RULES

    def test_absolute_path_rule_accepted(self, tmp_path):
        rules_file = tmp_path / "app_profiles.json"
        rules = [{"exe": "C:\\Games\\game.exe", "slot": 2}]
        rules_file.write_text(json.dumps(rules), encoding="utf-8")
        with patch("joycon_helper.app_switcher._rules_path", return_value=rules_file):
            result = load_rules()
        assert len(result) == 1
        assert result[0]["exe"] == "C:\\Games\\game.exe"

    def test_missing_file_returns_empty(self, tmp_path):
        rules_file = tmp_path / "nonexistent.json"
        with patch("joycon_helper.app_switcher._rules_path", return_value=rules_file):
            result = load_rules()
        assert result == []

    def test_non_dict_entries_skipped(self, tmp_path):
        rules_file = tmp_path / "app_profiles.json"
        rules = [{"exe": "good.exe", "slot": 0}, "bad_entry", 42]
        rules_file.write_text(json.dumps(rules), encoding="utf-8")
        with patch("joycon_helper.app_switcher._rules_path", return_value=rules_file):
            result = load_rules()
        assert len(result) == 1
