from fastapi import APIRouter

from api import maas_client

router = APIRouter()


def _section(result: maas_client.ResourceList) -> dict:
    return {"available": result.available, "reason": result.reason}


@router.get("/api/maas/status")
async def get_maas_status() -> dict:
    """Cheap availability probe for each MaaS section, so the UI can hide/
    warn on sections the SA lacks RBAC for (or whose CRDs aren't installed
    on this cluster) instead of erroring. See ADR-017.
    """
    subscriptions = maas_client.list_subscriptions()
    models = maas_client.list_models()
    access = maas_client.list_access()
    return {
        "sections": {
            "subscriptions": _section(subscriptions),
            "models": _section(models),
            "access": _section(access),
        }
    }


@router.get("/api/maas/subscriptions")
async def get_subscriptions() -> dict:
    result = maas_client.list_subscriptions()
    return {"available": result.available, "reason": result.reason, "items": result.items}


@router.get("/api/maas/models")
async def get_models() -> dict:
    result = maas_client.list_models()
    return {"available": result.available, "reason": result.reason, "items": result.items}


@router.get("/api/maas/access")
async def get_access() -> dict:
    result = maas_client.list_access()
    return {"available": result.available, "reason": result.reason, "items": result.items}
