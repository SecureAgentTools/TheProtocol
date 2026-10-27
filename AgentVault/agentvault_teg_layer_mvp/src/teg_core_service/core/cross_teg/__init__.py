"""
Cross-TEG Transfer Protocol Implementation.

This module implements the AVTP (AgentVault Transfer Protocol) extensions
for cross-TEG transfers in separated registry architectures.
"""

from .protocol import CrossTEGTransferProtocol, TransferState
from .coordinator import DistributedTransactionCoordinator
from .messages import (
    CrossTEGTransferRequest,
    CrossTEGTransferResponse,
    TransferStatus,
    CompensationRequest,
    TransferAcceptRequest,
    TransferAcceptResponse
)

__all__ = [
    "CrossTEGTransferProtocol",
    "TransferState",
    "DistributedTransactionCoordinator",
    "CrossTEGTransferRequest",
    "CrossTEGTransferResponse",
    "TransferStatus",
    "CompensationRequest",
    "TransferAcceptRequest",
    "TransferAcceptResponse"
]
