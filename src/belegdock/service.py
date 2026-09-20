from typing import Any

from .workflow import Store


def refresh_remote_inventory(store: Store, remote: Any) -> dict[str, Any]:
    try:
        inventory = remote.inventory(
            include_archived=True, expected_organization_id=store.remote_organization()
        )
        files = []
        for item in inventory["files"]:
            enriched = dict(item)
            cached = store.cached_remote_hash(inventory["organizationId"], item)
            enriched["hash"] = cached if cached is not None else remote.hash_file(item["id"])
            files.append(enriched)
        store.refresh_remote(inventory["organizationId"], files)
        return {"organizationId": inventory["organizationId"], "count": len(files)}
    except Exception:
        store.record_refresh_failure("remote_refresh_failed")
        raise
