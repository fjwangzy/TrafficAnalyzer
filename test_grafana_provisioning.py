import json
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parent
COMPOSE = ROOT / "docker-compose.yaml"
DATASOURCE = ROOT / "services/grafana/provisioning/datasources/datasource.yaml"
DASHBOARDS = [
    ROOT / "services/grafana/provisioning/dashboards/camera-1.json",
    ROOT / "services/grafana/provisioning/dashboards/camera-2.json",
]


def _dashboard_datasource_refs(path):
    refs = set()
    data = json.loads(path.read_text())

    def walk(value):
        if isinstance(value, dict):
            datasource = value.get("datasource")
            if (
                isinstance(datasource, dict)
                and datasource.get("uid")
                and datasource.get("uid") != "-- Grafana --"
            ):
                refs.add((datasource.get("uid"), datasource.get("type")))
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(data)
    return refs


class GrafanaProvisioningTest(unittest.TestCase):
    def test_compose_grafana_defaults_work_without_env_file(self):
        compose = yaml.safe_load(COMPOSE.read_text())

        self.assertNotIn("version", compose)
        grafana = compose["services"]["grafana"]
        env = grafana["environment"]

        self.assertEqual(env["GF_SECURITY_ADMIN_USER"], "${GRAFANA_ADMIN_USER:-admin}")
        self.assertEqual(env["GF_SECURITY_ADMIN_PASSWORD"], "${GRAFANA_ADMIN_PASSWORD:-admin123}")
        self.assertEqual(env["INFLUXDB_ADMIN_USER"], "${INFLUXDB_ADMIN_USER:-}")
        self.assertEqual(env["INFLUXDB_ADMIN_PASSWORD"], "${INFLUXDB_ADMIN_PASSWORD:-}")
        self.assertIn("influxdb", grafana["depends_on"])
        self.assertIn("postgres", grafana["depends_on"])

        volumes = grafana["volumes"]
        self.assertIn(
            "./services/grafana/provisioning:/etc/grafana/provisioning",
            volumes,
        )

    def test_datasource_uids_match_dashboard_references(self):
        datasource = yaml.safe_load(DATASOURCE.read_text())
        provisioned = {
            (item["uid"], item["type"])
            for item in datasource["datasources"]
        }
        dashboard_refs = set()
        for dashboard in DASHBOARDS:
            dashboard_refs.update(_dashboard_datasource_refs(dashboard))

        self.assertIn(("cdycrblq6bf9ce", "influxdb"), provisioned)
        self.assertIn(
            ("f848db3d-2635-4913-be1c-ae2d0db7c90a", "grafana-postgresql-datasource"),
            provisioned,
        )
        self.assertFalse(dashboard_refs - provisioned)

    def test_influxdb_datasource_uses_container_network_and_local_defaults(self):
        datasource = yaml.safe_load(DATASOURCE.read_text())
        by_uid = {item["uid"]: item for item in datasource["datasources"]}

        influx = by_uid["cdycrblq6bf9ce"]
        self.assertEqual(influx["url"], "http://influxdb:8086")
        self.assertEqual(influx["database"], "influx")
        self.assertEqual(influx["user"], "${INFLUXDB_ADMIN_USER}")
        self.assertEqual(influx["secureJsonData"]["password"], "${INFLUXDB_ADMIN_PASSWORD}")
        self.assertEqual(influx["jsonData"]["httpMode"], "GET")

        postgres = by_uid["f848db3d-2635-4913-be1c-ae2d0db7c90a"]
        self.assertEqual(postgres["url"], "postgres:5432")
        self.assertEqual(postgres["database"], "traffic_platform")
        self.assertEqual(postgres["user"], "traffic")
        self.assertEqual(postgres["jsonData"]["sslmode"], "disable")


if __name__ == "__main__":
    unittest.main()
