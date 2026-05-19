import urllib.request
import json
import base64

auth_str = "admin:admin"
auth_bytes = auth_str.encode("ascii")
base64_bytes = base64.b64encode(auth_bytes)
base64_str = base64_bytes.decode("ascii")
headers = {
    "Authorization": "Basic " + base64_str,
    "Content-Type": "application/json",
    "Accept": "application/json"
}

def get_dashboard(uid):
    url = f"http://localhost:3111/api/dashboards/uid/{uid}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode())
    except Exception as e:
        print(f"Error fetching {uid}:", e)
        return None

def update_dashboard(dashboard_data):
    url = "http://localhost:3111/api/dashboards/db"
    # To update, we wrap the dashboard object in a json containing "dashboard", "message" and "overwrite":true
    payload = {
        "dashboard": dashboard_data["dashboard"],
        "message": "Translated to Chinese",
        "overwrite": True
    }
    
    req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req) as response:
            res = json.loads(response.read().decode())
            print("Successfully updated dashboard:", res)
    except urllib.error.HTTPError as e:
        print("HTTP Error:", e.code, e.read().decode())
    except Exception as e:
        print("Error updating dashboard:", e)

# Replacements mapping
replacements = {
    "Число машин на участке кругового движения": "环岛区域车辆数",
    "Загруженность дорог (машин в минуту)": "道路拥堵情况 (辆/分钟)",
    "число машин в минуту": "每分钟车辆数",
    "График изменения загруженности дорог": "道路拥堵情况变化趋势",
    'Перейти на дашборд "Камера 2"': '切换至仪表盘 "摄像头 2"',
    'Перейти на дашборд "Камера 1"': '切换至仪表盘 "摄像头 1"',
    "окно усреднения": "平均窗口",
    "Road 1": "道路 1",
    "Road 2": "道路 2",
    "Road 3": "道路 3",
    "Road 4": "道路 4",
    "Road 5": "道路 5",
    "Road 6": "道路 6"
}

def translate_json(data):
    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(v, str):
                for old_text, new_text in replacements.items():
                    if old_text in v:
                        v = v.replace(old_text, new_text)
                data[k] = v
            else:
                translate_json(v)
    elif isinstance(data, list):
        for item in data:
            translate_json(item)

# Process Dashboard 1
uid1 = "edycr94pt2mm8b"
db1 = get_dashboard(uid1)
if db1:
    translate_json(db1)
    db1["dashboard"]["id"] = None # set id to None when importing/updating
    update_dashboard(db1)

# Process Dashboard 2
uid2 = "adycu34xs035sb"
db2 = get_dashboard(uid2)
if db2:
    translate_json(db2)
    db2["dashboard"]["id"] = None
    update_dashboard(db2)

