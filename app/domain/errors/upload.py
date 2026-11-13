class InvalidUploadError(ValueError):
    """Upload rejected by domain rules (unsupported type, mixed media, too many files)."""


class UploadTooLargeError(ValueError):
    def __init__(self, max_bytes: int) -> None:
        super().__init__(f"upload exceeds the limit of {max_bytes} bytes")
        self.max_bytes = max_bytes
