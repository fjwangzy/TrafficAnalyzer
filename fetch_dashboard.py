import urllib.request
import json
import base64

url = "http://localhost:3111/api/dashboards/uid/edycr94pt2mm8b"
req = urllib.request.Request(url)
auth_str = "admin:admin"
auth_bytes = auth_str.encode("ascii")
base64_bytes = base64.b64encode(auth_bytes)
base64_str = base64_bytes.decode("ascii")
req.add_header("Authorization", "Basic " + base64_str)

try:
    with urllib.request.urlopen(req) as response:
        data = json.loads(response.read().decode())
        with open("dashboard_backup.json", "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print("Dashboard downloaded successfully.")
except Exception as e:
    print("Error:", e)
