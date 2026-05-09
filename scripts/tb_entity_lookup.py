from __future__ import annotations

from typing import Any


class EntityLookupError(RuntimeError):
    pass


def exact_entity_id_from_page(
    payload: dict[str, Any],
    *,
    expected_name: str,
    entity_label: str,
) -> str:
    items = payload.get("data") or []
    exact = [x for x in items if str(x.get("name", "")).strip() == expected_name]
    if not exact:
        return ""
    if len(exact) > 1:
        raise EntityLookupError(
            f"Ambiguous {entity_label} lookup for {expected_name!r}: {len(exact)} exact matches"
        )
    return exact[0]["id"]["id"]
