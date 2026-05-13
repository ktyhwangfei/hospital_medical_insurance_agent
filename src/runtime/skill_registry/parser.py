import re
from dataclasses import dataclass


@dataclass
class MentionResult:
    mentioned_skill_ids: list[str]
    clean_message: str


_MENTION_PATTERN = re.compile(r"@([a-z0-9_]+(?:-[a-z0-9_]+)*)")


def parse_message(message: str) -> MentionResult:
    matches = _MENTION_PATTERN.findall(message)
    clean = _MENTION_PATTERN.sub("", message)
    clean = re.sub(r"\s+", " ", clean).strip()
    return MentionResult(mentioned_skill_ids=matches, clean_message=clean)