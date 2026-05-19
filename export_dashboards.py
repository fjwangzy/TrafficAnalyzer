import urllib.request
import json
import base64
import os

auth_str = "admin:admin"
auth_bytes = auth_str.encode("ascii")
base64_bytes = base64.b64encode(auth_bytes)
base64_str = base64_bytes.decode("ascii")
headers = {
    "Authorization": "Basic " + base64_str,
    "Accept": "application/json"
}

def get_dashboard(uid):
    url = f"http://localhost:3111/api/dashboards/uid/{uid}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode())["dashboard"]
    except Exception as e:
        print(f"Error fetching {uid}:", e)
        return None

out_dir = r"d:\ai\TrafficAnalyzer\services\grafana\provisioning\dashboards"

for uid, filename in [("edycr94pt2mm8b", "camera-1.json"), ("adycu34xs035sb", "camera-2.json")]:
    db = get_dashboard(uid)
    if db:
        # Remove id for provisioning
        db["id"] = None
        out_path = os.path.join(out_dir, filename)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(db, f, indent=2, ensure_ascii=False)
        print(f"Saved {filename}")
