"""
Phone OTP service abstraction.

The final SRS uses Twilio Verify for phone OTP. Stage 1 does not wire up
a real Twilio account and does not fake successful verification. This
module exists purely as the extension point a later stage will fill in
without touching any other file — views/serializers should only ever
call `OTPService`, never talk to Twilio directly.

TODO (later stage):
  - Implement TwilioOTPService using `twilio.rest.Client` with
    settings.TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN /
    TWILIO_VERIFY_SERVICE_SID.
  - Swap `get_otp_service()` to return TwilioOTPService when those
    settings are populated.
  - Add rate limiting (Redis-backed) around send/verify.
"""

from django.conf import settings


class OTPServiceUnavailable(Exception):
    """Raised when no real OTP backend is configured."""


class BaseOTPService:
    def send_otp(self, phone_number: str) -> None:
        raise NotImplementedError

    def verify_otp(self, phone_number: str, code: str) -> bool:
        raise NotImplementedError


class UnconfiguredOTPService(BaseOTPService):
    """
    Used whenever Twilio credentials are absent (the default for local
    development in Stage 1). It never pretends to succeed — it raises,
    so callers can surface a clear "phone verification not available"
    message instead of silently marking a user as verified.
    """

    def send_otp(self, phone_number: str) -> None:
        raise OTPServiceUnavailable(
            "Phone OTP is not configured for this environment. "
            "Set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN and "
            "TWILIO_VERIFY_SERVICE_SID to enable it."
        )

    def verify_otp(self, phone_number: str, code: str) -> bool:
        raise OTPServiceUnavailable(
            "Phone OTP is not configured for this environment."
        )


def get_otp_service() -> BaseOTPService:
    if (
        settings.TWILIO_ACCOUNT_SID
        and settings.TWILIO_AUTH_TOKEN
        and settings.TWILIO_VERIFY_SERVICE_SID
    ):
        # A later stage implements and returns TwilioOTPService here.
        raise NotImplementedError(
            "Twilio credentials are configured but TwilioOTPService has "
            "not been implemented yet — that lands in a later stage."
        )
    return UnconfiguredOTPService()


# ==================================================
# Trust Score Service (Stage 2)
# ==================================================

MIN_TRUST_SCORE = 0
MAX_TRUST_SCORE = 100
INITIAL_TRUST_SCORE = 100


class TrustScoreService:
    """
    Centralized service for managing and mutating user trust scores.
    Guarantees that all updates respect the valid range (0-100).
    """

    MIN_SCORE = MIN_TRUST_SCORE
    MAX_SCORE = MAX_TRUST_SCORE
    INITIAL_SCORE = INITIAL_TRUST_SCORE

    @classmethod
    def clamp_score(cls, score: int) -> int:
        """Clamp score to valid boundaries [MIN_SCORE, MAX_SCORE]."""
        return max(cls.MIN_SCORE, min(cls.MAX_SCORE, int(score)))

    @classmethod
    def set_trust_score(cls, user, score: int) -> int:
        """Set a user's trust score to a specific valid value."""
        clamped = cls.clamp_score(score)
        user.trust_score = clamped
        user.save(update_fields=["trust_score", "updated_at"])
        return user.trust_score

    @classmethod
    def increase_trust_score(cls, user, amount: int) -> int:
        """Increase a user's trust score by an amount, capping at MAX_SCORE."""
        if amount < 0:
            raise ValueError("Amount to increase must be non-negative.")
        return cls.set_trust_score(user, user.trust_score + amount)

    @classmethod
    def decrease_trust_score(cls, user, amount: int) -> int:
        """Decrease a user's trust score by an amount, floored at MIN_SCORE."""
        if amount < 0:
            raise ValueError("Amount to decrease must be non-negative.")
        return cls.set_trust_score(user, user.trust_score - amount)

    @classmethod
    def reset_trust_score(cls, user) -> int:
        """Reset a user's trust score to the default initial value (100)."""
        return cls.set_trust_score(user, cls.INITIAL_SCORE)


# Convenience module-level functions
clamp_trust_score = TrustScoreService.clamp_score
set_trust_score = TrustScoreService.set_trust_score
increase_trust_score = TrustScoreService.increase_trust_score
decrease_trust_score = TrustScoreService.decrease_trust_score
reset_trust_score = TrustScoreService.reset_trust_score

