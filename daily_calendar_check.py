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

# Google Calendar 自訂標籤的顯示順序與圖示。
# 日後新增標籤時，就算沒有列在這裡，仍會自動顯示。
LABEL_ORDER = [
    "Yui活動",
    "Martin活動",
    "家人行程/活動",
    "嘟嘟家親子活動",
    "就醫/看診",
    "費用繳納",
    "桃園",
    "其他行程",
]

LABEL_ICONS = {
    "Yui活動": "🌸",
    "Martin活動": "🔵",
    "家人行程/活動": "👨‍👩‍👧‍👦",
    "嘟嘟家親子活動": "🐰",
    "就醫/看診": "🏥",
    "費用繳納": "💳",
    "桃園": "📍",
    "其他行程": "🗓️",
}


def get_calendar_service():
    """用服務帳號金鑰建立 Google Calendar API 的連線"""
    info = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
    credentials = service_account.Credentials.from_service_account_info(
        info, scopes=SCOPES
    )
    return build("calendar", "v3", credentials=credentials)


def get_label_map(service):
    """回傳 {標籤 ID: 標籤名稱}；讀不到標籤時回傳空字典。"""
    calendar = service.calendars().get(calendarId=CALENDAR_ID).execute()
    labels = calendar.get("labelProperties", {}).get("eventLabels", [])

    if not labels:
        print(
            "⚠️ 未讀取到 Google 日曆標籤。"
            "請確認服務帳號已被授予「變更活動」權限。"
        )

    return {
        label["id"]: label.get("name", "其他行程")
        for label in labels
        if label.get("id")
    }


def get_today_events():
    """回傳今天（台灣時區）的行程，並依 Google 日曆標籤分組。"""
    service = get_calendar_service()
    label_map = get_label_map(service)
    today = datetime.now(TW).date()

    start_of_day = datetime(today.year, today.month, today.day, 0, 0, 0, tzinfo=TW)
    end_of_day = start_of_day + timedelta(days=1)

    request = service.events().list(
        calendarId=CALENDAR_ID,
        timeMin=start_of_day.isoformat(),
        timeMax=end_of_day.isoformat(),
        singleEvents=True,
        orderBy="startTime",
    )

    # Google Calendar 新版標籤需要在請求附上 eventLabelVersion=1。
    # Python client 尚未把這個讀取參數公開，因此加到請求網址。
    separator = "&" if "?" in request.uri else "?"
    request.uri += f"{separator}eventLabelVersion=1"
    events_result = request.execute()

    events = events_result.get("items", [])
    schedule_by_label = {}

    for e in events:
        title = e.get("summary", "（無標題）")
        start = e.get("start", {})
        # Google 尚未向服務帳號提供標籤時，保留舊版的平面清單格式；
        # 一旦能讀到標籤，沒有標籤的活動才歸入「其他行程」。
        label_name = (
            label_map.get(e.get("eventLabelId"), "其他行程")
            if label_map else None
        )

        if "dateTime" in start:
            # 有明確時間的行程
            start_dt = datetime.fromisoformat(start["dateTime"])
            time_str = start_dt.astimezone(TW).strftime("%H:%M")
            line = f"{time_str} {title}"
        else:
            # 整天的行程（例如生日、假期）
            line = f"整天　{title}"

        schedule_by_label.setdefault(label_name, []).append(line)

    return schedule_by_label


def build_message():
    schedule_by_label = get_today_events()

    if not schedule_by_label:
        return None  # 今天沒有行程，不推播

    today_str = datetime.now(TW).strftime("%Y/%m/%d")
    msg = f"📢 嘟嘟一家 今日行程（{today_str}）\n\n"

    # 標籤 API 暫時不可用時維持原本格式，避免影響既有推播。
    if set(schedule_by_label) == {None}:
        msg += "\n".join(
            f"🗓️ {line}" for line in schedule_by_label[None]
        )
        return msg.strip()

    known_labels = [
        label for label in LABEL_ORDER
        if label in schedule_by_label
    ]
    new_labels = sorted(
        label for label in schedule_by_label
        if label not in LABEL_ORDER
    )

    sections = []
    for label in known_labels + new_labels:
        icon = LABEL_ICONS.get(label, "🏷️")
        lines = "\n".join(schedule_by_label[label])
        sections.append(f"{icon}【{label}】\n{lines}")

    msg += "\n\n".join(sections)
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
