import os
import requests
from datetime import datetime, timedelta, timezone

# ── 環境變數 ──────────────────────────────
NOTION_TOKEN = os.environ["NOTION_TOKEN"]
LINE_TOKEN   = os.environ["LINE_TOKEN"]
LINE_USER_ID   = os.environ["LINE_USER_ID"]
LINE_USER_ID_2 = os.environ["LINE_USER_ID_2"]

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

        date_display = bill_date.strftime("%m/%d")
        lines.append(f"▪️ {name} {date_display} {price_str}".strip())

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

    return [f"▪️ {get_title(p)}" for p in results]

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

    priority_tag = {"急": "[急]", "中": "[中]", "緩": "[緩]"}

    urgent = []
    others = 0
    for p in results:
        name_prop = p["properties"].get("項目名稱", {})
        texts     = name_prop.get("title", [])
        name      = texts[0]["plain_text"] if texts else "（無標題）"

        pri_prop = p["properties"].get("優先級", {})
        pri_sel  = pri_prop.get("select", {})
        pri_name = pri_sel.get("name", "") if pri_sel else ""
        tag      = priority_tag.get(pri_name, "")

        if pri_name == "急":
            urgent.append(f"▪️ {tag} {name}".strip())
        else:
            others += 1

    return urgent, others

def build_message():
    bills              = get_bills()
    wiki               = get_wiki()
    buy_urgent, buy_others   = get_todos_by_type("🛒 待買清單")
    todo_urgent, todo_others = get_todos_by_type("✅ 待辦事項")

    msg = f"✨叮咚～又到了嘟嘟一家的週報時間 📢\n\n"

    msg += "📊 繳費提醒\n"
    msg += ("\n".join(bills) if bills else "▪️ 本週沒有到期帳單") + "\n\n"

    msg += "🛒 待買清單\n"
    if buy_urgent:
        msg += "\n".join(buy_urgent)
        if buy_others > 0:
            msg += f"\n（另有 {buy_others} 項待購）"
    else:
        msg += "▪️ 沒有急需購買的項目"
        if buy_others > 0:
            msg += f"\n（另有 {buy_others} 項待購）"
    msg += "\n\n"

    msg += "✅ 待辦事項\n"
    if todo_urgent:
        msg += "\n".join(todo_urgent)
        if todo_others > 0:
            msg += f"\n（另有 {todo_others} 項待辦）"
    else:
        msg += "▪️ 沒有急需處理的事項"
        if todo_others > 0:
            msg += f"\n（另有 {todo_others} 項待辦）"
    msg += "\n\n"

    msg += "📚 小百科新文章\n"
    if wiki:
        msg += "\n".join(wiki[:5])
        if len(wiki) > 5:
            msg += f"\n（本週共 {len(wiki)} 篇，其餘請至小百科查閱）"
    else:
        msg += "▪️ 本週尚無新文章"

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
                "messages": [{"type": "text", "text": msg}]
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
