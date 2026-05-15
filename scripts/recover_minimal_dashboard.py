from __future__ import annotations

import json
import requests

TB_URL = "http://127.0.0.1:9090"
TB_USERNAME = "tenant@campus.io"
TB_PASSWORD = "Tenant123!"


def main() -> int:
    s = requests.Session()
    login = s.post(
        f"{TB_URL}/api/auth/login",
        json={"username": TB_USERNAME, "password": TB_PASSWORD},
        timeout=20,
    )
    login.raise_for_status()
    token = login.json()["token"]
    h = {
        "X-Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    dashboards = s.get(
        f"{TB_URL}/api/tenant/dashboards",
        params={"pageSize": 100, "page": 0, "sortProperty": "title", "sortOrder": "ASC"},
        headers=h,
        timeout=20,
    ).json().get("data", [])

    for d in dashboards:
        did = d.get("id", {}).get("id")
        if did:
            s.delete(f"{TB_URL}/api/dashboard/{did}", headers=h, timeout=20)

    payload = {
        "title": "Phase 2 NOC Dashboard",
        "name": "Phase 2 NOC Dashboard",
        "image": None,
        "mobileHide": False,
        "mobileOrder": None,
        "resources": [],
        "configuration": {
            "description": "Recovery minimal dashboard",
            "widgets": {},
            "states": {
                "default": {
                    "name": "Default",
                    "root": True,
                    "layouts": {
                        "main": {
                            "widgets": {},
                            "gridSettings": {
                                "backgroundColor": "#f5f7fb",
                                "color": "rgba(0,0,0,0.87)",
                                "columns": 24,
                                "margin": 10,
                                "outerMargin": True,
                            },
                        }
                    },
                }
            },
            "entityAliases": {},
            "timewindow": {
                "displayValue": "",
                "selectedTab": 0,
                "realtime": {"interval": 1000, "timewindowMs": 60000},
                "history": {"historyType": 0, "interval": 1000, "timewindowMs": 60000},
                "aggregation": {"type": "AVG", "limit": 25000},
            },
            "settings": {
                "stateControllerId": "default",
                "showTitle": True,
                "showEntitiesSelect": False,
                "showDashboardTimewindow": True,
            },
        },
    }

    resp = s.post(f"{TB_URL}/api/dashboard", headers=h, data=json.dumps(payload), timeout=30)
    resp.raise_for_status()
    did = resp.json().get("id", {}).get("id")
    print(f"Created minimal dashboard: {did}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
