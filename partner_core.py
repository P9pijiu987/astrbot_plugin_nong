from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class PartnerCommand:
    action: str
    game: str | None = None


_FIXED_COMMANDS = {
    "伙伴帮助": "help",
    "游戏伙伴帮助": "help",
    "伙伴help": "help",
    "伙伴列表": "list",
    "我的伙伴": "mine",
}

_DYNAMIC_COMMAND = re.compile(
    r"^(?P<action>邀请加入|同意加入|拒绝加入|加入|退出|召集|查看)"
    r"(?P<game>.+?)伙伴(?:\s|$)"
)

# Prevent unrelated group messages from activating this plugin and waking AstrBot.
# AstrBot may already have removed the configured wake prefix before filtering.
PARTNER_FILTER_PATTERN = re.compile(
    r"^[／/]?(?:(?:伙伴帮助|游戏伙伴帮助|伙伴help|伙伴列表|我的伙伴)\s*$|"
    r"(?:邀请加入|同意加入|拒绝加入|加入|退出|召集|查看).+?伙伴(?:\s|$))",
    re.IGNORECASE,
)


def parse_partner_command(message: str) -> PartnerCommand | None:
    """Parse the text after AstrBot has optionally removed its wake prefix."""
    text = unicodedata.normalize("NFKC", str(message or "")).strip()
    if text.startswith("/"):
        text = text[1:].lstrip()
    if text in _FIXED_COMMANDS:
        return PartnerCommand(_FIXED_COMMANDS[text])

    matched = _DYNAMIC_COMMAND.match(text)
    if not matched:
        return None
    return PartnerCommand(matched.group("action"), matched.group("game").strip())


def validate_game_name(game: str, max_length: int) -> tuple[str | None, str | None]:
    name = unicodedata.normalize("NFKC", str(game or "")).strip()
    if not name:
        return None, "游戏名不能为空。"
    if len(name) > max(1, max_length):
        return None, f"游戏名最多 {max(1, max_length)} 个字符。"
    if any(char.isspace() for char in name):
        return None, "游戏名不能包含空格。"
    if any(char in name for char in "/@\\"):
        return None, "游戏名不能包含 /、@或反斜杠。"
    return name, None


def game_key(game: str) -> str:
    return unicodedata.normalize("NFKC", game).casefold()
