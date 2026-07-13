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

# Google Calendar 標籤在 LINE 裡使用的簡短名稱。
# 保留舊名稱相容性，已排定的舊行程不會突然無法辨識。
LABEL_DISPLAY = {
    "🌸 Yui活動": ("🌸", "Yui"),
    "Yui活動": ("🌸", "Yui"),
    "🔵 Martin活動": ("🔵", "Martin"),
    "Martin活動": ("🔵", "Martin"),
    "🐰 嘟嘟家親子活動": ("🐰", "親子"),
    "嘟嘟家親子活動": ("🐰", "親子"),
    "👣 家人行程/活動": ("👣", "家庭"),
    "家人行程/活動": ("👣", "家庭"),
    "🏥 就醫/看診": ("🏥", "看診"),
    "就醫/看診": ("🏥", "看診"),
    "💳 費用繳納": ("💳", "繳費"),
    "費用繳納": ("💳", "繳費"),
}

# 「回桃園／回宜蘭」是所在地背景，不當成一般行程分類。
LOCATION_LABELS = {
    "📍 回桃園": "回桃園",
    "回桃園": "回桃園",
    "📍 回宜蘭": "回宜蘭",
    "回宜蘭": "回宜蘭",
}

# Google 新標籤 API 尚未對所有帳號回傳資料時，使用活動顏色備援。
# 這些代碼來自「M.Y 嘟嘟一家」目前的實際行程資料。
COLOR_DISPLAY = {
    "2": ("🌸", "Yui"),
    "4": ("🐰", "親子"),
    "5": ("👣", "家庭"),
    "11": ("🏥", "看診"),
}

LOCATION_COLORS = {
    "6": "回桃園",
    "1": "回宜蘭",
}

WEATHER_LOCATIONS = {
    "台北": (25.0330, 121.5654),
    "桃園": (24.9937, 121.3010),
    "宜蘭": (24.7021, 121.7378),
}

WEEKDAYS = "一二三四五六日"


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
            "⚠️ Google 尚未回傳日曆標籤，改用活動顏色辨識。"
        )

    return {
        label["id"]: label.get("name", "").strip()
        for label in labels
        if label.get("id")
    }


def get_events(day_offset=0):
    """回傳指定日期（0=今天、1=明天）的行程與標籤。"""
    service = get_calendar_service()
    label_map = get_label_map(service)
    target_date = datetime.now(TW).date() + timedelta(days=day_offset)

    start_of_day = datetime(
        target_date.year, target_date.month, target_date.day,
        0, 0, 0, tzinfo=TW,
    )
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
    schedule = []

    for e in events:
        title = e.get("summary", "（無標題）")
        start = e.get("start", {})
        # Google 尚未向服務帳號提供標籤時，保留舊版的平面清單格式；
        # 一旦能讀到標籤，沒有標籤的活動才歸入「其他行程」。
        label_name = label_map.get(e.get("eventLabelId"), "") if label_map else ""

        if "dateTime" in start:
            # 有明確時間的行程
            start_dt = datetime.fromisoformat(start["dateTime"])
            time_str = start_dt.astimezone(TW).strftime("%H:%M")
            time_text = time_str
        else:
            # 整天的行程（例如生日、假期）
            time_text = "整天"

        schedule.append({
            "title": title.strip(),
            "time": time_text,
            "label": label_name,
            "color_id": e.get("colorId", ""),
        })

    return schedule


def get_weather_line(location_name, day_offset=0):
    """取得台北、桃園或宜蘭的單行天氣摘要；失敗時不影響行程推播。"""
    latitude, longitude = WEATHER_LOCATIONS[location_name]

    try:
        response = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": latitude,
                "longitude": longitude,
                "daily": (
                    "weather_code,temperature_2m_max,temperature_2m_min,"
                    "precipitation_probability_max"
                ),
                "timezone": "Asia/Taipei",
                "forecast_days": max(2, day_offset + 1),
            },
            timeout=10,
        )
        response.raise_for_status()
        daily = response.json()["daily"]

        low = round(daily["temperature_2m_min"][day_offset])
        high = round(daily["temperature_2m_max"][day_offset])
        rain = round(daily["precipitation_probability_max"][day_offset])
        weather_code = daily["weather_code"][day_offset]

        if rain >= 60:
            icon, summary = "🌧️", f"降雨 {rain}%"
        elif rain >= 30:
            icon, summary = "🌦️", f"降雨 {rain}%"
        elif weather_code == 0:
            icon, summary = "☀️", "晴朗"
        elif weather_code in (1, 2, 3):
            icon, summary = "🌤️", "多雲"
        elif weather_code in (45, 48):
            icon, summary = "🌫️", "有霧"
        elif weather_code in (95, 96, 99):
            icon, summary = "⛈️", "雷雨"
        else:
            icon, summary = "🌦️", "偶有陣雨"

        return f"{icon} {location_name}｜{low}–{high}°C・{summary}"
    except (requests.RequestException, KeyError, IndexError, TypeError, ValueError) as exc:
        print(f"⚠️ 天氣資料讀取失敗：{exc}")
        return None


def build_message(events=None, now=None, day_offset=0):
    events = get_events(day_offset) if events is None else events

    if not events:
        return None  # 今天沒有行程，不推播

    target_time = (now or datetime.now(TW)) + timedelta(days=day_offset)
    date_text = (
        f"{target_time.month}/{target_time.day}"
        f"（{WEEKDAYS[target_time.weekday()]}）"
    )
    heading = "☀️ 今日行程" if day_offset == 0 else "🌙 明日預告"
    locations = []
    activity_lines = []

    for event in events:
        title = event["title"]
        label = event.get("label", "").strip()
        color_id = str(event.get("color_id", ""))
        location = LOCATION_LABELS.get(label) or LOCATION_COLORS.get(color_id)

        # 地點標籤且標題也是「回桃園／回宜蘭」時，視為跨日背景。
        # 標籤 API 尚未開放時，也可以靠標題辨識地點背景。
        title_location = next(
            (place for place in ("回桃園", "回宜蘭") if title.startswith(place)),
            None,
        )
        if location and title.startswith(location):
            if location not in locations:
                locations.append(location)
            continue
        if not label and title_location:
            if title_location not in locations:
                locations.append(title_location)
            continue

        if label in LABEL_DISPLAY:
            icon, short_name = LABEL_DISPLAY[label]
        elif color_id in COLOR_DISPLAY:
            icon, short_name = COLOR_DISPLAY[color_id]
        elif location:
            icon, short_name = "📍", location.replace("回", "")
        else:
            icon, short_name = "🗓️", "其他"

        activity_lines.append(
            f"{icon} {short_name}｜{event['time']} {title}"
        )

    weather_location = locations[0].replace("回", "") if locations else "台北"
    weather_line = get_weather_line(weather_location, day_offset)

    lines = [f"{heading}｜{date_text}"]
    if weather_line:
        lines.append(weather_line)

    if locations:
        lines.append("")
        for location in locations:
            lines.append(f"📍 {location}")

    lines.append("")
    if activity_lines:
        lines.extend(activity_lines)
    elif locations:
        lines.append("☁️ 今天沒有其他安排")
    else:
        return None

    return "\n".join(lines).strip()


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
    day_offset = int(os.getenv("DAY_OFFSET", "0"))
    msg = build_message(day_offset=day_offset)
    if msg is None:
        print("今天沒有行程，不推播。")
    else:
        print("========== 預覽訊息 ==========")
        print(msg)
        print("==============================")
        send_line(msg)
        print("✅ 推播完成！")
