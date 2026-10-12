"""Download a pinned official model snapshot with size and digest verification."""

import argparse
import hashlib
import json
import shutil
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path, PurePosixPath
from urllib.parse import quote

MODEL = "google/embeddinggemma-2"
REVISION = "914f7f89142e33e77833254d9c9b90c3cef7303b"


def download_ranges(url: str, partial: Path, size: int) -> None:
    """Bounded concurrent ranges, persisted independently and checked before assembly."""
    chunk_size = 4 * 1024 * 1024
    pieces = partial.with_name(partial.name + ".chunks")
    pieces.mkdir(exist_ok=True)
    starts = list(range(0, size, chunk_size))
    # Reuse complete ranges from a previous sequential download.
    if partial.exists():
        with partial.open("rb") as handle:
            for start in starts:
                expected = min(chunk_size, size - start)
                data = handle.read(expected)
                if len(data) != expected:
                    break
                target = pieces / str(start)
                if not target.exists():
                    target.write_bytes(data)

    def one(start: int) -> Path:
        end = min(start + chunk_size, size) - 1
        expected = end - start + 1
        target = pieces / str(start)
        if target.exists() and target.stat().st_size == expected:
            return target
        temporary = target.with_suffix(".tmp")
        for attempt in range(3):
            try:
                request = urllib.request.Request(
                    url, headers={"Range": f"bytes={start}-{end}"}
                )
                with urllib.request.urlopen(request, timeout=30) as response:
                    if (
                        response.status != 206
                        or response.headers.get("Content-Range")
                        != f"bytes {start}-{end}/{size}"
                    ):
                        raise ValueError("Server returned an unexpected model range")
                    with temporary.open("wb") as handle:
                        while data := response.read(min(1024 * 1024, expected + 1)):
                            handle.write(data)
                            if handle.tell() > expected:
                                raise ValueError("Model range exceeded expected length")
                if temporary.stat().st_size != expected:
                    raise ValueError("Incomplete model range")
                temporary.replace(target)
                return target
            except (OSError, ValueError):
                temporary.unlink(missing_ok=True)
                if attempt == 2:
                    raise
                time.sleep(1)
        raise RuntimeError("Unreachable download state")

    with ThreadPoolExecutor(max_workers=32) as workers:
        futures = [workers.submit(one, start) for start in starts]
        for count, future in enumerate(as_completed(futures), 1):
            future.result()
            if count % 32 == 0 or count == len(starts):
                print(f"  {100 * count / len(starts):.0f}%", flush=True)
    with partial.open("wb") as handle:
        for start in starts:
            with (pieces / str(start)).open("rb") as piece:
                shutil.copyfileobj(piece, handle)


def digest(path: Path, item: dict) -> str:
    algorithm = hashlib.sha256() if item.get("lfs") else hashlib.sha1()
    if not item.get("lfs"):
        algorithm.update(f"blob {path.stat().st_size}\0".encode())
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            algorithm.update(chunk)
    return algorithm.hexdigest()


def download(directory: Path) -> None:
    url = f"https://huggingface.co/api/models/{MODEL}/tree/{REVISION}?recursive=true"
    with urllib.request.urlopen(url, timeout=30) as response:
        items = json.load(response)
    directory.mkdir(parents=True, exist_ok=True)
    # A rerun must revalidate every file before advertising readiness again.
    (directory / "edge-model.json").unlink(missing_ok=True)
    for item in items:
        if item["type"] != "file" or item["path"] in {"README.md", ".gitattributes"}:
            continue
        relative = PurePosixPath(item["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Invalid model file path")
        destination = directory.joinpath(*relative.parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        expected = item.get("lfs", {}).get("oid", item["oid"])
        if (
            destination.exists()
            and destination.stat().st_size == item["size"]
            and digest(destination, item) == expected
        ):
            continue
        partial = destination.with_name(destination.name + ".part")
        offset = partial.stat().st_size if partial.exists() else 0
        if offset >= item["size"]:
            if offset == item["size"] and digest(partial, item) == expected:
                partial.replace(destination)
                continue
            partial.unlink()
            offset = 0
        request = urllib.request.Request(
            f"https://huggingface.co/{MODEL}/resolve/{REVISION}/{quote(str(relative))}",
            headers={"Range": f"bytes={offset}-"} if offset else {},
        )
        print(
            f"Downloading {relative} ({item['size'] / 1024 / 1024:.1f} MB)", flush=True
        )
        started, reported = time.monotonic(), offset
        if item["size"] > 4 * 1024 * 1024:
            download_ranges(request.full_url, partial, item["size"])
            if digest(partial, item) != expected:
                partial.unlink(missing_ok=True)
                shutil.rmtree(partial.with_name(partial.name + ".chunks"))
                raise ValueError(f"Integrity check failed for {relative}")
            partial.replace(destination)
            shutil.rmtree(partial.with_name(partial.name + ".chunks"))
            print(
                f"Verified {relative} in {time.monotonic() - started:.1f}s", flush=True
            )
            continue
        with urllib.request.urlopen(request, timeout=30) as response:
            if offset and response.status != 206:
                offset = 0
            with partial.open("ab" if offset else "wb") as handle:
                while chunk := response.read(1024 * 1024):
                    handle.write(chunk)
                    offset += len(chunk)
                    if offset > item["size"]:
                        raise ValueError("Model file exceeded declared size")
                    if offset - reported >= 128 * 1024 * 1024:
                        print(f"  {100 * offset / item['size']:.0f}%", flush=True)
                        reported = offset
        if offset != item["size"] or digest(partial, item) != expected:
            partial.unlink(missing_ok=True)
            raise ValueError(f"Integrity check failed for {relative}")
        partial.replace(destination)
        print(f"Verified {relative} in {time.monotonic() - started:.1f}s", flush=True)
    manifest = {"model": MODEL, "revision": REVISION}
    marker = directory / "edge-model.json"
    temporary = marker.with_suffix(".tmp")
    temporary.write_text(json.dumps(manifest))
    temporary.replace(marker)
    print("Model snapshot is ready.", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--directory", type=Path, default=Path("data/models/embeddinggemma-2")
    )
    download(parser.parse_args().directory)
