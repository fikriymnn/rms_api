"""Impor semua model agar terdaftar di Base.metadata (dipakai Alembic)."""

from app.features.auth.models import RefreshToken  # noqa: F401
from app.features.outlets.models import Outlet  # noqa: F401
from app.features.sync.models import Counter, Doc  # noqa: F401
from app.features.users.models import User  # noqa: F401
from app.features.attendance.models import Attendance  # noqa: F401
from app.features.approvals.models import ApprovalRequest  # noqa: F401
from app.features.notifications.models import DeviceToken, Notification  # noqa: F401
from app.features.attendance.models import Attendance, ConsentEvent  # noqa: F401
