"""Replace tenant dashboards with a new advanced Phase-2 NOC dashboard.

The new dashboard shows real-time telemetry from:
- one MQTT room (b01-f01-r101)
- one CoAP room (b01-f01-r111)
and includes online/offline state via the ThingsBoard DEVICE active entity field.

It also adds:
- live fleet table
- floor summary table
- active alarms table
- faster dashboard refresh (500ms) for visibly quicker updates
"""

from __future__ import annotations

import json
import os
from typing import Any

import requests

TB_URL = os.getenv("TB_URL", "http://127.0.0.1:9090").rstrip("/")
TB_USERNAME = os.getenv("TB_USERNAME", "tenant@campus.io")
TB_PASSWORD = os.getenv("TB_PASSWORD", "Tenant123!")


def _auth_headers(token: str) -> dict[str, str]:
    return {
        "X-Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _login(session: requests.Session) -> str:
    resp = session.post(
        f"{TB_URL}/api/auth/login",
        json={"username": TB_USERNAME, "password": TB_PASSWORD},
        timeout=30,
    )
    resp.raise_for_status()
    token = resp.json().get("token")
    if not token:
        raise RuntimeError("ThingsBoard login succeeded but token is missing.")
    return token


def _list_all_dashboards(session: requests.Session, headers: dict[str, str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    page = 0
    while True:
        resp = session.get(
            f"{TB_URL}/api/tenant/dashboards",
            params={"pageSize": 100, "page": page, "sortProperty": "title", "sortOrder": "ASC"},
            headers=headers,
            timeout=30,
        )
        resp.raise_for_status()
        payload = resp.json()
        rows = payload.get("data", [])
        out.extend(rows)
        if not payload.get("hasNext", False):
            break
        page += 1
    return out


def _delete_dashboard(session: requests.Session, headers: dict[str, str], dashboard_id: str) -> None:
    resp = session.delete(f"{TB_URL}/api/dashboard/{dashboard_id}", headers=headers, timeout=30)
    if resp.status_code not in (200, 204):
        resp.raise_for_status()


def _make_data_key(
    name: str,
    label: str,
    key_type: str,
    color: str,
    units: str | None = None,
    decimals: int | None = None,
) -> dict[str, Any]:
    key: dict[str, Any] = {
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
        key["units"] = units
    if decimals is not None:
        key["decimals"] = decimals
    return key


def _entities_table_widget(
    widget_id: str,
    title: str,
    alias_id: str,
    page_size: int = 1,
    enable_search: bool = False,
    display_pagination: bool = False,
    keys: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if keys is None:
        keys = [
            _make_data_key("temperature", "Temperature", "timeseries", "#4caf50", "C", 1),
            _make_data_key("humidity", "Humidity", "timeseries", "#2196f3", "%", 1),
            _make_data_key("occupancy", "Occupancy", "timeseries", "#ff9800"),
            _make_data_key("hvac_mode", "HVAC", "timeseries", "#9c27b0"),
            _make_data_key("active", "Online/Offline", "entityField", "#f44336"),
        ]
    return {
        "id": widget_id,
        "type": "latest",
        "sizeX": 12,
        "sizeY": 9,
        "typeFullFqn": "system.cards.entities_table",
        "config": {
            "timewindow": {
                "displayValue": "",
                "selectedTab": 0,
                "realtime": {
                    "realtimeType": 1,
                    "interval": 500,
                    "timewindowMs": 120000,
                    "quickInterval": "CURRENT_DAY",
                },
                "history": {
                    "historyType": 0,
                    "interval": 500,
                    "timewindowMs": 120000,
                },
                "aggregation": {"type": "NONE", "limit": 200},
            },
            "showTitle": True,
            "backgroundColor": "rgb(255, 255, 255)",
            "color": "rgba(0, 0, 0, 0.87)",
            "padding": "4px",
            "settings": {
                "enableSearch": enable_search,
                "displayPagination": display_pagination,
                "defaultPageSize": page_size,
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
            "titleStyle": {
                "fontSize": "16px",
                "fontWeight": 400,
                "padding": "5px 10px 5px 10px",
            },
            "useDashboardTimewindow": False,
            "showLegend": False,
            "datasources": [
                {
                    "type": "entity",
                    "name": None,
                    "entityAliasId": alias_id,
                    "filterId": None,
                    "dataKeys": keys,
                }
            ],
            "showTitleIcon": False,
            "actions": {"headerButton": [], "actionCellButton": [], "rowClick": []},
        },
    }


def _alarms_widget(widget_id: str, alias_id: str) -> dict[str, Any]:
    return {
        "id": widget_id,
        "type": "alarm",
        "sizeX": 24,
        "sizeY": 7,
        "typeFullFqn": "system.alarm_widgets.alarms_table",
        "config": {
            "timewindow": {
                "realtime": {"interval": 500, "timewindowMs": 120000},
                "aggregation": {"type": "NONE", "limit": 200},
            },
            "showTitle": True,
            "backgroundColor": "rgb(255, 255, 255)",
            "color": "rgba(0, 0, 0, 0.87)",
            "padding": "4px",
            "settings": {
                "enableSelection": True,
                "enableSearch": True,
                "displayDetails": True,
                "allowAcknowledgment": True,
                "allowClear": True,
                "allowAssign": True,
                "displayComments": True,
                "displayPagination": True,
                "defaultPageSize": 10,
                "defaultSortOrder": "-createdTime",
                "alarmsTitle": "NOC Alarms",
            },
            "title": "Active alarms",
            "dropShadow": True,
            "useDashboardTimewindow": False,
            "alarmSource": {
                "type": "entity",
                "name": "alarms",
                "entityAliasId": alias_id,
                "filterId": None,
                "dataKeys": [
                    {"name": "createdTime", "type": "alarm", "label": "Created", "color": "#2196f3", "settings": {}},
                    {"name": "type", "type": "alarm", "label": "Type", "color": "#f44336", "settings": {}},
                    {"name": "severity", "type": "alarm", "label": "Severity", "color": "#ffc107", "settings": {}},
                    {"name": "status", "type": "alarm", "label": "Status", "color": "#607d8b", "settings": {}},
                ],
            },
            "alarmsPollingInterval": 3,
            "alarmFilterConfig": {
                "statusList": [],
                "severityList": [],
                "typeList": [],
                "searchPropagatedAlarms": True,
            },
            "alarmsMaxCountLoad": 0,
            "alarmsFetchSize": 100,
        },
    }


def _build_dashboard_payload() -> dict[str, Any]:
    w_mqtt = "11111111-1111-4111-8111-111111111111"
    w_coap = "22222222-2222-4222-8222-222222222222"
    w_fleet = "33333333-3333-4333-8333-333333333333"
    w_floor = "44444444-4444-4444-8444-444444444444"
    w_alarm = "55555555-5555-4555-8555-555555555555"
    a_mqtt = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    a_coap = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    a_fleet = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
    a_floor = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"

    return {
        "title": "Phase 2 NOC Dashboard",
        "name": "Phase 2 NOC Dashboard",
        "image": None,
        "mobileHide": False,
        "mobileOrder": None,
        "resources": [],
        "configuration": {
            "description": (
                "Phase-2 requirement dashboard: real-time telemetry from MQTT and CoAP rooms "
                "with online/offline indicator."
            ),
            "widgets": {
                w_mqtt: _entities_table_widget(w_mqtt, "MQTT Room (b01-f01-r101)", a_mqtt),
                w_coap: _entities_table_widget(w_coap, "CoAP Room (b01-f01-r111)", a_coap),
                w_fleet: _entities_table_widget(
                    w_fleet,
                    "Fleet Live View (MQTT + CoAP)",
                    a_fleet,
                    page_size=20,
                    enable_search=True,
                    display_pagination=True,
                ),
                w_floor: _entities_table_widget(
                    w_floor,
                    "Floor Summary Live View",
                    a_floor,
                    page_size=10,
                    enable_search=True,
                    display_pagination=True,
                    keys=[
                        _make_data_key("avg_temperature", "Avg Temp", "timeseries", "#4caf50", "C", 1),
                        _make_data_key("avg_humidity", "Avg Humidity", "timeseries", "#2196f3", "%", 1),
                        _make_data_key("occupied_rooms", "Occupied", "timeseries", "#607d8b"),
                        _make_data_key("total_rooms", "Total Rooms", "timeseries", "#9e9e9e"),
                        _make_data_key("occupancy_rate", "Occupancy Rate", "timeseries", "#ff9800", "", 4),
                        _make_data_key("active", "Online/Offline", "entityField", "#f44336"),
                    ],
                ),
                w_alarm: _alarms_widget(w_alarm, a_fleet),
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
                                w_fleet: {"sizeX": 12, "sizeY": 10, "row": 8, "col": 0},
                                w_floor: {"sizeX": 12, "sizeY": 10, "row": 8, "col": 12},
                                w_alarm: {"sizeX": 24, "sizeY": 7, "row": 18, "col": 0},
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
                    "filter": {
                        "type": "entityName",
                        "resolveMultiple": True,
                        "entityType": "DEVICE",
                        "entityNameFilter": "b01-f01-r101",
                    },
                },
                a_coap: {
                    "id": a_coap,
                    "alias": "CoAP Room",
                    "filter": {
                        "type": "entityName",
                        "resolveMultiple": True,
                        "entityType": "DEVICE",
                        "entityNameFilter": "b01-f01-r111",
                    },
                },
                a_fleet: {
                    "id": a_fleet,
                    "alias": "All Rooms",
                    "filter": {
                        "type": "entityType",
                        "resolveMultiple": True,
                        "entityType": "DEVICE",
                    },
                },
                a_floor: {
                    "id": a_floor,
                    "alias": "All Floor Summaries",
                    "filter": {
                        "type": "entityName",
                        "resolveMultiple": True,
                        "entityType": "DEVICE",
                        "entityNameFilter": "floor-summary",
                    },
                },
            },
            "timewindow": {
                "displayValue": "",
                "selectedTab": 0,
                "realtime": {"interval": 500, "timewindowMs": 120000},
                "history": {"historyType": 0, "interval": 500, "timewindowMs": 120000},
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


def main() -> int:
    session = requests.Session()
    token = _login(session)
    headers = _auth_headers(token)

    dashboards = _list_all_dashboards(session, headers)
    for d in dashboards:
        did = d.get("id", {}).get("id")
        if did:
            _delete_dashboard(session, headers, did)
    print(f"Deleted dashboards: {len(dashboards)}")

    payload = _build_dashboard_payload()
    resp = session.post(f"{TB_URL}/api/dashboard", headers=headers, data=json.dumps(payload), timeout=30)
    resp.raise_for_status()
    created = resp.json()
    print("Created dashboard:", created.get("title"), created.get("id", {}).get("id"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
