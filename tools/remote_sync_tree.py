# coding=utf-8
"""Reliable directory sync to remote host via ssh with tar extraction and manifest verification."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import shlex
import subprocess
import sys
import tarfile
from pathlib import Path, PurePosixPath


def _run(
    command: list[str],
    *,
    input_bytes: bytes | None = None,
    step: str,
    echo_output: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    proc = subprocess.run(
        command,
        input=input_bytes,
        capture_output=True,
        check=False,
    )
    if echo_output and proc.stdout:
        sys.stdout.buffer.write(proc.stdout)
    if echo_output and proc.stderr:
        sys.stderr.buffer.write(proc.stderr)
    if proc.returncode != 0:
        raise RuntimeError(f"{step} failed with exit code {proc.returncode}")
    return proc


def _collect_manifest(local_dir: Path) -> list[dict[str, str | int]]:
    rows: list[dict[str, str | int]] = []
    for path in sorted(local_dir.rglob("*")):
        if not path.is_file():
            continue
        relative = str(path.relative_to(local_dir)).replace("\\", "/")
        payload = path.read_bytes()
        rows.append(
            {
                "path": relative,
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest().lower(),
            }
        )
    return rows


def _build_archive(local_dir: Path, manifest: list[dict[str, str | int]]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for row in manifest:
            arcname = str(row["path"])
            archive.add(local_dir / arcname, arcname=arcname)
    return buffer.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync a local directory to a remote host over ssh.")
    parser.add_argument("--local-dir", required=True, help="Local directory path")
    parser.add_argument("--remote-host", required=True, help="Remote ssh host")
    parser.add_argument("--remote-dir", required=True, help="Remote directory path")
    parser.add_argument("--label", default="tree", help="Label for log/error messages")
    args = parser.parse_args()

    local_dir = Path(args.local_dir).resolve()
    if not local_dir.exists() or not local_dir.is_dir():
        raise FileNotFoundError(f"{args.label} local directory missing: {local_dir}")

    manifest = _collect_manifest(local_dir)
    remote_dir = str(PurePosixPath(args.remote_dir))
    remote_archive = str(PurePosixPath(remote_dir) / ".sync-upload.tar.gz")

    _run(
        ["ssh.exe", "-o", "BatchMode=yes", args.remote_host, f"mkdir -p {shlex.quote(remote_dir)}"],
        step=f"{args.label} mkdir",
    )

    archive_bytes = _build_archive(local_dir, manifest)
    _run(
        ["ssh.exe", "-o", "BatchMode=yes", args.remote_host, f"cat > {shlex.quote(remote_archive)}"],
        input_bytes=archive_bytes,
        step=f"{args.label} upload",
    )

    verify_code = f"""
import hashlib
import json
import tarfile
from pathlib import Path

remote_dir = Path({remote_dir!r})
archive = Path({remote_archive!r})
manifest = json.loads({json.dumps(json.dumps(manifest, ensure_ascii=False))})

remote_dir.mkdir(parents=True, exist_ok=True)
with tarfile.open(archive, "r:gz") as tf:
    tf.extractall(remote_dir)

bad = []
for row in manifest:
    path = remote_dir / row["path"]
    if not path.exists():
        bad.append((row["path"], "missing"))
        continue
    payload = path.read_bytes()
    size = len(payload)
    sha256 = hashlib.sha256(payload).hexdigest().lower()
    if size != int(row["size"]):
        bad.append((row["path"], f"size:{{size}}!={{row['size']}}"))
    elif sha256 != str(row["sha256"]).lower():
        bad.append((row["path"], "sha256_mismatch"))

archive.unlink(missing_ok=True)

if bad:
    for item in bad[:20]:
        print(f"BAD {{item[0]}} {{item[1]}}")
    raise SystemExit(1)

print(json.dumps({{
    "files": len(manifest),
    "bytes": sum(int(row["size"]) for row in manifest),
}}, ensure_ascii=False))
"""
    proc = _run(
        ["ssh.exe", "-o", "BatchMode=yes", args.remote_host, "python3 -"],
        input_bytes=verify_code.encode("utf-8"),
        step=f"{args.label} verify",
        echo_output=False,
    )
    output = proc.stdout.decode("utf-8", errors="replace").strip()
    if output:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
