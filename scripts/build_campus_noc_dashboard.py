"""Emit ``thingsboard/dashboard_campus_noc.json`` (Campus NOC) for TB 4.x import.

Run from repo root:  python scripts/build_campus_noc_dashboard.py
"""
from __future__ import annotations

import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "thingsboard" / "dashboard_campus_noc.json"

# UUIDs used as stable ids in the export (re-imports rematch the same file)
W_FLEET = "a1b2c3d4-e5f6-4789-a01b-2c3d4e5f6a00"
W_FLOOR = "b2c3d4e5-f6a7-4890-b12c-3d4e5f6a7b00"
W_ALARM = "c3d4e5f6-a7b8-4901-c23d-4e5f6a7b8c00"
W_SYNC = "f6a7b8c9-d0e1-4234-f56a-7b8c9d0e1f00"
W_VERSION = "a7b8c9d0-e1f2-4345-a67b-8c9d0e1f2001"
A_FLEET = "d4e5f6a7-b8c9-4012-d34e-5f6a7b8c9d0a"
A_FLOOR = "e5f6a7b8-c9d0-4123-e45f-6a7b8c9d0e1a"


def _hash() -> float:
    return round(random.random(), 16)


def data_key(
    name: str,
    label: str,
    d_type: str,
    color: str,
    units: str | None = None,
    dec: int | None = None,
) -> dict:
    d: dict = {
        "name": name,
        "type": d_type,
        "label": label,
        "color": color,
        "settings": {
            "columnWidth": "0px",
            "useCellStyleFunction": False,
            "useCellContentFunction": False,
            "defaultColumnVisibility": "visible",
            "columnSelectionToDisplay": "enabled",
        },
        "_hash": _hash(),
    }
    if units is not None:
        d["units"] = units
    if dec is not None:
        d["decimals"] = dec
    return d


def widget_entities_table(
    w_id: str,
    title: str,
    alias_id: str,
    entities_title: str,
    data_keys: list[dict],
) -> dict:
    return {
        "id": w_id,
        "type": "latest",
        "sizeX": 12,
        "sizeY": 8,
        "typeFullFqn": "system.cards.entities_table",
        "config": {
            "timewindow": {
                "displayValue": "",
                "selectedTab": 0,
                "realtime": {
                    "realtimeType": 1,
                    "interval": 1000,
                    "timewindowMs": 86400000,
                    "quickInterval": "CURRENT_DAY",
                },
                "history": {
                    "historyType": 0,
                    "interval": 1000,
                    "timewindowMs": 60000,
                },
                "aggregation": {"type": "NONE", "limit": 200},
            },
            "showTitle": True,
            "backgroundColor": "rgb(255, 255, 255)",
            "color": "rgba(0, 0, 0, 0.87)",
            "padding": "4px",
            "settings": {
                "enableSearch": True,
                "displayPagination": True,
                "defaultPageSize": 20,
                "defaultSortOrder": "entityName",
                "displayEntityName": True,
                "displayEntityType": False,
                "enableSelectColumnDisplay": False,
                "enableStickyHeader": True,
                "enableStickyAction": False,
                "entitiesTitle": entities_title,
                "entityNameColumnTitle": "Device",
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
                    "dataKeys": data_keys,
                }
            ],
            "showTitleIcon": False,
            "actions": {"headerButton": [], "actionCellButton": [], "rowClick": []},
        },
    }


def widget_alarms(w_id: str, alias_id: str) -> dict:
    return {
        "id": w_id,
        "type": "alarm",
        "sizeX": 12,
        "sizeY": 8,
        "typeFullFqn": "system.alarm_widgets.alarms_table",
        "config": {
            "timewindow": {
                "realtime": {"interval": 1000, "timewindowMs": 86400000},
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
                "alarmsTitle": "Temperature alarms",
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
                    {
                        "name": "createdTime",
                        "type": "alarm",
                        "label": "Created",
                        "color": "#2196f3",
                        "settings": {},
                        "_hash": _hash(),
                    },
                    {
                        "name": "type",
                        "type": "alarm",
                        "label": "Type",
                        "color": "#f44336",
                        "settings": {},
                        "_hash": _hash(),
                    },
                    {
                        "name": "severity",
                        "type": "alarm",
                        "label": "Severity",
                        "color": "#ffc107",
                        "settings": {},
                        "_hash": _hash(),
                    },
                    {
                        "name": "status",
                        "type": "alarm",
                        "label": "Status",
                        "color": "#607d8b",
                        "settings": {},
                        "_hash": _hash(),
                    },
                ],
            },
            "alarmsPollingInterval": 5,
            "alarmFilterConfig": {
                "statusList": [],
                "severityList": [],
                "typeList": ["TEMPERATURE_THRESHOLD"],
                "searchPropagatedAlarms": True,
            },
            "alarmsMaxCountLoad": 0,
            "alarmsFetchSize": 100,
        },
    }


def main() -> None:
    random.seed(42)
    fleet_keys = [
        data_key("temperature", "Temperature", "timeseries", "#4caf50", "°C", 1),
        data_key("humidity", "Humidity", "timeseries", "#2196f3", "%", 0),
        data_key("hvac_mode", "HVAC mode", "timeseries", "#9c27b0"),
        data_key("occupancy", "Occupancy", "timeseries", "#ff9800"),
        data_key("device_status", "Status", "timeseries", "#f44336"),
    ]
    floor_keys = [
        data_key("avg_temperature", "Avg temp", "timeseries", "#4caf50", "°C", 1),
        data_key("avg_humidity", "Avg humidity", "timeseries", "#2196f3", "%", 0),
        data_key("occupied_rooms", "Occupied", "timeseries", "#607d8b"),
        data_key("occupancy_rate", "Occupancy rate", "timeseries", "#ff9800", "", 4),
    ]
    sync_keys = [
        data_key("last_seen", "Last Seen", "attribute", "#607d8b"),
        data_key("desired_hvac_mode", "Desired HVAC", "attribute", "#3f51b5"),
        data_key("reported_hvac_mode", "Reported HVAC", "attribute", "#4caf50"),
        data_key("desired_lighting_dimmer", "Desired Dimmer", "attribute", "#3f51b5"),
        data_key("reported_lighting_dimmer", "Reported Dimmer", "attribute", "#4caf50"),
        data_key("sync_status", "Sync Status", "attribute", "#f44336"),
        data_key("current_version", "Current Version", "attribute", "#ff9800"),
        data_key("config_version", "Target Version", "attribute", "#3f51b5"),
    ]
    version_keys = [
        data_key("current_version", "Current Version", "attribute", "#ff9800"),
        data_key("config_version", "Target Version", "attribute", "#3f51b5"),
        data_key("sync_status", "Sync Status", "attribute", "#f44336"),
        data_key("last_seen", "Last Seen", "attribute", "#607d8b"),
        data_key("ota_rejected", "Last OTA Rejected", "timeseries", "#e91e63"),
        data_key("ota_reason", "Last OTA Reason", "timeseries", "#795548"),
    ]

    dashboard = {
        "title": "Campus NOC",
        "image": None,
        "mobileHide": False,
        "mobileOrder": None,
        "configuration": {
            "description": "SWAPD453 — Fleet grid, floor summary, and threshold alarms. "
            "Spatial polygon config in thingsboard/floor_polygons.json. "
            "Re-export from UI after import if you adjust aliases. "
            "Source: repo scripts/build_campus_noc_dashboard.py",
            "widgets": {
                W_FLEET: widget_entities_table(
                    W_FLEET,
                    "Fleet — room devices",
                    A_FLEET,
                    "Rooms",
                    fleet_keys,
                ),
                W_FLOOR: widget_entities_table(
                    W_FLOOR,
                    "Floor summary",
                    A_FLOOR,
                    "Floor aggregates",
                    floor_keys,
                ),
                W_ALARM: widget_alarms(W_ALARM, A_FLEET),
                W_SYNC: widget_entities_table(
                    W_SYNC,
                    "Fleet synchronization status",
                    A_FLEET,
                    "Sync View",
                    sync_keys,
                ),
                W_VERSION: widget_entities_table(
                    W_VERSION,
                    "Fleet evolution status",
                    A_FLEET,
                    "Versioning",
                    version_keys,
                ),
            },
            "states": {
                "default": {
                    "name": "Campus NOC",
                    "root": True,
                    "layouts": {
                        "main": {
                            "widgets": {
                                W_FLEET: {
                                    "sizeX": 24,
                                    "sizeY": 8,
                                    "row": 0,
                                    "col": 0,
                                },
                                W_FLOOR: {
                                    "sizeX": 12,
                                    "sizeY": 7,
                                    "row": 8,
                                    "col": 0,
                                },
                                W_ALARM: {
                                    "sizeX": 12,
                                    "sizeY": 7,
                                    "row": 8,
                                    "col": 12,
                                },
                                W_SYNC: {
                                    "sizeX": 24,
                                    "sizeY": 7,
                                    "row": 15,
                                    "col": 0,
                                },
                                W_VERSION: {
                                    "sizeX": 24,
                                    "sizeY": 7,
                                    "row": 22,
                                    "col": 0,
                                },
                            },
                            "gridSettings": {
                                "backgroundColor": "#eeeeee",
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
                A_FLEET: {
                    "id": A_FLEET,
                    "alias": "All campus devices",
                    "filter": {
                        "type": "entityType",
                        "resolveMultiple": True,
                        "entityType": "DEVICE",
                    },
                },
                A_FLOOR: {
                    "id": A_FLOOR,
                    "alias": "Floor summary devices",
                    # Match names ending with floor-summary (TB treats pattern as name filter)
                    "filter": {
                        "type": "entityName",
                        "resolveMultiple": True,
                        "entityType": "DEVICE",
                        "entityNameFilter": "floor-summary",
                    },
                },
            },
            "filters": {
                "syncStatus": {
                    "key": {
                        "type": "ENTITY_FIELD",
                        "key": "name",
                    },
                    "valueType": "STRING",
                }
            },
            "timewindow": {
                "displayValue": "",
                "selectedTab": 0,
                "realtime": {"interval": 1000, "timewindowMs": 60000},
                "history": {
                    "historyType": 0,
                    "interval": 1000,
                    "timewindowMs": 60000,
                },
                "aggregation": {"type": "AVG", "limit": 25000},
            },
            "settings": {
                "stateControllerId": "default",
                "showTitle": True,
                "showEntitiesSelect": True,
                "showDashboardTimewindow": True,
            },
        },
        "name": "Campus NOC",
        "resources": [],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(dashboard, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
