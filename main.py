from __future__ import annotations

from typing import Any

import astrbot.api.message_components as Comp
from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star


class NongPartnerPlugin(Star):
    """农伙伴：加入、召集、退出。"""

    def __init__(self, context: Context):
        super().__init__(context)

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    @filter.command("加入农伙伴")
    async def join_partner(self, event: AstrMessageEvent):
        """/加入农伙伴 [@群友（可选）]：将自己或被@用户加入农伙伴名单。"""
        group_id = self._get_group_id(event)
        if group_id is None:
            yield event.plain_result("该指令仅支持群聊使用。")
            return

        target_ids = self._extract_mentioned_user_ids(event)
        if not target_ids:
            sender_id = self._get_sender_id(event)
            if sender_id is None:
                yield event.plain_result("无法识别发送者身份，加入失败。")
                return
            target_ids = [sender_id]

        members = await self._get_group_members(group_id)
        before = set(members)
        members_set = set(members)
        members_set.update(target_ids)
        await self._save_group_members(group_id, sorted(members_set))

        added = [uid for uid in target_ids if uid not in before]
        if not added:
            yield event.plain_result("目标用户已在农伙伴名单中。")
            return

        chain: list[Any] = [Comp.Plain("已加入农伙伴：")]
        for uid in added:
            chain.extend([Comp.At(qq=uid), Comp.Plain(" ")])
        chain.append(Comp.Plain(f"\n当前农伙伴人数：{len(members_set)}"))
        yield event.chain_result(chain)

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    @filter.command("召集农伙伴")
    async def summon_partner(self, event: AstrMessageEvent):
        """/召集农伙伴：一键 @ 当前群内所有农伙伴。"""
        group_id = self._get_group_id(event)
        if group_id is None:
            yield event.plain_result("该指令仅支持群聊使用。")
            return

        members = await self._get_group_members(group_id)
        if not members:
            yield event.plain_result("当前还没有农伙伴，先使用 /加入农伙伴 吧。")
            return

        chain: list[Any] = [Comp.Plain("农伙伴集合：")]
        for uid in members:
            chain.extend([Comp.At(qq=uid), Comp.Plain(" ")])
        yield event.chain_result(chain)

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    @filter.command("退出农伙伴")
    async def leave_partner(self, event: AstrMessageEvent):
        """/退出农伙伴：将自己移出当前群的农伙伴名单。"""
        group_id = self._get_group_id(event)
        sender_id = self._get_sender_id(event)
        if group_id is None:
            yield event.plain_result("该指令仅支持群聊使用。")
            return
        if sender_id is None:
            yield event.plain_result("无法识别发送者身份，退出失败。")
            return

        members = await self._get_group_members(group_id)
        if sender_id not in members:
            yield event.plain_result("你当前不在农伙伴名单中。")
            return

        members = [uid for uid in members if uid != sender_id]
        await self._save_group_members(group_id, members)
        yield event.plain_result(f"已将你移出农伙伴名单，当前人数：{len(members)}")

    async def _get_group_members(self, group_id: str) -> list[str]:
        key = self._group_members_key(group_id)
        raw = await self.get_kv_data(key, [])
        if not isinstance(raw, list):
            logger.warning("农伙伴存储格式异常，已重置。group_id=%s", group_id)
            return []
        return [str(uid) for uid in raw if str(uid).strip()]

    async def _save_group_members(self, group_id: str, members: list[str]) -> None:
        key = self._group_members_key(group_id)
        normalized = sorted({str(uid) for uid in members if str(uid).strip()})
        await self.put_kv_data(key, normalized)

    @staticmethod
    def _group_members_key(group_id: str) -> str:
        return f"nong_partners:{group_id}"

    @staticmethod
    def _get_sender_id(event: AstrMessageEvent) -> str | None:
        try:
            sender_id = event.get_sender_id()
        except Exception:
            return None
        if sender_id is None:
            return None
        return str(sender_id)

    @staticmethod
    def _get_group_id(event: AstrMessageEvent) -> str | None:
        try:
            group_id = event.get_group_id()
        except Exception:
            return None
        if group_id is None:
            return None
        return str(group_id)

    @staticmethod
    def _extract_mentioned_user_ids(event: AstrMessageEvent) -> list[str]:
        segments = NongPartnerPlugin._get_message_segments(event)
        results: list[str] = []
        for seg in segments:
            qq = NongPartnerPlugin._extract_qq_from_segment(seg)
            if qq:
                results.append(qq)
        return sorted(set(results))

    @staticmethod
    def _get_message_segments(event: AstrMessageEvent) -> list[Any]:
        try:
            getter = getattr(event, "get_messages", None)
            if callable(getter):
                result = getter()
                if isinstance(result, list):
                    return result
        except Exception:
            pass

        message = getattr(event, "message", None)
        if isinstance(message, list):
            return message
        return []

    @staticmethod
    def _extract_qq_from_segment(seg: Any) -> str | None:
        qq = getattr(seg, "qq", None)
        if qq is not None:
            text = str(qq).strip()
            return text or None

        if isinstance(seg, dict):
            seg_type = str(seg.get("type", "")).lower()
            if seg_type == "at":
                data = seg.get("data", {})
                if isinstance(data, dict):
                    qq_value = data.get("qq")
                    if qq_value is not None:
                        text = str(qq_value).strip()
                        return text or None
        return None

    async def terminate(self):
        logger.info("农伙伴插件已停用。")
