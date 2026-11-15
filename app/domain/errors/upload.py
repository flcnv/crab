class InvalidUploadError(ValueError): ...


class UploadTooLargeError(ValueError):
    def __init__(self, max_bytes: int) -> None:
        super().__init__(f"upload exceeds the limit of {max_bytes} bytes")
        self.max_bytes = max_bytes
