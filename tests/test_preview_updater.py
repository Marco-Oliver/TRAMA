"""Safe Preview in-app updates. No real release, network, Windows or secrets."""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from knowledge_bridge.update_service import (
    VERSION, check_release, check_preview_release,
    download_verified_preview_installer, preview_build_number,
)
from knowledge_bridge.bridge import Bridge


REPO = "Marco-Oliver/TRAMA"
TAG = "v2.2.0-preview.42"
ASSET = "TRAMA_Preview_Setup.exe"
CHECKSUMS = "SHA256SUMS-Preview.txt"
PREFIX = f"https://github.com/{REPO}/releases/download/{TAG}/"


def sample_release(tag=TAG, *, prerelease=True, draft=False, asset=ASSET):
    prefix=f"https://github.com/{REPO}/releases/download/{tag}/"
    return {"tag_name":tag,"prerelease":prerelease,"draft":draft,
            "html_url":f"https://github.com/{REPO}/releases/tag/{tag}",
            "assets":[{"name":asset,"browser_download_url":prefix+asset},
                      {"name":CHECKSUMS,"browser_download_url":prefix+CHECKSUMS}]}


class InMemoryReply:
    def __init__(self, body: bytes):
        self.body=body
        self.pos=0

    def __enter__(self):return self
    def __exit__(self, *_):return False

    def read(self, count=-1):
        if count is None or count<0:
            count=len(self.body)-self.pos
        part=self.body[self.pos:self.pos+count]
        self.pos+=len(part)
        return part


class GitHubPreviewStub:
    def __init__(self, releases, *, corrupt=False):
        self.releases=releases
        self.binary=b"MZ" + b"fictitious-preview-setup" * 100
        hash_hex=hashlib.sha256(self.binary).hexdigest()
        if corrupt:
            hash_hex="0"*64
        self.manifest=f"{hash_hex}  {ASSET}\n".encode()
        self.requested=[]

    def __call__(self, request, timeout=None):
        url=request.full_url if hasattr(request,'full_url') else str(request)
        self.requested.append(url)
        if url==f"https://api.github.com/repos/{REPO}/releases?per_page=40":
            return InMemoryReply(json.dumps(self.releases).encode())
        if url==PREFIX+CHECKSUMS:
            return InMemoryReply(self.manifest)
        if url==PREFIX+ASSET:
            return InMemoryReply(self.binary)
        raise AssertionError("Unexpected outgoing request: "+url)


class PreviewUpdateTests(unittest.TestCase):
    def test_preview_build_version_is_not_confused_with_stable_semver(self):
        self.assertEqual(VERSION,"2.2.1")
        self.assertEqual(preview_build_number("2.2.0-preview.41"),41)
        self.assertEqual(preview_build_number(TAG),42)
        for invalid in ("v2.2.0","v2.1.0","v2.2.0-preview",
                        "v2.2.0-preview.0","v2.2.0-preview.42?x=1",
                        "v3.0.0-preview.42","v2.2.0-preview.0042"):
            self.assertIsNone(preview_build_number(invalid),invalid)

    def test_looks_only_at_published_newer_prereleases_not_stable(self):
        fake=GitHubPreviewStub([
            sample_release(tag="v9.9.9",prerelease=False),
            sample_release(tag="v2.2.0-preview.40"),
            sample_release(tag="v2.2.0-preview.400",draft=True),
            sample_release(tag="v2.2.0-preview.43",prerelease=False),
            sample_release(),
        ])
        info=check_preview_release(REPO,"2.2.0-preview.41",opener=fake)
        self.assertTrue(info["available"])
        self.assertEqual(info["version"],TAG)
        self.assertNotIn("/releases/latest",fake.requested[0])
        self.assertEqual(len(fake.requested),1)
        info=check_preview_release(REPO,"2.2.0-preview.42",opener=fake)
        self.assertFalse(info["available"])
        self.assertNotIn("release_page",info)
        self.assertFalse(check_preview_release("evil/../repo","2.2.0-preview.40",opener=fake)["ok"])

    def test_checksum_verified_preview_can_download_without_zip(self):
        fake=GitHubPreviewStub([sample_release()])
        with tempfile.TemporaryDirectory() as directory:
            result=download_verified_preview_installer(
                REPO,"2.2.0-preview.41",directory,opener=fake)
            self.assertTrue(result["ok"],result)
            target=Path(result["path"])
            self.assertEqual(target.name,f"TRAMA_Preview_Setup_{TAG}.exe")
            self.assertEqual(target.read_bytes(),fake.binary)
            self.assertEqual(result["sha256"],hashlib.sha256(fake.binary).hexdigest())
            self.assertEqual(len(fake.requested),3)
            self.assertFalse(any(p.suffix==".part" for p in Path(directory).iterdir()))

    def test_corrupt_or_missing_preview_never_leaves_an_executable(self):
        for corrupt in (False, True):
            fake=GitHubPreviewStub([sample_release()] if corrupt else [],corrupt=corrupt)
            with self.subTest(corrupt=corrupt),tempfile.TemporaryDirectory() as directory:
                result=download_verified_preview_installer(
                    REPO,"2.2.0-preview.41",directory,opener=fake)
                self.assertFalse(result["ok"])
                self.assertEqual(list(Path(directory).glob("*.exe")),[])
        # A forged asset link cannot redirect the downloader to other hosts.
        broken=sample_release()
        broken["assets"][0]["browser_download_url"]="https://evil.test/setup.exe"
        self.assertFalse(check_preview_release(
            REPO,"2.2.0-preview.41",opener=GitHubPreviewStub([broken]))["available"])

    def test_preview_bridge_never_uses_stable_channel_or_installers(self):
        bridge=Bridge()
        with tempfile.TemporaryDirectory() as directory, \
             patch("knowledge_bridge.bridge.PREVIEW_BUNDLE",True), \
             patch.object(bridge,"_release_repo",return_value=REPO), \
             patch.object(bridge,"_preview_update_version",return_value="2.2.0-preview.41"):
            with patch("knowledge_bridge.bridge.check_release",side_effect=AssertionError("stable channel contacted")), \
                 patch("knowledge_bridge.bridge.check_preview_release",
                       return_value={"ok":True,"available":True,"version":TAG,"release_page":f"https://github.com/{REPO}/releases/tag/{TAG}"}) as preview:
                self.assertTrue(bridge.check_updates()["available"])
                preview.assert_called_once_with(REPO,"2.2.0-preview.41")
            with patch("knowledge_bridge.bridge.webbrowser.open") as browser:
                stable=f"https://github.com/{REPO}/releases/tag/v2.1.0"
                self.assertFalse(bridge.open_update_page(stable)["ok"])
                self.assertFalse(bridge.open_update_page(f"https://github.com/{REPO}/releases/tag/{TAG}?evil=1")["ok"])
                self.assertTrue(bridge.open_update_page(f"https://github.com/{REPO}/releases/tag/{TAG}")["ok"])
                browser.assert_called_once()
            setup=Path(directory)/"updates"/f"TRAMA_Setup_v9.9.9.exe"
            setup.parent.mkdir()
            setup.write_bytes(b"dummy stable installer")
            bridge._verified_installer=(str(setup),hashlib.sha256(setup.read_bytes()).hexdigest())
            with patch("knowledge_bridge.bridge.DATA_HOME",Path(directory)), \
                 patch("knowledge_bridge.bridge.sys.platform","win32"), \
                 patch("knowledge_bridge.bridge.os.startfile",create=True) as launcher:
                self.assertFalse(bridge.launch_update(str(setup),True)["ok"])
                launcher.assert_not_called()

    def test_preview_channel_stays_disabled_in_stable_binary(self):
        bridge=Bridge()
        with patch("knowledge_bridge.bridge.PREVIEW_BUNDLE",False), \
             patch.object(bridge,"_release_repo",return_value=REPO), \
             patch("knowledge_bridge.bridge.check_preview_release",
                   side_effect=AssertionError("preview contacted")), \
             patch("knowledge_bridge.bridge.check_release",
                   return_value={"ok":True,"available":False}) as stable:
            self.assertEqual(bridge._preview_update_version(),"")
            self.assertTrue(bridge.check_updates()["ok"])
            stable.assert_called_once_with(REPO)


if __name__ == "__main__":
    unittest.main()
