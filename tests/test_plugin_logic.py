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
        joined = await plugin._join(FakeEvent("1"), "group", "1", "原神")
        self.assertIn("加入成功", joined[1])

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
        plugin = FakePlugin({"summon_cooldown_seconds": 0})
        await plugin._join(FakeEvent("1"), "group", "1", "农")
        result = await plugin._summon(FakeEvent("2"), "group", "2", "农")
        self.assertIn("只有农伙伴", result[1])

    async def test_old_nong_members_are_migrated(self):
        plugin = FakePlugin()
        plugin.storage["nong_partners:group"] = ["7", "8"]
        state = await plugin._load_state("group")
        self.assertEqual(state["games"]["农"]["members"], ["7", "8"])


if __name__ == "__main__":
    unittest.main()
