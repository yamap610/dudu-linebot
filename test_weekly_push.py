import os
import sys
from datetime import date
from types import SimpleNamespace
import unittest
from unittest.mock import patch

for name in ('NOTION_TOKEN', 'LINE_TOKEN', 'LINE_USER_ID', 'LINE_USER_ID_2', 'BILL_DB_ID', 'WIKI_DB_ID', 'TODO_DB_ID'):
    os.environ.setdefault(name, 'test')

sys.modules.setdefault('requests', SimpleNamespace(post=None))
import weekly_push


class WeeklyPushTest(unittest.TestCase):
    def test_urgent_todo_displays_scheduled_or_overdue_date(self):
        today = date(2026, 7, 21)
        self.assertEqual(
            weekly_push.format_urgent_todo('回桃園待辦', {
                '預定作業日期': {'date': {'start': '2026-07-25'}},
            }, today),
            '▪️ 回桃園待辦｜7/25',
        )
        self.assertEqual(
            weekly_push.format_urgent_todo('領處方箋', {
                '預定作業日期': {'date': {'start': '2026-07-21'}},
            }, today),
            '▪️ 領處方箋｜今天',
        )
        self.assertEqual(
            weekly_push.format_urgent_todo('整理行李', {
                '預定作業日期': {'date': {'start': '2026-07-19'}},
            }, today),
            '▪️ 整理行李｜逾期 2 天',
        )
        self.assertEqual(
            weekly_push.format_urgent_todo('買尿布', {}, today),
            '▪️ 買尿布',
        )

    @patch.object(weekly_push, 'get_todos_by_type')
    @patch.object(weekly_push, 'get_wiki', return_value=['文章一', '文章二'])
    @patch.object(weekly_push, 'get_bills', return_value=[])
    def test_compact_weekly_message(self, _bills, _wiki, todos):
        todos.side_effect = [(['▪️ 濕紙巾', '▪️ 普拿疼'], 6), (['▪️ 冷氣'], 1)]
        message = weekly_push.build_message()
        self.assertIn('📢 本週整理 ', message)
        self.assertNotIn('嘟嘟一家', message)
        self.assertIn('【本週待繳｜0 項】', message)
        self.assertIn('本週沒有待繳項目', message)
        self.assertIn('【急需購買｜2 項】', message)
        self.assertIn('另有 6 項一般待買', message)
        self.assertIn('【急需處理｜1 項】', message)
        self.assertIn('本週新增 2 篇文章', message)
        self.assertNotIn('文章一', message)

    @patch.object(weekly_push.requests, 'post')
    def test_weekly_message_has_view_all_buttons(self, post):
        post.return_value.status_code = 200
        weekly_push.send_line('週報')
        message = post.call_args.kwargs['json']['messages'][0]
        actions = [item['action']['data'] for item in message['quickReply']['items']]
        self.assertEqual(actions, [
            'action=list&type=buy',
            'action=list&type=todo',
            'action=bills',
            'action=wiki_menu',
        ])


if __name__ == '__main__':
    unittest.main()
