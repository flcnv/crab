import asyncio
from collections.abc import AsyncIterable
from pathlib import Path


class LocalStorage:
    def __init__(self, root: Path) -> None:
        self.root = root

    def local_path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root.resolve()):
            raise ValueError(f"storage key escapes the storage root: {key!r}")
        return path

    async def put(self, key: str, data: bytes) -> str:
        path = self.local_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(path.write_bytes, data)
        return key

    async def put_stream(self, key: str, chunks: AsyncIterable[bytes]) -> int:
        path = self.local_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.part")
        size = 0
        try:
            with tmp.open("wb") as f:
                async for chunk in chunks:
                    await asyncio.to_thread(f.write, chunk)
                    size += len(chunk)
            tmp.replace(path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        return size

    async def get(self, key: str) -> bytes:
        return await asyncio.to_thread(self.local_path(key).read_bytes)

    async def delete(self, key: str) -> None:
        self.local_path(key).unlink(missing_ok=True)
