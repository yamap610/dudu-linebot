import os
import sys
from datetime import date
from types import SimpleNamespace
import unittest
from unittest.mock import patch

for name in ('NOTION_TOKEN', 'LINE_TOKEN', 'LINE_USER_ID', 'LINE_USER_ID_2', 'BILL_DB_ID', 'TODO_DB_ID'):
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
    @patch.object(weekly_push, 'get_expiries', return_value=[])
    @patch.object(weekly_push, 'get_bills', return_value=[])
    def test_compact_weekly_message(self, _bills, _expiries, todos):
        todos.side_effect = [(['▪️ 濕紙巾', '▪️ 普拿疼'], 6), (['▪️ 冷氣'], 1)]
        message = weekly_push.build_message()
        self.assertIn('📢 本週整理 ', message)
        self.assertNotIn('嘟嘟一家', message)
        self.assertIn('【本週待繳｜0 項】', message)
        self.assertIn('本週沒有待繳項目', message)
        self.assertIn('【急需購買｜2 項】', message)
        self.assertIn('另有 6 項一般待買', message)
        self.assertIn('【急需處理｜1 項】', message)
        self.assertIn('【效期提醒｜0 項】', message)
        self.assertIn('✨ 本週沒有即將到期或需要更換的品項，安心使用就好～', message)
        self.assertNotIn('小百科', message)

    @patch.object(weekly_push, 'query_db')
    def test_expiry_reminders_include_overdue_and_this_week(self, query_db):
        def expiry(name, due_date, reminder=True, handled=False):
            return {'properties': {
                '品項': {'type': 'title', 'title': [{'plain_text': name}]},
                '日期': {'type': 'date', 'date': {'start': due_date}},
                '提醒': {'checkbox': reminder},
                '已處理': {'checkbox': handled},
            }}
        query_db.return_value = [
            expiry('牛奶', '2026-07-20'),
            expiry('濾芯', '2026-07-25'),
            expiry('下週品項', '2026-07-28'),
            expiry('關閉提醒', '2026-07-22', reminder=False),
        ]
        self.assertEqual(weekly_push.get_expiries(date(2026, 7, 21)), [
            '▪️ 牛奶｜已過期 1 天',
            '▪️ 濾芯｜剩 4 天',
        ])

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
            'action=expiry',
        ])


if __name__ == '__main__':
    unittest.main()
