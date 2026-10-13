"""Impor semua model agar terdaftar di Base.metadata (dipakai Alembic)."""

from app.features.auth.models import RefreshToken  # noqa: F401
from app.features.outlets.models import Outlet  # noqa: F401
from app.features.sync.models import Counter, Doc  # noqa: F401
from app.features.users.models import User  # noqa: F401
