from __future__ import annotations

import asyncio
import math
import time
from collections import defaultdict
from typing import Any

import astrbot.api.message_components as Comp
from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star

from .partner_core import (
    PARTNER_FILTER_PATTERN,
    PartnerCommand,
    game_key,
    parse_partner_command,
    validate_game_name,
)


class NongPartnerPlugin(Star):
    """游戏伙伴：为每个群维护任意游戏的伙伴名单。"""

    STATE_VERSION = 2

    def __init__(self, context: Context, config: AstrBotConfig | None = None):
        super().__init__(context)
        self.config = config or {}
        self._group_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    @filter.regex(PARTNER_FILTER_PATTERN)
    async def on_group_message(self, event: AstrMessageEvent):
        command = parse_partner_command(event.message_str)
        if command is None:
            return

        event.stop_event()
        try:
            result = await self._dispatch(event, command)
        except Exception:
            logger.exception("处理游戏伙伴指令时发生异常")
            result = event.plain_result("指令处理失败，请稍后再试。")
        if result is not None:
            yield result

    async def _dispatch(self, event: AstrMessageEvent, command: PartnerCommand):
        group_id = self._get_group_id(event)
        sender_id = self._get_sender_id(event)
        if group_id is None or sender_id is None:
            return event.plain_result("无法识别群或发送者身份。")

        if command.action == "help":
            return event.plain_result(self._help_text())
        if command.action == "list":
            return await self._list_games(event, group_id)
        if command.action == "mine":
            return await self._list_mine(event, group_id, sender_id)

        game, error = validate_game_name(
            command.game or "", self._int_config("max_game_name_length", 16, minimum=1)
        )
        if error:
            return event.plain_result(error)
        assert game is not None

        handlers = {
            "加入": self._join,
            "邀请加入": self._invite,
            "同意加入": self._accept,
            "拒绝加入": self._reject,
            "退出": self._leave,
            "召集": self._summon,
            "查看": self._show,
        }
        handler = handlers.get(command.action)
        if handler is None:
            return None
        return await handler(event, group_id, sender_id, game)

    async def _join(self, event, group_id: str, sender_id: str, game: str):
        if not self._bool_config("allow_self_join", True) and not event.is_admin():
            return event.plain_result("本群已关闭自助加入，请联系管理员。")
        async with self._group_locks[group_id]:
            state = await self._load_state(group_id)
            record = self._ensure_game(state, game, sender_id)
            if sender_id in record["members"]:
                return event.plain_result(f"你已经是{record['name']}伙伴了。")
            record["members"].append(sender_id)
            record["members"] = sorted(set(record["members"]))
            self._remove_invite(state, game_key(game), sender_id)
            await self._save_state(group_id, state)
            count = len(record["members"])
        return event.plain_result(
            f"加入成功！你现在是{game}伙伴，当前共 {count} 人。"
        )

    async def _invite(self, event, group_id: str, sender_id: str, game: str):
        if not self._bool_config("allow_invite", True) and not event.is_admin():
            return event.plain_result("邀请功能已关闭。")
        self_id = self._get_self_id(event)
        targets = [
            uid
            for uid in self._extract_mentioned_user_ids(event)
            if uid != sender_id and uid != self_id
        ]
        if not targets:
            return event.plain_result(
                f"请在指令后 @ 要邀请的群友：/邀请加入{game}伙伴 @群友"
            )

        minutes = self._int_config("invite_expire_minutes", 10, minimum=1)
        expires_at = time.time() + minutes * 60
        async with self._group_locks[group_id]:
            state = await self._load_state(group_id)
            record = self._ensure_game(state, game, sender_id)
            if (
                self._bool_config("invite_requires_membership", False)
                and sender_id not in record["members"]
                and not event.is_admin()
            ):
                return event.plain_result(f"只有{game}伙伴才能邀请别人加入。")
            pending = state["invites"].setdefault(game_key(game), {})
            invited = []
            already_members = []
            for uid in targets:
                if uid in record["members"]:
                    already_members.append(uid)
                    continue
                pending[uid] = {"inviter": sender_id, "expires_at": expires_at}
                invited.append(uid)
            if invited:
                await self._save_state(group_id, state)

        if not invited:
            return event.plain_result("被 @ 的群友已经都在该伙伴名单中。")
        chain: list[Any] = [Comp.Plain(f"{game}伙伴邀请：")]
        for uid in invited:
            chain.extend([Comp.At(qq=uid), Comp.Plain(" ")])
        chain.append(
            Comp.Plain(
                f"\n请在 {minutes} 分钟内输入 /同意加入{game}伙伴；"
                f"不想加入可输入 /拒绝加入{game}伙伴。"
            )
        )
        if already_members:
            chain.append(Comp.Plain(f"\n已忽略 {len(already_members)} 位现有成员。"))
        return event.chain_result(chain)

    async def _accept(self, event, group_id: str, sender_id: str, game: str):
        async with self._group_locks[group_id]:
            state = await self._load_state(group_id)
            key = game_key(game)
            invite = state["invites"].get(key, {}).get(sender_id)
            if not invite:
                return event.plain_result(f"你没有待处理的{game}伙伴邀请。")
            if float(invite.get("expires_at", 0)) <= time.time():
                self._remove_invite(state, key, sender_id)
                await self._save_state(group_id, state)
                return event.plain_result("这条邀请已过期，请让群友重新邀请。")
            record = self._ensure_game(state, game, str(invite.get("inviter", "")))
            record["members"] = sorted(set(record["members"] + [sender_id]))
            self._remove_invite(state, key, sender_id)
            await self._save_state(group_id, state)
            count = len(record["members"])
        return event.plain_result(
            f"已同意邀请！你现在是{record['name']}伙伴，"
            f"当前共 {count} 人。"
        )

    async def _reject(self, event, group_id: str, sender_id: str, game: str):
        async with self._group_locks[group_id]:
            state = await self._load_state(group_id)
            key = game_key(game)
            if sender_id not in state["invites"].get(key, {}):
                return event.plain_result(f"你没有待处理的{game}伙伴邀请。")
            self._remove_invite(state, key, sender_id)
            await self._save_state(group_id, state)
        return event.plain_result(f"已拒绝加入{game}伙伴。")

    async def _leave(self, event, group_id: str, sender_id: str, game: str):
        async with self._group_locks[group_id]:
            state = await self._load_state(group_id)
            record = state["games"].get(game_key(game))
            if not record or sender_id not in record["members"]:
                return event.plain_result(f"你当前不是{game}伙伴。")
            record["members"].remove(sender_id)
            await self._save_state(group_id, state)
            count = len(record["members"])
        return event.plain_result(f"已退出{record['name']}伙伴，当前还有 {count} 人。")

    async def _summon(self, event, group_id: str, sender_id: str, game: str):
        key = game_key(game)
        now = time.time()
        async with self._group_locks[group_id]:
            state = await self._load_state(group_id)
            record = state["games"].get(key)
            if not record or not record["members"]:
                return event.plain_result(
                    f"当前还没有{game}伙伴，先用 /加入{game}伙伴 吧。"
                )
            if sender_id not in record["members"] and not (
                event.is_admin()
                and self._bool_config("admin_can_summon_without_membership", False)
            ):
                return event.plain_result(
                    f"只有{record['name']}伙伴才能召集该游戏的伙伴。"
                )

            cooldown = self._int_config("summon_cooldown_seconds", 300, minimum=0)
            bypass = event.is_admin() and self._bool_config("admin_bypass_cooldown", True)
            cooldowns = state["cooldowns"].setdefault(key, {"global": 0, "users": {}})
            scope = str(self.config.get("cooldown_scope", "game"))
            last = (
                float(cooldowns.get("users", {}).get(sender_id, 0))
                if scope == "user"
                else float(cooldowns.get("global", 0))
            )
            remaining = math.ceil(cooldown - (now - last))
            if not bypass and remaining > 0:
                return event.plain_result(f"召集太频繁啦，请 {remaining} 秒后再试。")
            cooldowns["global"] = now
            cooldowns.setdefault("users", {})[sender_id] = now
            await self._save_state(group_id, state)
            members = list(record["members"])
            display_name = record["name"]

        chain: list[Any] = [Comp.Plain(f"{display_name}伙伴集合！")]
        for uid in members:
            chain.extend([Comp.At(qq=uid), Comp.Plain(" ")])
        return event.chain_result(chain)

    async def _show(self, event, group_id: str, sender_id: str, game: str):
        del sender_id
        async with self._group_locks[group_id]:
            state = await self._load_state(group_id)
            record = state["games"].get(game_key(game))
            if not record or not record["members"]:
                return event.plain_result(f"当前还没有{game}伙伴。")
            members = list(record["members"])
            display_name = record["name"]
        chain: list[Any] = [Comp.Plain(f"{display_name}伙伴（{len(members)} 人）：")]
        for uid in members:
            chain.extend([Comp.At(qq=uid), Comp.Plain(" ")])
        return event.chain_result(chain)

    async def _list_games(self, event, group_id: str):
        async with self._group_locks[group_id]:
            state = await self._load_state(group_id)
            games = sorted(
                ((record["name"], len(record["members"])) for record in state["games"].values()),
                key=lambda item: item[0].casefold(),
            )
        if not games:
            return event.plain_result(
                "本群还没有任何游戏伙伴，"
                "输入 /加入<游戏>伙伴 创建第一个吧。"
            )
        lines = ["本群游戏伙伴："] + [f"• {name}：{count} 人" for name, count in games]
        return event.plain_result("\n".join(lines))

    async def _list_mine(self, event, group_id: str, sender_id: str):
        async with self._group_locks[group_id]:
            state = await self._load_state(group_id)
            names = sorted(
                record["name"]
                for record in state["games"].values()
                if sender_id in record["members"]
            )
        if not names:
            return event.plain_result("你还没有加入任何游戏伙伴。")
        return event.plain_result("你加入的伙伴：" + "、".join(names))

    async def _load_state(self, group_id: str) -> dict[str, Any]:
        raw = await self.get_kv_data(self._state_key(group_id), None)
        if not isinstance(raw, dict) or raw.get("version") != self.STATE_VERSION:
            raw = {
                "version": self.STATE_VERSION,
                "games": {},
                "invites": {},
                "cooldowns": {},
                "migrated_nong": False,
            }
        if not isinstance(raw.get("games"), dict):
            raw["games"] = {}
        if not isinstance(raw.get("invites"), dict):
            raw["invites"] = {}
        if not isinstance(raw.get("cooldowns"), dict):
            raw["cooldowns"] = {}

        if not raw.get("migrated_nong"):
            old_members = await self.get_kv_data(f"nong_partners:{group_id}", [])
            if isinstance(old_members, list) and old_members:
                record = self._ensure_game(raw, "农", "migration")
                record["members"] = sorted(
                    {str(uid) for uid in old_members if str(uid).strip()}
                )
            raw["migrated_nong"] = True
            await self._save_state(group_id, raw)
        return raw

    async def _save_state(self, group_id: str, state: dict[str, Any]) -> None:
        await self.put_kv_data(self._state_key(group_id), state)

    @staticmethod
    def _ensure_game(state: dict[str, Any], game: str, creator: str) -> dict[str, Any]:
        key = game_key(game)
        record = state["games"].setdefault(
            key,
            {
                "name": game,
                "members": [],
                "created_by": creator,
                "created_at": time.time(),
            },
        )
        record.setdefault("name", game)
        record.setdefault("members", [])
        return record

    @staticmethod
    def _remove_invite(state: dict[str, Any], key: str, user_id: str) -> None:
        pending = state["invites"].get(key)
        if not isinstance(pending, dict):
            return
        pending.pop(user_id, None)
        if not pending:
            state["invites"].pop(key, None)

    def _help_text(self) -> str:
        cooldown = self._int_config("summon_cooldown_seconds", 300, minimum=0)
        return (
            "【游戏伙伴帮助】\n"
            "把 <游戏> 换成农、原神、LOL 等任意游戏名：\n"
            "• /加入<游戏>伙伴：自助加入\n"
            "• /邀请加入<游戏>伙伴 @群友：发送邀请\n"
            "• /同意加入<游戏>伙伴：接受邀请\n"
            "• /拒绝加入<游戏>伙伴：拒绝邀请\n"
            "• /退出<游戏>伙伴：退出名单\n"
            "• /召集<游戏>伙伴：@ 该游戏所有伙伴\n"
            "• /查看<游戏>伙伴：查看成员\n"
            "• /伙伴列表：查看本群的全部游戏\n"
            "• /我的伙伴：查看自己加入的游戏\n"
            f"\n只有该游戏伙伴能召集；当前召集冷却为 {cooldown} 秒。"
        )

    def _bool_config(self, key: str, default: bool) -> bool:
        value = self.config.get(key, default)
        return value if isinstance(value, bool) else default

    def _int_config(self, key: str, default: int, minimum: int = 0) -> int:
        try:
            return max(minimum, int(self.config.get(key, default)))
        except (TypeError, ValueError):
            return max(minimum, default)

    @staticmethod
    def _state_key(group_id: str) -> str:
        return f"game_partners:v2:{group_id}"

    @staticmethod
    def _get_sender_id(event: AstrMessageEvent) -> str | None:
        try:
            value = event.get_sender_id()
            return str(value) if value is not None else None
        except Exception:
            return None

    @staticmethod
    def _get_group_id(event: AstrMessageEvent) -> str | None:
        try:
            value = event.get_group_id()
            return str(value) if value is not None else None
        except Exception:
            return None

    @staticmethod
    def _get_self_id(event: AstrMessageEvent) -> str | None:
        try:
            value = event.get_self_id()
            return str(value) if value is not None else None
        except Exception:
            return None

    @staticmethod
    def _extract_mentioned_user_ids(event: AstrMessageEvent) -> list[str]:
        results: set[str] = set()
        try:
            segments = event.get_messages()
        except Exception:
            segments = getattr(event.message_obj, "message", [])
        for segment in segments or []:
            value = getattr(segment, "qq", None)
            if value is None and isinstance(segment, dict):
                data = segment.get("data", {})
                if str(segment.get("type", "")).lower() == "at" and isinstance(data, dict):
                    value = data.get("qq")
            if value is not None and str(value).strip() and str(value) != "all":
                results.add(str(value))
        return sorted(results)

    async def terminate(self):
        logger.info("游戏伙伴插件已停用。")
