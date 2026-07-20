"""Shared archive admission and member-validation policy.

The archive contents are untrusted customer input.  This module intentionally
contains no extraction code; every extractor must validate members here before
creating a filesystem entry and must still enforce actual bytes while copying.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import zipfile


def _env_int(name: str, default: int, minimum: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(minimum, int(raw))
    except ValueError:
        return default


def _env_float(name: str, default: float, minimum: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(minimum, float(raw))
    except ValueError:
        return default


@dataclass(frozen=True)
class ArchiveLimits:
    max_extracted_bytes: int
    max_members: int
    max_member_bytes: int
    max_path_depth: int
    max_name_bytes: int
    max_compression_ratio: float
    scratch_reserve_bytes: int

    @classmethod
    def from_env(cls, *, max_extracted_bytes: int) -> "ArchiveLimits":
        gib = 1024**3
        return cls(
            max_extracted_bytes=max_extracted_bytes,
            max_members=_env_int("S2RS_MAX_ARCHIVE_MEMBERS", 250_000, 1),
            max_member_bytes=_env_int("S2RS_MAX_MEMBER_GB", 10, 1) * gib,
            max_path_depth=_env_int("S2RS_MAX_PATH_DEPTH", 32, 1),
            max_name_bytes=_env_int("S2RS_MAX_MEMBER_NAME_BYTES", 4096, 64),
            max_compression_ratio=_env_float(
                "S2RS_MAX_COMPRESSION_RATIO", 1000.0, 1.0
            ),
            scratch_reserve_bytes=_env_int(
                "S2RS_SCRATCH_RESERVE_GB", 2, 0
            ) * gib,
        )


class ArchivePolicyError(ValueError):
    pass


def safe_member_path(name: str, limits: ArchiveLimits) -> PurePosixPath:
    if not isinstance(name, str) or "\x00" in name:
        raise ArchivePolicyError("Invalid archive member name")
    if len(name.encode("utf-8", "surrogatepass")) > limits.max_name_bytes:
        raise ArchivePolicyError("Archive member name exceeds safety limit")
    normalized = name.replace("\\", "/")
    if len(normalized) >= 2 and normalized[0].isalpha() and normalized[1] == ":":
        raise ArchivePolicyError(f"Invalid archive member name: {name}")
    path = PurePosixPath(normalized)
    if path.is_absolute() or ".." in path.parts:
        raise ArchivePolicyError(f"Invalid archive member name: {name}")
    meaningful_parts = [part for part in path.parts if part not in {"", "."}]
    if len(meaningful_parts) > limits.max_path_depth:
        raise ArchivePolicyError("Archive member path exceeds depth limit")
    return PurePosixPath(*meaningful_parts) if meaningful_parts else PurePosixPath(".")


def validate_member_size(size: int, limits: ArchiveLimits) -> None:
    if size < 0 or size > limits.max_member_bytes:
        raise ArchivePolicyError("Archive member exceeds per-file safety limit")


def validate_member_count(count: int, limits: ArchiveLimits) -> None:
    if count > limits.max_members:
        raise ArchivePolicyError("Archive contains too many entries")


def validate_zip_info(info: zipfile.ZipInfo, limits: ArchiveLimits) -> None:
    validate_member_size(int(info.file_size), limits)
    mode = info.external_attr >> 16
    file_type = stat.S_IFMT(mode)
    if file_type and not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
        raise ArchivePolicyError(
            f"Archive links and special files are not supported: {info.filename}"
        )
    if info.file_size > 0:
        ratio = info.file_size / max(1, info.compress_size)
        if ratio > limits.max_compression_ratio:
            raise ArchivePolicyError("Archive member compression ratio exceeds safety limit")


def require_scratch_capacity(path: Path, expected_bytes: int, limits: ArchiveLimits) -> None:
    free = shutil.disk_usage(path).free
    required = min(max(0, expected_bytes), limits.max_extracted_bytes)
    if free - limits.scratch_reserve_bytes < required:
        raise ArchivePolicyError(
            f"Insufficient scratch space: require {required} bytes plus reserve"
        )
