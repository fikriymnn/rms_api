from pydantic import BaseModel, Field

KEY_PATTERN = r"^[a-z][a-z0-9_]{1,19}$"


class RoleCreate(BaseModel):
    key: str = Field(pattern=KEY_PATTERN)
    name: str = Field(min_length=2, max_length=60)
    description: str = Field(default="", max_length=255)
    is_staff: bool = False
    permissions: list[str] = []


class RoleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=60)
    description: str | None = Field(default=None, max_length=255)
    is_staff: bool | None = None
    permissions: list[str] | None = None


class RoleOut(BaseModel):
    key: str
    name: str
    description: str
    is_system: bool
    is_staff: bool
    locked: bool  # owner: tidak bisa diubah/dihapus
    permissions: list[str]
    user_count: int
