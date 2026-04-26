from fastapi import APIRouter, Depends

from app.providers.registry import ProviderRegistry, get_registry
from app.providers.schema import ProviderCapabilities

router = APIRouter()


@router.get("/capabilities", response_model=ProviderCapabilities)
def capabilities(registry: ProviderRegistry = Depends(get_registry)):
    return registry.capabilities()
