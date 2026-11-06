"""Live public-channel smoke for TRAMA Preview. No credentials, vault or AI.

It intentionally downloads only official, already published Preview assets.
Designed to run on a disposable Windows GitHub Actions runner.
"""
from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

from knowledge_bridge.update_service import (
    VERSION, check_preview_release, download_verified_preview_installer,
    check_release, preview_build_number,
)

REPO = "Marco-Oliver/TRAMA"


def run():
    baseline = "2.2.0-preview.188"
    latest = check_preview_release(REPO, baseline)
    assert latest.get("ok") and latest.get("available"), latest
    tag = latest["version"]
    assert preview_build_number(tag) is not None
    assert preview_build_number(tag) > 188
    assert latest["release_page"] == f"https://github.com/{REPO}/releases/tag/{tag}"
    assert not check_preview_release(REPO, tag).get("available"), (
        "Already-updated Preview must not download itself again.")
    with tempfile.TemporaryDirectory(prefix="trama-preview-real-api-") as temp:
        result = download_verified_preview_installer(REPO, baseline, temp)
        assert result["ok"], result
        target = Path(result["path"])
        assert target.name == f"TRAMA_Preview_Setup_{tag}.exe"
        assert target.stat().st_size > 1000
        with target.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        assert result["sha256"] == digest
        assert not list(Path(temp).glob("*.part"))
        print(f"PASS: public API + EXE download + SHA-256: {tag}, {target.stat().st_size} bytes")
    stable = check_release(REPO)
    assert stable.get("ok") and stable.get("version") == "v2.2.0" and not stable.get("available"), stable
    assert VERSION == "2.2.0", VERSION
    print("PASS: stable release lookup unaffected by experimental prereleases.")


if __name__ == "__main__":
    run()
