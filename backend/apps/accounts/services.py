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
