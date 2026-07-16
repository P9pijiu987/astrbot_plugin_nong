import asyncio
import importlib
import logging
import sys
import types
import unittest
from collections import defaultdict
from pathlib import Path


class Plain:
    def __init__(self, text):
        self.text = text


class At:
    def __init__(self, qq):
        self.qq = str(qq)


class _Filter:
    class EventMessageType:
        GROUP_MESSAGE = 1

    @staticmethod
    def event_message_type(*_args, **_kwargs):
        return lambda function: function

    @staticmethod
    def regex(*_args, **_kwargs):
        return lambda function: function


def _install_astrbot_stubs():
    astrbot = types.ModuleType("astrbot")
    api = types.ModuleType("astrbot.api")
    components = types.ModuleType("astrbot.api.message_components")
    event = types.ModuleType("astrbot.api.event")
    star = types.ModuleType("astrbot.api.star")

    components.Plain = Plain
    components.At = At
    api.AstrBotConfig = dict
    api.logger = logging.getLogger("plugin-test")
    event.AstrMessageEvent = object
    event.filter = _Filter

    class Star:
        def __init__(self, context):
            self.context = context

    star.Context = object
    star.Star = Star
    sys.modules.update(
        {
            "astrbot": astrbot,
            "astrbot.api": api,
            "astrbot.api.message_components": components,
            "astrbot.api.event": event,
            "astrbot.api.star": star,
        }
    )


_install_astrbot_stubs()
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
plugin_module = importlib.import_module("astrbot_plugin_nong.main")


class FakeEvent:
    def __init__(self, sender="1", mentions=None, admin=False):
        self.sender = sender
        self.mentions = mentions or []
        self.admin = admin

    def is_admin(self):
        return self.admin

    def get_messages(self):
        return [At(uid) for uid in self.mentions]

    def get_self_id(self):
        return "999"

    def plain_result(self, text):
        return ("plain", text)

    def chain_result(self, chain):
        return ("chain", chain)


class FakePlugin(plugin_module.NongPartnerPlugin):
    def __init__(self, config=None):
        self.config = config or {}
        self._group_locks = defaultdict(asyncio.Lock)
        self.storage = {}

    async def get_kv_data(self, key, default=None):
        return self.storage.get(key, default)

    async def put_kv_data(self, key, value):
        self.storage[key] = value


class PluginLogicTests(unittest.IsolatedAsyncioTestCase):
    async def test_join_invite_accept_and_member_summon(self):
        plugin = FakePlugin({"summon_cooldown_seconds": 0})
        requested = await plugin._join(FakeEvent("1"), "group", "1", "原神")
        self.assertIn("已申请创建", requested[1])

        approved = await plugin._approve_creation(
            FakeEvent("10", admin=True), "group", "10", "原神"
        )
        self.assertEqual(approved[0], "chain")

        invited = await plugin._invite(
            FakeEvent("1", mentions=["2"]), "group", "1", "原神"
        )
        self.assertEqual(invited[0], "chain")

        accepted = await plugin._accept(FakeEvent("2"), "group", "2", "原神")
        self.assertIn("已同意邀请", accepted[1])

        summoned = await plugin._summon(FakeEvent("2"), "group", "2", "原神")
        mentioned = [part.qq for part in summoned[1] if isinstance(part, At)]
        self.assertEqual(mentioned, ["1", "2"])

    async def test_non_member_cannot_summon(self):
        plugin = FakePlugin(
            {"summon_cooldown_seconds": 0, "require_creation_approval": False}
        )
        await plugin._join(FakeEvent("1"), "group", "1", "农")
        result = await plugin._summon(FakeEvent("2"), "group", "2", "农")
        self.assertIn("只有农伙伴", result[1])

    async def test_old_nong_members_are_migrated(self):
        plugin = FakePlugin()
        plugin.storage["nong_partners:group"] = ["7", "8"]
        state = await plugin._load_state("group")
        self.assertEqual(state["games"]["农"]["members"], ["7", "8"])

    async def test_only_admin_can_approve_and_delete(self):
        plugin = FakePlugin()
        await plugin._join(FakeEvent("1"), "group", "1", "星际")

        denied = await plugin._approve_creation(
            FakeEvent("2"), "group", "2", "星际"
        )
        self.assertIn("只有 AstrBot 管理员", denied[1])

        await plugin._approve_creation(
            FakeEvent("10", admin=True), "group", "10", "星际"
        )
        denied_delete = await plugin._delete_game(
            FakeEvent("2"), "group", "2", "星际"
        )
        self.assertIn("只有 AstrBot 管理员", denied_delete[1])

        deleted = await plugin._delete_game(
            FakeEvent("10", admin=True), "group", "10", "星际"
        )
        self.assertIn("已删除星际伙伴", deleted[1])

    async def test_multiple_requesters_join_after_approval(self):
        plugin = FakePlugin()
        await plugin._join(FakeEvent("1"), "group", "1", "文明")
        await plugin._join(FakeEvent("2"), "group", "2", "文明")
        await plugin._approve_creation(
            FakeEvent("10", admin=True), "group", "10", "文明"
        )
        state = await plugin._load_state("group")
        self.assertEqual(state["games"]["文明"]["members"], ["1", "2"])

    async def test_disabling_review_promotes_existing_request(self):
        plugin = FakePlugin()
        await plugin._join(FakeEvent("1"), "group", "1", "红警")
        plugin.config["require_creation_approval"] = False
        result = await plugin._join(FakeEvent("1"), "group", "1", "红警")
        self.assertIn("创建并加入", result[1])
        state = await plugin._load_state("group")
        self.assertEqual(state["games"]["红警"]["members"], ["1"])
        self.assertNotIn("红警", state["pending_creations"])


if __name__ == "__main__":
    unittest.main()
