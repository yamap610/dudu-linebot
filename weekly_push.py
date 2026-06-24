import os
import requests
from datetime import datetime, timedelta, timezone

# ── 環境變數 ──────────────────────────────
NOTION_TOKEN = os.environ["NOTION_TOKEN"]
LINE_TOKEN   = os.environ["LINE_TOKEN"]
LINE_USER_ID = os.environ["LINE_USER_ID"]

BILL_DB_ID = os.environ["BILL_DB_ID"]   # 支出管理
WIKI_DB_ID = os.environ["WIKI_DB_ID"]   # M.Y 小百科
TODO_DB_ID = os.environ["TODO_DB_ID"]   # To Do List

TW = timezone(timedelta(hours=8))

notion_headers = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

# ── 共用：查詢資料庫 ──────────────────────
def query_db(db_id, body):
    res = requests.post(
        f"https://api.notion.com/v1/databases/{db_id}/query",
        headers=notion_headers,
        json=body
    )
    return res.json().get("results", [])

# ── 共用：自動抓 title 欄位 ───────────────
def get_title(page):
    for val in page["properties"].values():
        if val["type"] == "title":
            texts = val["title"]
            return texts[0]["plain_text"] if texts else "（無標題）"
    return "（無標題）"

# ────────────────────────────────────────
# 📊 支出管理：7天內「下次繳費」到期
# ────────────────────────────────────────
def get_bills():
    today     = datetime.now(TW).date()
    one_week  = today + timedelta(days=7)

    # 抓全部資料（不用 filter）
    results = query_db(BILL_DB_ID, {
        "sorts": [{"property": "下次繳費", "direction": "ascending"}]
    })

    lines = []
    for p in results:
        name = get_title(p)

        # 「下次繳費」是公式欄位，type 是 formula
        formula_prop = p["properties"].get("下次繳費", {})
        formula_val  = formula_prop.get("formula", {})
        
        # 公式結果可能是 string 或 date
        date_str = ""
        if formula_val.get("type") == "string":
            date_str = formula_val.get("string", "")
        elif formula_val.get("type") == "date":
            date_obj = formula_val.get("date", {})
            date_str = date_obj.get("start", "") if date_obj else ""

        # 沒有日期就跳過
        if not date_str:
            continue

        # 轉成 date 物件比較
        try:
            bill_date = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
        except:
            continue

        # 只要 7 天內的
        if not (today <= bill_date <= one_week):
            continue

        price_prop = p["properties"].get("價格", {})
        price      = price_prop.get("number")
        price_str  = f"${price:,}" if price else "金額未填"

        lines.append(f"• {name}　{date_str[:10]}　{price_str}")

    return lines

# ────────────────────────────────────────
# 📚 M.Y 小百科：本週新增（建立時間）
# ────────────────────────────────────────
def get_wiki():
    last_week = datetime.now(TW).date() - timedelta(days=7)

    results = query_db(WIKI_DB_ID, {
        "filter": {
            "property": "建立時間",
            "date": {"on_or_after": str(last_week)}
        },
        "sorts": [{"property": "建立時間", "direction": "descending"}]
    })

    lines = []
    for p in results:
        name = get_title(p)

        cat_prop = p["properties"].get("分類", {})
        cats = cat_prop.get("multi_select", []) or []
        cat_str = "、".join([c["name"] for c in cats]) if cats else ""

        lines.append(f"• {name}" + (f"　[{cat_str}]" if cat_str else ""))

    return lines

# ────────────────────────────────────────
# ✅ To Do List：依「屬性」分開撈
# ────────────────────────────────────────
def get_todos_by_type(attr_name):
    """
    attr_name: "待買清單" 或 "待辦事項"
    """
    results = query_db(TODO_DB_ID, {
        "filter": {
            "and": [
                {"property": "完成", "checkbox": {"equals": False}},
                {"property": "屬性", "select": {"equals": attr_name}}
            ]
        },
        "sorts": [{"property": "優先級", "direction": "ascending"}]
    })

    priority_icon = {"高": "🔴", "中": "🟡", "低": "🟢"}

    lines = []
    for p in results:
        name_prop = p["properties"].get("項目名稱", {})
        texts     = name_prop.get("title", [])
        name      = texts[0]["plain_text"] if texts else "（無標題）"

        pri_prop = p["properties"].get("優先級", {})
        pri_sel  = pri_prop.get("select", {})
        pri_name = pri_sel.get("name", "") if pri_sel else ""
        icon     = priority_icon.get(pri_name, "•")

        # 備註（有的話顯示）
        note_prop = p["properties"].get("備註", {})
        notes     = note_prop.get("rich_text", [])
        note_str  = notes[0]["plain_text"] if notes else ""

        line = f"{icon} {name}"
        if note_str:
            line += f"\n　　↳ {note_str}"
        lines.append(line)

    return lines

# ────────────────────────────────────────
# 組合訊息
# ────────────────────────────────────────
def build_message():
    bills      = get_bills()
    wiki       = get_wiki()
    buy_list   = get_todos_by_type("🛒 待買清單")
    todo_list  = get_todos_by_type("✅ 待辦事項")

    today_str = datetime.now(TW).strftime("%Y/%m/%d")

    msg  = f"🐾 嘟嘟一家週報 {today_str}\n\n"

    msg += "📊 即將到期帳單（7天內）\n"
    msg += "━━━━━━━━━━━━━\n"
    msg += ("\n".join(bills) if bills else "✨ 本週沒有到期帳單") + "\n\n"

    msg += "📚 小百科本週新文章\n"
    msg += "━━━━━━━━━━━━━\n"
    msg += ("\n".join(wiki) if wiki else "📝 本週尚無新文章") + "\n\n"

    msg += "🛒 待買清單\n"
    msg += "━━━━━━━━━━━━━\n"
    msg += ("\n".join(buy_list[:10]) if buy_list else "✨ 待買清單是空的") + "\n\n"

    msg += "✅ 待辦事項\n"
    msg += "━━━━━━━━━━━━━\n"
    msg += ("\n".join(todo_list[:10]) if todo_list else "🎉 所有待辦已完成！")

    return msg

# ────────────────────────────────────────
# 發送 LINE 推播
# ────────────────────────────────────────
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

# ────────────────────────────────────────
# 執行
# ────────────────────────────────────────
if __name__ == "__main__":
    msg = build_message()
    print("========== 預覽訊息 ==========")
    print(msg)
    print("==============================")
    send_line(msg)
    print("✅ 推播完成！")
