"""
Unit tests for OutputParser.

Tests cover parsing behavior of [CONCLUSION] and [OFFICE_NOTE] markers:
- Normal parse with both markers
- Missing CONCLUSION marker
- Missing OFFICE_NOTE marker
- Empty input
- Duplicate markers (first occurrence wins)
"""

import pytest

from skills.settlement_explain_skill.output_parser import OutputParser


class TestOutputParser:
    """OutputParser.parse() unit tests."""

    def test_normal_parse(self):
        """Both [CONCLUSION] and [OFFICE_NOTE] present."""
        raw = "[CONCLUSION]\n这是结论\n[OFFICE_NOTE]\n这是备注"
        result = OutputParser.parse(raw)
        assert result.conclusion == "这是结论"
        assert result.office_note == "这是备注"
        assert result.raw_output == raw

    def test_missing_conclusion_marker(self):
        """Only [OFFICE_NOTE] present → conclusion should be empty."""
        raw = "[OFFICE_NOTE]\n这是备注"
        result = OutputParser.parse(raw)
        assert result.conclusion == ""
        assert result.office_note == "这是备注"

    def test_missing_office_note_marker(self):
        """Only [CONCLUSION] present → office_note should be empty."""
        raw = "[CONCLUSION]\n这是结论"
        result = OutputParser.parse(raw)
        assert result.conclusion == "这是结论"
        assert result.office_note == ""

    def test_empty_input(self):
        """Empty string → both fields empty."""
        result = OutputParser.parse("")
        assert result.conclusion == ""
        assert result.office_note == ""
        assert result.raw_output == ""

    def test_duplicate_markers_take_first(self):
        """Duplicate markers → first [CONCLUSION] and first [OFFICE_NOTE] win."""
        raw = (
            "[CONCLUSION]\n第一个结论\n"
            "[OFFICE_NOTE]\n第一个备注\n"
            "[CONCLUSION]\n第二个结论\n"
            "[OFFICE_NOTE]\n第二个备注"
        )
        result = OutputParser.parse(raw)
        assert result.conclusion == "第一个结论"
        assert result.office_note == "第一个备注\n[CONCLUSION]\n第二个结论\n[OFFICE_NOTE]\n第二个备注"
