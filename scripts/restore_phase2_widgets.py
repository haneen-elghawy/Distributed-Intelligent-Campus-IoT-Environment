from __future__ import annotations

import json
import requests

TB_URL = "http://127.0.0.1:9090"
TB_USERNAME = "tenant@campus.io"
TB_PASSWORD = "Tenant123!"


def _auth_headers(token: str) -> dict[str, str]:
    return {
        "X-Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _data_key(name: str, label: str, key_type: str, color: str, units: str | None = None, decimals: int | None = None):
    out = {
        "name": name,
        "type": key_type,
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
        out["units"] = units
    if decimals is not None:
        out["decimals"] = decimals
    return out


def _latest_table_widget(widget_id: str, title: str, alias_id: str) -> dict:
    return {
        "id": widget_id,
        "type": "latest",
        "sizeX": 12,
        "sizeY": 8,
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
                        _data_key("temperature", "Temperature", "timeseries", "#4caf50", "C", 1),
                        _data_key("humidity", "Humidity", "timeseries", "#2196f3", "%", 1),
                        _data_key("occupancy", "Occupancy", "timeseries", "#ff9800"),
                        _data_key("hvac_mode", "HVAC", "timeseries", "#9c27b0"),
                        _data_key("active", "Online/Offline", "entityField", "#f44336"),
                    ],
                }
            ],
            "showTitleIcon": False,
            "actions": {"headerButton": [], "actionCellButton": [], "rowClick": []},
        },
    }


def _timeseries_widget(widget_id: str, title: str, alias_id: str) -> dict:
    return {
        "id": widget_id,
        "type": "timeseries",
        "sizeX": 24,
        "sizeY": 8,
        "typeFullFqn": "system.charts.timeseries_line_chart",
        "config": {
            "title": title,
            "showTitle": True,
            "useDashboardTimewindow": True,
            "timewindow": {
                "displayValue": "",
                "selectedTab": 0,
                "realtime": {"realtimeType": 1, "interval": 1000, "timewindowMs": 120000, "quickInterval": "CURRENT_DAY"},
                "history": {"historyType": 0, "interval": 1000, "timewindowMs": 120000},
                "aggregation": {"type": "NONE", "limit": 500},
            },
            "datasources": [
                {
                    "type": "entity",
                    "name": None,
                    "entityAliasId": alias_id,
                    "filterId": None,
                    "dataKeys": [
                        _data_key("temperature", "Temperature", "timeseries", "#4caf50", "C", 1),
                        _data_key("humidity", "Humidity", "timeseries", "#2196f3", "%", 1),
                    ],
                }
            ],
            "settings": {
                "showLegend": True,
                "showTooltip": True,
                "stack": False,
                "thresholds": [],
            },
            "backgroundColor": "rgb(255, 255, 255)",
            "dropShadow": True,
            "padding": "4px",
        },
    }


def main() -> int:
    s = requests.Session()
    login = s.post(
        f"{TB_URL}/api/auth/login",
        json={"username": TB_USERNAME, "password": TB_PASSWORD},
        timeout=20,
    )
    login.raise_for_status()
    token = login.json()["token"]
    headers = _auth_headers(token)

    dashboards = s.get(
        f"{TB_URL}/api/tenant/dashboards",
        params={"pageSize": 100, "page": 0, "sortProperty": "title", "sortOrder": "ASC"},
        headers=headers,
        timeout=20,
    ).json()["data"]

    dashboard = next((d for d in dashboards if d.get("title") == "Phase 2 NOC Dashboard"), None)
    if not dashboard:
        raise RuntimeError("Phase 2 NOC Dashboard not found.")

    did = dashboard["id"]["id"]
    full = s.get(f"{TB_URL}/api/dashboard/{did}", headers=headers, timeout=20)
    full.raise_for_status()
    payload = full.json()

    w_mqtt = "70111111-1111-4111-8111-111111111111"
    w_coap = "70222222-2222-4222-8222-222222222222"
    w_chart = "70333333-3333-4333-8333-333333333333"
    a_mqtt = "70aaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    a_coap = "70bbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"

    payload["configuration"] = {
        "description": "Restored Phase-2 widgets: MQTT + CoAP + trend chart.",
        "widgets": {
            w_mqtt: _latest_table_widget(w_mqtt, "MQTT Room (b01-f01-r101)", a_mqtt),
            w_coap: _latest_table_widget(w_coap, "CoAP Room (b01-f01-r111)", a_coap),
            w_chart: _timeseries_widget(w_chart, "MQTT Trend (2 min)", a_mqtt),
        },
        "states": {
            "default": {
                "name": "Phase 2 NOC",
                "root": True,
                "layouts": {
                    "main": {
                        "widgets": {
                            w_mqtt: {"sizeX": 12, "sizeY": 8, "row": 0, "col": 0},
                            w_coap: {"sizeX": 12, "sizeY": 8, "row": 0, "col": 12},
                            w_chart: {"sizeX": 24, "sizeY": 8, "row": 8, "col": 0},
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
    }

    save = s.post(f"{TB_URL}/api/dashboard", headers=headers, data=json.dumps(payload), timeout=30)
    save.raise_for_status()
    print("Widgets restored on dashboard:", did)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
