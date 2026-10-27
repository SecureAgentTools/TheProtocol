"""
AgentVault Registry Services
"""

from .webhook_service import (
    WebhookService,
    webhook_service,
    emit_agent_event,
    emit_staking_event,
    emit_governance_event,
    emit_federation_event
)

from .export_import_service import (
    ExportImportService,
    export_import_service
)

from .vetoken_calculator import (
    VeTokenCalculator,
    vetoken_calculator
)

# Conditional import for 2FA (in case pyotp not installed yet)
try:
    from .two_factor_auth import (
        TwoFactorAuthService,
        TwoFactorResponse
    )
    _2FA_AVAILABLE = True
except ImportError:
    # If pyotp not installed, create dummy classes
    class TwoFactorAuthService:
        @staticmethod
        def generate_partial_token(*args, **kwargs):
            raise RuntimeError("2FA not available. Please install: pip install pyotp qrcode[pil]")
    
    class TwoFactorResponse:
        pass
    
    _2FA_AVAILABLE = False

__all__ = [
    "WebhookService",
    "webhook_service",
    "emit_agent_event",
    "emit_staking_event",
    "emit_governance_event",
    "emit_federation_event",
    "TwoFactorAuthService",
    "TwoFactorResponse",
    "ExportImportService",
    "export_import_service",
    "VeTokenCalculator",
    "vetoken_calculator"
]
