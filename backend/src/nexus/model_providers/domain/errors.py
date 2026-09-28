"""Model provider domain errors."""


class ModelProviderConfigurationError(ValueError):
    """Raised when provider/model configuration is invalid."""


__all__ = ["ModelProviderConfigurationError"]
