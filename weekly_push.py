import os
import calendar
import requests
from datetime import datetime, timedelta, timezone

# ── 環境變數 ──────────────────────────────
NOTION_TOKEN = os.environ["NOTION_TOKEN"]
LINE_TOKEN   = os.environ["LINE_TOKEN"]
LINE_USER_ID   = os.environ["LINE_USER_ID"]
LINE_USER_ID_2 = os.environ["LINE_USER_ID_2"]

BILL_DB_ID = os.environ["BILL_DB_ID"]
TODO_DB_ID = os.environ["TODO_DB_ID"]
EXPIRY_DB_ID = os.environ.get("EXPIRY_DB_ID") or "f40a3915e858492daa9a941ddccea34d"
BILL_HISTORY_DB_ID = os.environ.get("BILL_HISTORY_DB_ID") or "c3b447cd772183c4a3e101bfc6880814"

TW = timezone(timedelta(hours=8))

notion_headers = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

def query_db(db_id, body):
    res = requests.post(
        f"https://api.notion.com/v1/databases/{db_id}/query",
        headers=notion_headers,
        json=body
    )
    return res.json().get("results", [])

def get_title(page):
    for val in page["properties"].values():
        if val["type"] == "title":
            texts = val["title"]
            return texts[0]["plain_text"] if texts else "（無標題）"
    return "（無標題）"

def previous_billing_date(due_date, billing_cycle="月"):
    months = {"月": 1, "季": 3, "年": 12}.get(billing_cycle, 1)
    month_index = due_date.year * 12 + due_date.month - 1 - months
    year, zero_based_month = divmod(month_index, 12)
    month = zero_based_month + 1
    day = min(due_date.day, calendar.monthrange(year, month)[1])
    return due_date.replace(year=year, month=month, day=day)

def has_payment_in_current_cycle(page_id, due_date, billing_cycle, today):
    if not page_id:
        return False
    cycle_start = previous_billing_date(due_date, billing_cycle) + timedelta(days=1)
    records = query_db(BILL_HISTORY_DB_ID, {
        "filter": {"and": [
            {"property": "產品", "relation": {"contains": page_id}},
            {"property": "繳費日期", "date": {"on_or_after": str(cycle_start)}},
            {"property": "繳費日期", "date": {"on_or_before": str(today)}}
        ]},
        "page_size": 1
    })
    return bool(records)

def get_bills(today=None):
    today    = today or datetime.now(TW).date()
    week_end = today + timedelta(days=6)

    results = query_db(BILL_DB_ID, {
        "sorts": [{"property": "下次繳費", "direction": "ascending"}]
    })

    lines = []
    for p in results:
        if p["properties"].get("暫停訂閱", {}).get("checkbox", False):
            continue

        name = get_title(p)

        formula_prop = p["properties"].get("下次繳費", {})
        formula_val  = formula_prop.get("formula", {})

        date_str = ""
        if formula_val.get("type") == "string":
            date_str = formula_val.get("string", "")
        elif formula_val.get("type") == "date":
            date_obj = formula_val.get("date", {})
            date_str = date_obj.get("start", "") if date_obj else ""

        if not date_str:
            continue

        try:
            bill_date = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
        except:
            continue

        if not (today <= bill_date <= week_end):
            continue

        cycle_select = p["properties"].get("繳費週期", {}).get("select") or {}
        billing_cycle = cycle_select.get("name", "月")
        if has_payment_in_current_cycle(p.get("id"), bill_date, billing_cycle, today):
            continue

        price_prop = p["properties"].get("價格", {})
        price      = price_prop.get("number")
        price_str  = f"${price:,}" if price else ""

        date_display = bill_date.strftime("%m/%d")
        lines.append(f"▪️ {name}｜{date_display} {price_str}".strip())

    return lines

def get_expiries(today=None):
    today = today or datetime.now(TW).date()
    week_end = today + timedelta(days=6)
    results = query_db(EXPIRY_DB_ID, {
        "filter": {"property": "已處理", "checkbox": {"equals": False}},
        "sorts": [{"property": "日期", "direction": "ascending"}]
    })

    lines = []
    for page in results:
        properties = page.get("properties", {})
        if properties.get("提醒", {}).get("checkbox") is False:
            continue
        date_property = properties.get("日期") or properties.get("到期更換日", {})
        if date_property.get("type") == "formula":
            formula = date_property.get("formula", {})
            if formula.get("type") == "date":
                date_str = (formula.get("date") or {}).get("start", "")
            else:
                date_str = formula.get("string", "")
        else:
            date_str = (date_property.get("date") or {}).get("start", "")
        try:
            due_date = datetime.strptime(str(date_str)[:10], "%Y-%m-%d").date()
        except (TypeError, ValueError):
            continue
        if due_date > week_end:
            continue
        days = (due_date - today).days
        if days < 0:
            label = f"已過期 {abs(days)} 天"
        elif days == 0:
            label = "今天到期"
        else:
            label = f"剩 {days} 天"
        lines.append(f"▪️ {get_title(page)}｜{label}")
    return lines

def format_urgent_todo(name, properties, today=None):
    today = today or datetime.now(TW).date()
    date_prop = properties.get("預定作業日期", {})
    date_obj = date_prop.get("date") or {}
    date_str = date_obj.get("start", "")
    if not date_str:
        return f"▪️ {name}"

    try:
        due_date = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return f"▪️ {name}"

    days = (due_date - today).days
    if days < 0:
        date_text = f"逾期 {abs(days)} 天"
    elif days == 0:
        date_text = "今天"
    else:
        date_text = f"{due_date.month}/{due_date.day}"
    return f"▪️ {name}｜{date_text}"

def get_todos_by_type(attr_name):
    results = query_db(TODO_DB_ID, {
        "filter": {
            "and": [
                {"property": "完成", "checkbox": {"equals": False}},
                {"property": "屬性", "select": {"equals": attr_name}}
            ]
        },
        "sorts": [{"property": "優先級", "direction": "ascending"}]
    })

    urgent = []
    others = 0
    for p in results:
        name_prop = p["properties"].get("項目名稱", {})
        texts     = name_prop.get("title", [])
        name      = texts[0]["plain_text"] if texts else "（無標題）"

        pri_prop = p["properties"].get("優先級", {})
        pri_sel  = pri_prop.get("select", {})
        pri_name = pri_sel.get("name", "") if pri_sel else ""
        if pri_name == "急":
            urgent.append(format_urgent_todo(name, p["properties"]))
        else:
            others += 1

    return urgent, others

def build_message():
    bills              = get_bills()
    expiries           = get_expiries()
    buy_urgent, buy_others   = get_todos_by_type("🛒 待買清單")
    todo_urgent, todo_others = get_todos_by_type("✅ 待辦事項")

    today = datetime.now(TW).date()
    week_end = today + timedelta(days=6)
    msg = f"📢 本週整理 {today.month}/{today.day}-{week_end.month}/{week_end.day}\n"

    if bills:
        msg += f"\n【本週待繳｜{len(bills)} 項】\n"
        msg += "\n".join(bills) + "\n"
    else:
        msg += "\n【本週待繳｜0 項】\n本週沒有待繳項目\n"

    msg += f"\n【急需購買｜{len(buy_urgent)} 項】\n"
    if buy_urgent:
        msg += "\n".join(buy_urgent)
        if buy_others > 0:
            msg += f"\n另有 {buy_others} 項一般待買"
    else:
        msg += "目前沒有急需購買的項目"
        if buy_others > 0:
            msg += f"\n另有 {buy_others} 項一般待買"

    msg += f"\n\n【急需處理｜{len(todo_urgent)} 項】\n"
    if todo_urgent:
        msg += "\n".join(todo_urgent)
        if todo_others > 0:
            msg += f"\n另有 {todo_others} 項一般待辦"
    else:
        msg += "目前沒有急需處理的事項"
        if todo_others > 0:
            msg += f"\n另有 {todo_others} 項一般待辦"

    msg += f"\n\n【效期提醒｜{len(expiries)} 項】\n"
    if expiries:
        msg += "\n".join(expiries)
    else:
        msg += "✨ 本週沒有即將到期或需要更換的品項，安心使用就好～"

    return msg

def send_line(msg):
    user_ids = [LINE_USER_ID, LINE_USER_ID_2]
    for uid in user_ids:
        res = requests.post(
            "https://api.line.me/v2/bot/message/push",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {LINE_TOKEN}"
            },
            json={
                "to": uid,
                "messages": [{
                    "type": "text",
                    "text": msg,
                    "quickReply": {"items": [
                        {"type": "action", "action": {"type": "postback", "label": "查看全部待買", "data": "action=list&type=buy", "displayText": "查看全部待買"}},
                        {"type": "action", "action": {"type": "postback", "label": "查看全部待辦", "data": "action=list&type=todo", "displayText": "查看全部待辦"}},
                        {"type": "action", "action": {"type": "postback", "label": "查看繳費", "data": "action=bills", "displayText": "查看繳費狀態"}},
                        {"type": "action", "action": {"type": "postback", "label": "查看效期提醒", "data": "action=expiry", "displayText": "查看效期提醒"}}
                    ]}
                }]
            }
        )
        print(f"推播給 {uid[:10]}... 回應：{res.status_code}")

if __name__ == "__main__":
    msg = build_message()
    print("========== 預覽訊息 ==========")
    print(msg)
    print("==============================")
    send_line(msg)
    print("✅ 推播完成！")
