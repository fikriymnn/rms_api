from pydantic import BaseModel, ConfigDict
from pydantic import BaseModel, ConfigDict, Field

ROLE_KEY = r"^[a-z][a-z0-9_]{1,19}$"


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=50, pattern=r"^[A-Za-z0-9._-]+$")
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(min_length=1, max_length=100)
    position: str = Field(default="", max_length=100)
    role: str = Field(pattern=ROLE_KEY)
    outlet_id: str | None = None  # manager: diabaikan/dipaksa ke outletnya sendiri


class UserUpdate(BaseModel):
    """PATCH: hanya kolom yang dikirim yang diubah."""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    position: str | None = Field(default=None, max_length=100)
    role: str | None = Field(default=None, pattern=ROLE_KEY)
    outlet_id: str | None = None  # hanya owner


class PasswordReset(BaseModel):
    new_password: str = Field(min_length=8, max_length=128)


class UserOut(BaseModel):
    """Sengaja tanpa password_hash."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    username: str
    name: str
    position: str
    role: str
    outlet_id: str | None
    active: bool
    must_change_password: bool = False


class SessionUserOut(UserOut):
    """Untuk login & /auth/me: menyertakan nama role dan izin efektif."""

    role_name: str = ""
    permissions: list[str] = []
