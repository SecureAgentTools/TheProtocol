"""Smart transfer — unified auto-routed value movement (`POST /api/v1/teg/send`)."""
from .client import TransferClient, SmartSendError

__all__ = ["TransferClient", "SmartSendError"]
