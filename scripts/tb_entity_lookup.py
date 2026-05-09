from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any


class EntityLookupError(RuntimeError):
    pass


class EntityNotFoundError(EntityLookupError):
    pass


class EntityAmbiguousError(EntityLookupError):
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
        raise EntityNotFoundError(
            f'{entity_label.capitalize()} "{expected_name}" not found in candidate set'
        )
    if len(exact) > 1:
        raise EntityAmbiguousError(
            f"Ambiguous {entity_label} lookup for {expected_name!r}: {len(exact)} exact matches"
        )
    return exact[0]["id"]["id"]


def resolve_exact_entity_id_sync(
    *,
    expected_name: str,
    entity_label: str,
    fetch_page: Callable[[int], dict[str, Any]],
    max_pages: int = 200,
) -> str:
    """Resolve exact entity id by scanning paginated candidate pages."""
    matches: list[dict[str, Any]] = []
    for page in range(max_pages):
        payload = fetch_page(page)
        rows = payload.get("data") or []
        matches.extend([x for x in rows if str(x.get("name", "")).strip() == expected_name])
        if not payload.get("hasNext", False):
            break
    if not matches:
        raise EntityNotFoundError(f'{entity_label.capitalize()} "{expected_name}" not found')
    if len(matches) > 1:
        raise EntityAmbiguousError(
            f"Ambiguous {entity_label} lookup for {expected_name!r}: {len(matches)} exact matches"
        )
    return matches[0]["id"]["id"]


async def resolve_exact_entity_id_async(
    *,
    expected_name: str,
    entity_label: str,
    fetch_page: Callable[[int], Awaitable[dict[str, Any]]],
    max_pages: int = 200,
) -> str:
    """Async variant of exact paginated entity resolution."""
    matches: list[dict[str, Any]] = []
    for page in range(max_pages):
        payload = await fetch_page(page)
        rows = payload.get("data") or []
        matches.extend([x for x in rows if str(x.get("name", "")).strip() == expected_name])
        if not payload.get("hasNext", False):
            break
    if not matches:
        raise EntityNotFoundError(f'{entity_label.capitalize()} "{expected_name}" not found')
    if len(matches) > 1:
        raise EntityAmbiguousError(
            f"Ambiguous {entity_label} lookup for {expected_name!r}: {len(matches)} exact matches"
        )
    return matches[0]["id"]["id"]
