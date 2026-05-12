"""领域仓库层：封装存储细节，业务层只操作领域语义"""
from app.repositories.oauth_state_repo import OAuthStateRepository
from app.repositories.email_verification_repo import (
    EmailVerificationRepository,
    VerificationRecord,
    VerificationLookup,
)

__all__ = [
    "OAuthStateRepository",
    "EmailVerificationRepository",
    "VerificationRecord",
    "VerificationLookup",
]
