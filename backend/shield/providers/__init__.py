"""Read-only mail providers (Gmail, demo inbox)."""
from shield.providers.base import MailProvider, ProviderAuthError, ProviderTemporaryError, RawMessageRef

__all__ = ["MailProvider", "ProviderAuthError", "ProviderTemporaryError", "RawMessageRef"]
