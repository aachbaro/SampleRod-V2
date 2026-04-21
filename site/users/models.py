import uuid

from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """
    Local mirror of a pascuans auth-server identity.

    `oidc_sub` is the immutable UUID returned by auth.pascuans.dev.
    `username` is kept (inherited from AbstractUser) but we never rely on it;
    login always goes through OIDC.
    """

    oidc_sub = models.UUIDField(unique=True, null=True, blank=True)
    email = models.EmailField(unique=True)

    USERNAME_FIELD = "username"
    REQUIRED_FIELDS = ["email"]

    def __str__(self) -> str:
        return self.email or self.username

    @classmethod
    def from_oidc_claims(cls, claims: dict) -> "User":
        sub = claims.get("sub")
        if not sub:
            raise ValueError("OIDC claims missing 'sub'")
        email = claims.get("email") or f"{sub}@pascuans.local"
        try:
            sub_uuid = uuid.UUID(str(sub))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid OIDC sub: {sub!r}") from exc

        user, _ = cls.objects.update_or_create(
            oidc_sub=sub_uuid,
            defaults={
                "email": email,
                "username": email or str(sub_uuid),
                "first_name": claims.get("given_name", "") or "",
                "last_name": claims.get("family_name", "") or "",
            },
        )
        return user
