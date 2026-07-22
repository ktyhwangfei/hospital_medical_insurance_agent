"""
LLM 输出解析器 — 将 LLM 原始输出解析为结论（conclusion）和内部备注（office_note）。

通过 `[CONCLUSION]` 和 `[OFFICE_NOTE]` 标记切分原始输出。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ParsedOutput:
    """解析后的结构化输出。"""
    conclusion: str = ""
    office_note: str = ""
    raw_output: str = ""


class OutputParser:
    """LLM 输出解析器 — 按标记切分原始输出，不涉及内容校验。"""

    CONCLUSION_MARKER = "[CONCLUSION]"
    OFFICE_NOTE_MARKER = "[OFFICE_NOTE]"

    @classmethod
    def parse(cls, raw_output: str) -> ParsedOutput:
        """
        按标记解析 LLM 原始输出。

        Args:
            raw_output: LLM 原始输出文本

        Returns:
            ParsedOutput 结构化结果

        Example:
            >>> OutputParser.parse("[CONCLUSION]\\n结论正文\\n[OFFICE_NOTE]\\n备注正文")
            ParsedOutput(conclusion="结论正文", office_note="备注正文", raw_output=...)
        """
        if not raw_output:
            return ParsedOutput(raw_output=raw_output)

        conclusion = ""
        office_note = ""

        # 取第一个 [CONCLUSION] 到 [OFFICE_NOTE] 之间的文本
        c_start = raw_output.find(cls.CONCLUSION_MARKER)
        if c_start != -1:
            c_start += len(cls.CONCLUSION_MARKER)
            c_end = raw_output.find(cls.OFFICE_NOTE_MARKER, c_start)
            if c_end != -1:
                conclusion = raw_output[c_start:c_end].strip()
            else:
                conclusion = raw_output[c_start:].strip()

        # 取第一个 [OFFICE_NOTE] 之后的所有文本
        o_start = raw_output.find(cls.OFFICE_NOTE_MARKER)
        if o_start != -1:
            o_start += len(cls.OFFICE_NOTE_MARKER)
            office_note = raw_output[o_start:].strip()

        return ParsedOutput(
            conclusion=conclusion,
            office_note=office_note,
            raw_output=raw_output,
        )
