import unittest

from partner_core import (
    PARTNER_FILTER_PATTERN,
    game_key,
    parse_partner_command,
    validate_game_name,
)


class PartnerCoreTests(unittest.TestCase):
    def test_dynamic_commands(self):
        command = parse_partner_command("/召集原神伙伴")
        self.assertEqual((command.action, command.game), ("召集", "原神"))

        command = parse_partner_command("邀请加入LOL伙伴 @123")
        self.assertEqual((command.action, command.game), ("邀请加入", "LOL"))

        command = parse_partner_command("/同意加入农伙伴")
        self.assertEqual((command.action, command.game), ("同意加入", "农"))

        command = parse_partner_command("/同意创建黑神话伙伴")
        self.assertEqual((command.action, command.game), ("同意创建", "黑神话"))

        command = parse_partner_command("/删除LOL伙伴")
        self.assertEqual((command.action, command.game), ("删除", "LOL"))

    def test_fixed_commands(self):
        self.assertEqual(parse_partner_command("/伙伴帮助").action, "help")
        self.assertEqual(parse_partner_command("伙伴列表").action, "list")
        self.assertEqual(parse_partner_command("/我的伙伴").action, "mine")
        self.assertEqual(parse_partner_command("/待审核伙伴").action, "pending")

    def test_unrelated_message_is_ignored(self):
        self.assertIsNone(parse_partner_command("今晚玩什么？"))
        self.assertIsNone(parse_partner_command("/召集伙伴"))
        self.assertIsNone(PARTNER_FILTER_PATTERN.search("今晚玩什么？"))
        self.assertIsNone(PARTNER_FILTER_PATTERN.search("伙伴帮助一下"))
        self.assertIsNotNone(PARTNER_FILTER_PATTERN.search("/召集原神伙伴"))
        self.assertIsNotNone(PARTNER_FILTER_PATTERN.search("/同意创建原神伙伴"))
        self.assertIsNotNone(PARTNER_FILTER_PATTERN.search("/删除原神伙伴"))

    def test_game_validation_and_key(self):
        self.assertEqual(validate_game_name("ＬＯＬ", 16), ("LOL", None))
        self.assertIsNotNone(validate_game_name("原 神", 16)[1])
        self.assertIsNotNone(validate_game_name("a" * 17, 16)[1])
        self.assertEqual(game_key("LOL"), game_key("ｌｏｌ"))


if __name__ == "__main__":
    unittest.main()
