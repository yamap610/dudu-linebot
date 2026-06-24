import os
import requests
from datetime import datetime, timedelta, timezone

# ── 環境變數 ──────────────────────────────
NOTION_TOKEN = os.environ["NOTION_TOKEN"]
LINE_TOKEN   = os.environ["LINE_TOKEN"]
LINE_USER_ID = os.environ["LINE_USER_ID"]

BILL_DB_ID = os.environ["BILL_DB_ID"]
WIKI_DB_ID = os.environ["WIKI_DB_ID"]
TODO_DB_ID = os.environ["TODO_DB_ID"]

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

def get_bills():
    today    = datetime.now(TW).date()
    one_week = today + timedelta(days=7)

    results = query_db(BILL_DB_ID, {
        "sorts": [{"property": "下次繳費", "direction": "ascending"}]
    })

    lines = []
    for p in results:
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

        if not (today <= bill_date <= one_week):
            continue

        price_prop = p["properties"].get("價格", {})
        price      = price_prop.get("number")
        price_str  = f"${price:,}" if price else ""

        # 日期只顯示 MM/DD
        date_display = bill_date.strftime("%m/%d")

        lines.append(f"• {name} {date_display} {price_str}".strip())

    return lines

def get_wiki():
    last_week = datetime.now(TW).date() - timedelta(days=7)

    results = query_db(WIKI_DB_ID, {
        "filter": {
            "property": "建立時間",
            "date": {"on_or_after": str(last_week)}
        },
        "sorts": [{"property": "建立時間", "direction": "descending"}]
    })

    return [f"• {get_title(p)}" for p in results]

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

    lines = []
    for p in results:
        name_prop = p["properties"].get("項目名稱", {})
        texts     = name_prop.get("title", [])
        name      = texts[0]["plain_text"] if texts else "（無標題）"
        lines.append(f"• {name}")

    return lines

def build_message():
    bills     = get_bills()
    wiki      = get_wiki()
    buy_list  = get_todos_by_type("🛒 待買清單")
    todo_list = get_todos_by_type("✅ 待辦事項")

    today_str = datetime.now(TW).strftime("%Y/%m/%d")

    msg  = f"✨嘟嘟一家🌙 週報 {today_str}\n\n"

    msg += "📊 繳費提醒\n"
    msg += ("\n".join(bills) if bills else "✨ 本週沒有到期帳單") + "\n\n"

    msg += "📚 小百科新文章\n"
    msg += ("\n".join(wiki) if wiki else "📝 本週尚無新文章") + "\n\n"

    msg += "🛒 待買清單\n"
    msg += ("\n".join(buy_list[:10]) if buy_list else "✨ 待買清單是空的") + "\n\n"

    msg += "✅ 待辦事項\n"
    msg += ("\n".join(todo_list[:10]) if todo_list else "🎉 所有待辦已完成！")

    return msg

def send_line(msg):
    res = requests.post(
        "https://api.line.me/v2/bot/message/push",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {LINE_TOKEN}"
        },
        json={
            "to": LINE_USER_ID,
            "messages": [{"type": "text", "text": msg}]
        }
    )
    print(f"LINE 回應：{res.status_code} {res.text}")

if __name__ == "__main__":
    msg = build_message()
    print("========== 預覽訊息 ==========")
    print(msg)
    print("==============================")
    send_line(msg)
    print("✅ 推播完成！")
