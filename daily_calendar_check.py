import os
import json
import requests
from datetime import datetime, timedelta, timezone
from google.oauth2 import service_account
from googleapiclient.discovery import build

# ── 環境變數 ──
# GOOGLE_SERVICE_ACCOUNT_JSON：服務帳號金鑰檔的「完整 JSON 內容」（貼成一整行字串存到 GitHub Secrets）
# CALENDAR_ID：要讀取的 Google 日曆 ID（在日曆設定 →「整合日曆」裡可以找到）
# LINE_TOKEN、LINE_USER_ID、LINE_USER_ID_2：跟 daily_bill_check.py 共用同一組 GitHub Secrets
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]
CALENDAR_ID = os.environ["CALENDAR_ID"]
LINE_TOKEN     = os.environ["LINE_TOKEN"]
LINE_USER_ID   = os.environ["LINE_USER_ID"]
LINE_USER_ID_2 = os.environ["LINE_USER_ID_2"]

TW = timezone(timedelta(hours=8))
SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]


def get_calendar_service():
    """用服務帳號金鑰建立 Google Calendar API 的連線"""
    info = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
    credentials = service_account.Credentials.from_service_account_info(
        info, scopes=SCOPES
    )
    return build("calendar", "v3", credentials=credentials)


def get_today_events():
    """回傳今天（台灣時區）的行程清單"""
    service = get_calendar_service()
    today = datetime.now(TW).date()

    start_of_day = datetime(today.year, today.month, today.day, 0, 0, 0, tzinfo=TW)
    end_of_day = start_of_day + timedelta(days=1)

    events_result = service.events().list(
        calendarId=CALENDAR_ID,
        timeMin=start_of_day.isoformat(),
        timeMax=end_of_day.isoformat(),
        singleEvents=True,
        orderBy="startTime",
    ).execute()

    events = events_result.get("items", [])
    schedule = []

    for e in events:
        title = e.get("summary", "（無標題）")
        start = e.get("start", {})

        if "dateTime" in start:
            # 有明確時間的行程
            start_dt = datetime.fromisoformat(start["dateTime"])
            time_str = start_dt.astimezone(TW).strftime("%H:%M")
            schedule.append(f"🗓️ {time_str} {title}")
        else:
            # 整天的行程（例如生日、假期）
            schedule.append(f"🗓️ 整天　{title}")

    return schedule


def build_message():
    schedule = get_today_events()

    if not schedule:
        return None  # 今天沒有行程，不推播

    today_str = datetime.now(TW).strftime("%Y/%m/%d")
    msg = f"📢 嘟嘟一家 今日行程（{today_str}）\n\n"
    msg += "\n".join(schedule)
    return msg.strip()


def send_line(msg):
    user_ids = [LINE_USER_ID, LINE_USER_ID_2]
    for uid in user_ids:
        res = requests.post(
            "https://api.line.me/v2/bot/message/push",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {LINE_TOKEN}",
            },
            json={
                "to": uid,
                "messages": [{"type": "text", "text": msg}],
            },
        )
        print(f"推播給 {uid[:10]}... 回應：{res.status_code}")


if __name__ == "__main__":
    msg = build_message()
    if msg is None:
        print("今天沒有行程，不推播。")
    else:
        print("========== 預覽訊息 ==========")
        print(msg)
        print("==============================")
        send_line(msg)
        print("✅ 推播完成！")
