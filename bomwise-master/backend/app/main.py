import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: wire the provider registry from COMPONENT_PROVIDER env var.
    import logging as _logging
    from app.core.database import settings
    from app.providers.digikey import DigiKeyProvider
    from app.providers.digikey_mouser import DigiKeyMouserProvider
    from app.providers.findchips import FindChipsProvider
    from app.providers.mouser import MouserProvider
    from app.providers.nexar import NexarProvider
    from app.providers.nextpcb import NextPCBAdapter
    from app.providers.oemsecrets import OEMSecretsProvider
    from app.providers.registry import registry

    _startup_log = _logging.getLogger(__name__)

    registry.register("nexar", NexarProvider(), tier="premium")
    registry.register("findchips", FindChipsProvider(), tier="free")
    registry.register("digikey_mouser", DigiKeyMouserProvider(), tier="free")
    registry.register("oemsecrets", OEMSecretsProvider(), tier="free")

    for _name, _cls in [
        ("mouser", MouserProvider),
        ("digikey", DigiKeyProvider),
        ("nextpcb", NextPCBAdapter),
    ]:
        try:
            registry.register(_name, _cls())
        except ValueError as exc:
            _startup_log.warning("Provider %r not registered: %s", _name, exc)

    registry.set_active(settings.component_provider)

    yield


app = FastAPI(title="BOMexplorer API", version="1.0.0", lifespan=lifespan)

# CORS: allow localhost in dev, app.bomexplorer.app in production
import os as _os
_origins = ["http://localhost:5173"]
if _os.environ.get("ENVIRONMENT") == "production":
    _origins = ["https://app.bomexplorer.app"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from app.api.admin import router as admin_router  # noqa: E402
from app.api.auth import router as auth_router  # noqa: E402
from app.api.billing import router as billing_router  # noqa: E402
from app.api.capabilities import router as capabilities_router  # noqa: E402
from app.api.flags import router as flags_router  # noqa: E402
from app.api.projects import router as projects_router  # noqa: E402
from app.api.users import router as users_router  # noqa: E402
from app.api.version import router as version_router  # noqa: E402
from app.api.webhooks import router as webhooks_router  # noqa: E402

app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(users_router, prefix="/users", tags=["users"])
app.include_router(projects_router, prefix="/projects", tags=["projects"])
app.include_router(flags_router, prefix="/flags", tags=["flags"])
app.include_router(capabilities_router, prefix="/providers", tags=["providers"])
app.include_router(billing_router, tags=["billing"])
app.include_router(webhooks_router, tags=["webhooks"])
app.include_router(admin_router, tags=["admin"])
app.include_router(version_router, tags=["version"])
