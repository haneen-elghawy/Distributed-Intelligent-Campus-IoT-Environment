"""Create a lightweight Phase-2 NOC dashboard to avoid UI rendering stalls."""

from __future__ import annotations

import json
import os
from typing import Any

import requests

TB_URL = os.getenv("TB_URL", "http://127.0.0.1:9090").rstrip("/")
TB_USERNAME = os.getenv("TB_USERNAME", "tenant@campus.io")
TB_PASSWORD = os.getenv("TB_PASSWORD", "Tenant123!")


def _headers(token: str) -> dict[str, str]:
    return {
        "X-Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _login(s: requests.Session) -> str:
    r = s.post(f"{TB_URL}/api/auth/login", json={"username": TB_USERNAME, "password": TB_PASSWORD}, timeout=30)
    r.raise_for_status()
    return r.json()["token"]


def _list_dashboards(s: requests.Session, h: dict[str, str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    page = 0
    while True:
        r = s.get(
            f"{TB_URL}/api/tenant/dashboards",
            params={"pageSize": 100, "page": page, "sortProperty": "title", "sortOrder": "ASC"},
            headers=h,
            timeout=30,
        )
        r.raise_for_status()
        j = r.json()
        out.extend(j.get("data", []))
        if not j.get("hasNext", False):
            break
        page += 1
    return out


def _delete_dashboard(s: requests.Session, h: dict[str, str], did: str) -> None:
    r = s.delete(f"{TB_URL}/api/dashboard/{did}", headers=h, timeout=30)
    if r.status_code not in (200, 204):
        r.raise_for_status()


def _key(name: str, label: str, t: str, color: str, units: str | None = None, decimals: int | None = None) -> dict[str, Any]:
    k: dict[str, Any] = {
        "name": name,
        "type": t,
        "label": label,
        "color": color,
        "settings": {
            "columnWidth": "0px",
            "useCellStyleFunction": False,
            "useCellContentFunction": False,
            "defaultColumnVisibility": "visible",
            "columnSelectionToDisplay": "enabled",
        },
    }
    if units is not None:
        k["units"] = units
    if decimals is not None:
        k["decimals"] = decimals
    return k


def _table(widget_id: str, title: str, alias_id: str) -> dict[str, Any]:
    return {
        "id": widget_id,
        "type": "latest",
        "sizeX": 12,
        "sizeY": 10,
        "typeFullFqn": "system.cards.entities_table",
        "config": {
            "timewindow": {
                "displayValue": "",
                "selectedTab": 0,
                "realtime": {"realtimeType": 1, "interval": 1000, "timewindowMs": 120000, "quickInterval": "CURRENT_DAY"},
                "history": {"historyType": 0, "interval": 1000, "timewindowMs": 120000},
                "aggregation": {"type": "NONE", "limit": 200},
            },
            "showTitle": True,
            "backgroundColor": "rgb(255, 255, 255)",
            "color": "rgba(0, 0, 0, 0.87)",
            "padding": "4px",
            "settings": {
                "enableSearch": False,
                "displayPagination": False,
                "defaultPageSize": 1,
                "defaultSortOrder": "entityName",
                "displayEntityName": True,
                "displayEntityType": False,
                "enableSelectColumnDisplay": False,
                "enableStickyHeader": True,
                "enableStickyAction": False,
                "entitiesTitle": "Live Data",
                "entityNameColumnTitle": "Room",
            },
            "title": title,
            "dropShadow": True,
            "enableFullscreen": True,
            "titleStyle": {"fontSize": "16px", "fontWeight": 400, "padding": "5px 10px 5px 10px"},
            "useDashboardTimewindow": False,
            "showLegend": False,
            "datasources": [
                {
                    "type": "entity",
                    "name": None,
                    "entityAliasId": alias_id,
                    "filterId": None,
                    "dataKeys": [
                        _key("temperature", "Temperature", "timeseries", "#4caf50", "C", 1),
                        _key("humidity", "Humidity", "timeseries", "#2196f3", "%", 1),
                        _key("occupancy", "Occupancy", "timeseries", "#ff9800"),
                        _key("hvac_mode", "HVAC", "timeseries", "#9c27b0"),
                        _key("active", "Online/Offline", "entityField", "#f44336"),
                    ],
                }
            ],
            "showTitleIcon": False,
            "actions": {"headerButton": [], "actionCellButton": [], "rowClick": []},
        },
    }


def _payload() -> dict[str, Any]:
    w_mqtt = "91f50000-0000-4000-8000-000000000001"
    w_coap = "91f50000-0000-4000-8000-000000000002"
    a_mqtt = "91f50000-0000-4000-8000-000000000011"
    a_coap = "91f50000-0000-4000-8000-000000000012"
    return {
        "title": "Phase 2 NOC Dashboard",
        "name": "Phase 2 NOC Dashboard",
        "image": None,
        "mobileHide": False,
        "mobileOrder": None,
        "resources": [],
        "configuration": {
            "description": "Stable Phase-2 dashboard: MQTT + CoAP real-time telemetry and online/offline.",
            "widgets": {
                w_mqtt: _table(w_mqtt, "MQTT Room (b01-f01-r101)", a_mqtt),
                w_coap: _table(w_coap, "CoAP Room (b01-f01-r111)", a_coap),
            },
            "states": {
                "default": {
                    "name": "Phase 2 NOC",
                    "root": True,
                    "layouts": {
                        "main": {
                            "widgets": {
                                w_mqtt: {"sizeX": 12, "sizeY": 10, "row": 0, "col": 0},
                                w_coap: {"sizeX": 12, "sizeY": 10, "row": 0, "col": 12},
                            },
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
            "entityAliases": {
                a_mqtt: {
                    "id": a_mqtt,
                    "alias": "MQTT Room",
                    "filter": {"type": "entityName", "resolveMultiple": True, "entityType": "DEVICE", "entityNameFilter": "b01-f01-r101"},
                },
                a_coap: {
                    "id": a_coap,
                    "alias": "CoAP Room",
                    "filter": {"type": "entityName", "resolveMultiple": True, "entityType": "DEVICE", "entityNameFilter": "b01-f01-r111"},
                },
            },
            "timewindow": {
                "displayValue": "",
                "selectedTab": 0,
                "realtime": {"interval": 1000, "timewindowMs": 120000},
                "history": {"historyType": 0, "interval": 1000, "timewindowMs": 120000},
                "aggregation": {"type": "AVG", "limit": 25000},
            },
            "settings": {"stateControllerId": "default", "showTitle": True, "showEntitiesSelect": False, "showDashboardTimewindow": True},
        },
    }


def main() -> int:
    s = requests.Session()
    token = _login(s)
    h = _headers(token)
    dashboards = _list_dashboards(s, h)
    for d in dashboards:
        did = d.get("id", {}).get("id")
        if did:
            _delete_dashboard(s, h, did)
    print(f"Deleted dashboards: {len(dashboards)}")
    r = s.post(f"{TB_URL}/api/dashboard", headers=h, data=json.dumps(_payload()), timeout=30)
    r.raise_for_status()
    j = r.json()
    print("Created dashboard:", j.get("title"), j.get("id", {}).get("id"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
