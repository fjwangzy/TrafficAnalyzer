"""Authentication schemas."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator


class UserBase(BaseModel):
    """Base user schema."""
    username: str = Field(..., min_length=3, max_length=50)
    email: EmailStr
    role: str = Field(default="viewer", pattern="^(admin|operator|viewer)$")


class UserCreate(UserBase):
    """Schema for creating a new user."""
    password: str = Field(..., min_length=8, max_length=100)


class UserLogin(BaseModel):
    """Schema for user login."""
    username: str
    password: str


class UserResponse(UserBase):
    """Schema for user response."""
    id: int
    is_active: bool
    created_at: datetime
    updated_at: datetime
    capabilities: list[str] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="after")
    def populate_capabilities(self):
        if not self.capabilities:
            mapping = {
                "admin": ["survey.read", "survey.write", "survey.review", "survey.deliver", "governance.admin"],
                "operator": ["survey.read", "survey.write", "survey.review"],
                "viewer": ["survey.read"],
            }
            self.capabilities = mapping.get(self.role, [])
        return self


class Token(BaseModel):
    """JWT token response."""
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class TokenData(BaseModel):
    """Token payload data."""
    user_id: int | None = None
    username: str | None = None
    role: str | None = None
