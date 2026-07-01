import os
import requests
from datetime import datetime, timedelta, timezone

# ── 環境變數（跟 weekly_push.py 共用同一組 GitHub Secrets） ──
NOTION_TOKEN = os.environ["NOTION_TOKEN"]
LINE_TOKEN   = os.environ["LINE_TOKEN"]
LINE_USER_ID   = os.environ["LINE_USER_ID"]
LINE_USER_ID_2 = os.environ["LINE_USER_ID_2"]
BILL_DB_ID = os.environ["BILL_DB_ID"]

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

def get_due_today_and_overdue():
    """回傳今天到期、以及已逾期未繳的帳單清單"""
    today = datetime.now(TW).date()
    results = query_db(BILL_DB_ID, {
        "sorts": [{"property": "下次繳費", "direction": "ascending"}]
    })

    due_today = []
    overdue = []

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

        price_prop = p["properties"].get("價格", {})
        price      = price_prop.get("number")
        price_str  = f"${price:,}" if price else ""

        if bill_date == today:
            due_today.append(f"🔔 {name} {price_str}".strip())
        elif bill_date < today:
            days_late = (today - bill_date).days
            overdue.append(f"🔴 {name} {price_str}（已逾期{days_late}天）".strip())

    return due_today, overdue

def build_message():
    due_today, overdue = get_due_today_and_overdue()

    if not due_today and not overdue:
        return None  # 沒有任何需要提醒的帳單，當天不推播

    msg = "📢 嘟嘟一家 帳單提醒\n\n"
    if due_today:
        msg += "【今天到期】\n" + "\n".join(due_today) + "\n\n"
    if overdue:
        msg += "【已逾期，記得補繳】\n" + "\n".join(overdue) + "\n\n"
    return msg.strip()

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
    if msg is None:
        print("今天沒有到期或逾期的帳單，不推播。")
    else:
        print("========== 預覽訊息 ==========")
        print(msg)
        print("==============================")
        send_line(msg)
        print("✅ 推播完成！")
