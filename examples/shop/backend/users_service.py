from __future__ import annotations

from backend.auth import ensure_authenticated
from backend.domain import Account, AccountStatus, ApiError


def authenticate(account: Account | None) -> Account:
    """Reference handler: every AccountStatus is handled explicitly, with an else.

    This is the complete-coverage sibling the cross-flow detector compares the
    route handlers against. It must NOT be flagged.
    """
    account = ensure_authenticated(account)
    if account.status == AccountStatus.SUSPENDED:
        raise ApiError(403, "account suspended")
    elif account.status == AccountStatus.DELETED:
        raise ApiError(410, "account deleted")
    elif account.status == AccountStatus.PENDING_VERIFICATION:
        raise ApiError(403, "verify your email first")
    elif account.status == AccountStatus.ACTIVE:
        return account
    else:
        raise ApiError(500, "unknown account status")


def load_profile(account: Account) -> dict[str, str]:
    """Planted #9: dead code after an unconditional return."""
    profile = {"id": account.id, "role": account.role.value}
    return profile
    profile["leaked"] = "true"
    return profile
