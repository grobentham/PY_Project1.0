from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import zipfile
from pathlib import Path, PurePosixPath
from typing import Dict, Optional, Tuple

from .constants import CANONICAL_R6_ZIP_SHA256
from .r6_source_probe import probe_frozen_r6_source


class R6SourceBundleError(RuntimeError):
    pass


BUNDLE_VERSION = "R7_R1_R6_SOURCE_BUNDLE_V1"
REQUIRED_SOURCE_FILES: Tuple[str, ...] = (
    "v16r6/engine.py",
    "v16r5/engine.py",
    "V16_R5_MAIN.py",
)
MAX_SOURCE_FILE_BYTES = 8 * 1024 * 1024


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _normalize_member(name: str) -> str:
    if not isinstance(name, str) or not name:
        raise R6SourceBundleError("R6_ZIP_MEMBER_NAME_INVALID")
    normalized = name.replace("\\", "/")
    pure = PurePosixPath(normalized)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise R6SourceBundleError("R6_ZIP_UNSAFE_MEMBER_PATH:" + name)
    if pure.parts and ":" in pure.parts[0]:
        raise R6SourceBundleError("R6_ZIP_UNSAFE_MEMBER_DRIVE:" + name)
    return pure.as_posix()


def extract_canonical_source_bundle(
    parent_zip: Path,
    output_root: Path,
    *,
    expected_parent_sha256: str = CANONICAL_R6_ZIP_SHA256,
    replace_existing: bool = True,
) -> Dict:
    parent_zip = Path(parent_zip).resolve()
    output_root = Path(output_root).resolve()
    if not parent_zip.is_file():
        raise R6SourceBundleError("CANONICAL_R6_ZIP_MISSING")
    expected = str(expected_parent_sha256).lower()
    if len(expected) != 64:
        raise R6SourceBundleError("EXPECTED_PARENT_SHA256_INVALID")
    actual_parent_sha = _sha256_file(parent_zip)
    if actual_parent_sha != expected:
        raise R6SourceBundleError(
            "CANONICAL_R6_SHA256_MISMATCH:expected=" + expected + ":actual=" + actual_parent_sha
        )

    selected: Dict[str, zipfile.ZipInfo] = {}
    try:
        with zipfile.ZipFile(parent_zip, "r") as archive:
            for info in archive.infolist():
                normalized = _normalize_member(info.filename)
                if normalized not in REQUIRED_SOURCE_FILES:
                    continue
                if normalized in selected:
                    raise R6SourceBundleError("R6_ZIP_DUPLICATE_REQUIRED_MEMBER:" + normalized)
                if info.is_dir():
                    raise R6SourceBundleError("R6_ZIP_REQUIRED_MEMBER_IS_DIRECTORY:" + normalized)
                if info.file_size < 0 or info.file_size > MAX_SOURCE_FILE_BYTES:
                    raise R6SourceBundleError("R6_ZIP_SOURCE_SIZE_INVALID:" + normalized)
                selected[normalized] = info

            missing = sorted(set(REQUIRED_SOURCE_FILES) - set(selected))
            if missing:
                raise R6SourceBundleError("R6_ZIP_REQUIRED_SOURCE_MISSING:" + ",".join(missing))

            if output_root.exists():
                if not replace_existing:
                    raise R6SourceBundleError("R6_SOURCE_BUNDLE_OUTPUT_EXISTS")
                if output_root == output_root.anchor or output_root.parent == output_root:
                    raise R6SourceBundleError("R6_SOURCE_BUNDLE_OUTPUT_ROOT_UNSAFE")
                shutil.rmtree(output_root)
            output_root.mkdir(parents=True, exist_ok=False)

            files: Dict[str, Dict[str, object]] = {}
            for relative in REQUIRED_SOURCE_FILES:
                info = selected[relative]
                raw = archive.read(info)
                if len(raw) != info.file_size:
                    raise R6SourceBundleError("R6_ZIP_SOURCE_SIZE_MISMATCH:" + relative)
                try:
                    raw.decode("utf-8-sig")
                except UnicodeDecodeError as exc:
                    raise R6SourceBundleError("R6_ZIP_SOURCE_NOT_UTF8:" + relative) from exc
                target = output_root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(raw)
                files[relative] = {
                    "sha256": _sha256_bytes(raw),
                    "size_bytes": len(raw),
                }
    except zipfile.BadZipFile as exc:
        raise R6SourceBundleError("CANONICAL_R6_ZIP_INVALID") from exc

    probe = probe_frozen_r6_source(output_root)
    probe_path = output_root / "R7_R1_R6_SOURCE_PROBE.json"
    probe_path.write_text(json.dumps(probe, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    for relative in REQUIRED_SOURCE_FILES:
        probed_hash = str(probe["files"][relative]["sha256"])
        if probed_hash != files[relative]["sha256"]:
            raise R6SourceBundleError("R6_SOURCE_PROBE_HASH_DISAGREEMENT:" + relative)

    manifest = {
        "bundle_version": BUNDLE_VERSION,
        "canonical_parent_zip_sha256": actual_parent_sha,
        "source_only_bundle": True,
        "strategy_executed": False,
        "strategy_retuned": False,
        "final_holdout_accessed": False,
        "producer_admitted": False,
        "files": files,
        "source_probe_file": probe_path.name,
        "source_probe_sha256": _sha256_file(probe_path),
    }
    manifest_path = output_root / "R7_R1_R6_SOURCE_BUNDLE_MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract only exact frozen R5/R6 producer source from the canonical R6 ZIP"
    )
    parser.add_argument("--zip", dest="parent_zip", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = extract_canonical_source_bundle(args.parent_zip, args.output)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
