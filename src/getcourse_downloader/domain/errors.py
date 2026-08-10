"""Application-specific exception hierarchy."""


class DownloaderError(Exception):
    """Base error safe to present to a user."""


class InvalidDataError(DownloaderError):
    """Persisted or transferred data does not match the expected schema."""


class DownloadConfigurationError(DownloaderError):
    """A download request cannot be executed with the supplied settings."""


class ExternalServiceError(DownloaderError):
    """GetCourse, Rutube, Playwright, or another external service failed."""
