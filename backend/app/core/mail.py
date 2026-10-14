"""AWS SES adapter — the outbound-mail seam.

``MailClient`` is the Protocol the use cases depend on; ``Boto3MailClient`` is the real
implementation over SES v2; tests inject an in-memory fake by overriding ``get_mail_client``.
boto3 is synchronous, so every send runs in a worker thread. botocore ``ClientError``s are
translated to ``AppError`` here, so callers never see provider-specific exceptions.

The sender and the SES region are fixed in code (``mail_settings``); the identity's default
configuration set applies server-side. While the AWS account is in the SES sandbox, only verified
recipients are accepted (anything else is ``MessageRejected``).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from email.utils import formataddr
from functools import cache
from typing import TYPE_CHECKING, Annotated, Protocol

import boto3  # noqa: TID251
from botocore.exceptions import ClientError  # noqa: TID251
from fastapi import Depends

from app.core.config import aws_settings, mail_settings
from app.core.exceptions import AppError
from app.core.logging_config import get_logger

if TYPE_CHECKING:
    from mypy_boto3_sesv2 import SESV2Client
    from mypy_boto3_sesv2.type_defs import DestinationTypeDef, EmailContentTypeDef

logger = get_logger(__name__)

_CHARSET = "UTF-8"
# The sending account is throttled, paused or suspended: nothing about the message is wrong.
_UNAVAILABLE_CODES = frozenset(
    {"TooManyRequestsException", "LimitExceededException", "SendingPausedException", "AccountSuspendedException"}
)


@dataclass(frozen=True, slots=True)
class Mail:
    to: str
    subject: str
    text: str
    html: str


class MailClient(Protocol):
    async def send(self, mail: Mail) -> None: ...


# ── botocore error translation ────────────────────────────────────────────────


def _translate(error: ClientError) -> AppError:
    """Map an SES ``ClientError`` to the ``AppError`` the client should see.

    Nothing maps to a 4xx: the recipient is a stored user's address, so a rejection (sandbox,
    unverified MAIL FROM, malformed content) is an operational problem, not the caller's.
    """
    info = error.response.get("Error")
    code = "" if info is None else info.get("Code", "")
    if code in _UNAVAILABLE_CODES:
        return AppError.service_unavailable("Email service is busy, please retry", cause=error, ses_code=code)
    return AppError.internal("Email could not be sent", cause=error, ses_code=code)


# ── boto3 implementation ─────────────────────────────────────────────────────


class Boto3MailClient:
    """``MailClient`` over boto3 ``sesv2``."""

    def __init__(self, *, region: str, sender: str, access_key_id: str | None, secret_access_key: str | None) -> None:
        # Credentials are optional: None → boto3's default chain (env vars, profile, IAM role).
        # boto3-stubs types `client` as one overload per AWS service; the ones whose stub
        # package isn't installed return Unknown, which strict mode flags on the member access
        # even though the sesv2 overload we hit is fully typed.
        self._client: SESV2Client = boto3.client(  # pyright: ignore[reportUnknownMemberType]
            "sesv2",
            region_name=region,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
        )
        self._sender = sender

    async def send(self, mail: Mail) -> None:
        destination: DestinationTypeDef = {"ToAddresses": [mail.to]}
        content: EmailContentTypeDef = {
            "Simple": {
                "Subject": {"Data": mail.subject, "Charset": _CHARSET},
                "Body": {
                    "Text": {"Data": mail.text, "Charset": _CHARSET},
                    "Html": {"Data": mail.html, "Charset": _CHARSET},
                },
            }
        }
        try:
            response = await asyncio.to_thread(
                self._client.send_email, FromEmailAddress=self._sender, Destination=destination, Content=content
            )
        except ClientError as error:
            raise _translate(error) from error
        # The recipient is personal data; the SES message id is enough to trace a delivery.
        logger.info("mail sent", ses_message_id=response["MessageId"])


# ── FastAPI wiring ───────────────────────────────────────────────────────────


@cache
def _default_client() -> Boto3MailClient:
    # Built on first use, not at import: tests override the dependency and never touch boto3.
    secret = aws_settings.aws_secret_access_key
    return Boto3MailClient(
        region=mail_settings.region,
        sender=formataddr((mail_settings.sender_name, mail_settings.sender_address)),
        access_key_id=aws_settings.aws_access_key_id,
        secret_access_key=secret.get_secret_value() if secret else None,
    )


async def get_mail_client() -> MailClient:
    return _default_client()


MailDep = Annotated[MailClient, Depends(get_mail_client)]
