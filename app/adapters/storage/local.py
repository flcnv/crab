"""Local filesystem storage. Same interface as a future S3 adapter."""

from pathlib import Path


class LocalStorage:
    def __init__(self, root: Path) -> None:
        self.root = root

    def local_path(self, key: str) -> Path:
        return self.root / key

    async def put(self, key: str, data: bytes) -> str:
        path = self.local_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return key

    async def get(self, key: str) -> bytes:
        return self.local_path(key).read_bytes()
