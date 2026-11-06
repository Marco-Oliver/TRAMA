"""LRU capacity, file-system safety, and Windows DPAPI privacy boundaries."""
from __future__ import annotations
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from knowledge_bridge.github_cache import GithubCache, MAX_CACHE
from knowledge_bridge.github_code import GithubCodeReader
from knowledge_bridge.github_mapping import MappingError
from test_github_code_reader import FakeApi, REPO, SHA_A

class GithubCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/"app"/"github-cache"
        self.vault=Path(self.tmp.name)/"vault"
        self.vault.mkdir()

    def test_limit_300mb_never_exceeded_and_lru_eviction(self):
        cache=GithubCache(self.root,self.vault,max_bytes=25)
        self.assertLessEqual(cache.max_bytes,MAX_CACHE)
        self.assertTrue(cache.put(("one",),b"1"*14))
        self.assertTrue(cache.put(("two",),b"2"*14))
        self.assertIsNone(cache.get(("one",)))
        self.assertEqual(cache.get(("two",)),b"2"*14)
        self.assertLessEqual(sum(p.stat().st_size for p in self.root.glob("*.entry")),25)

    def test_private_requires_dpapi_and_never_falls_back_to_plaintext(self):
        cache=GithubCache(self.root,self.vault)
        with patch("knowledge_bridge.github_cache.sys.platform","linux"):
            self.assertFalse(cache.put(("private",REPO),b"private-secret",private=True))
        self.assertEqual(list(self.root.glob("*.entry")),[])
        def crypt(data, encrypt):
            return b"dpapi:" + data[::-1] if encrypt else data[6:][::-1]
        with patch("knowledge_bridge.github_cache.sys.platform","win32"):
            with patch("knowledge_bridge.github_cache._crypt",side_effect=crypt):
                self.assertTrue(cache.put(("private",REPO),b"private-secret",private=True))
                self.assertEqual(cache.get(("private",REPO),private=True),b"private-secret")
                self.assertIsNone(cache.get(("private",REPO),private=False))
        for entry in self.root.glob("*.entry"):
            self.assertNotIn(b"private-secret",entry.read_bytes())
            self.assertTrue(entry.read_bytes().startswith(b"E"))

    def test_vault_and_symlink_are_denied(self):
        with self.assertRaises(ValueError):
            GithubCache(self.vault/"cache",vault=self.vault)
        target=Path(self.tmp.name)/"target"
        target.mkdir()
        symlink=self.root
        symlink.parent.mkdir(parents=True)
        try:
            symlink.symlink_to(target,target_is_directory=True)
        except (OSError,NotImplementedError):
            self.skipTest("Symlinks unavailable")
        with self.assertRaises(ValueError):
            GithubCache(symlink,vault=self.vault)

    def test_nonbytes_large_and_malformed_cache_rejected(self):
        cache=GithubCache(self.root,self.vault)
        self.assertFalse(cache.put(("large",),b"x"*300001))
        self.assertFalse(cache.put(("wrong",),"a string"))
        self.root.mkdir(parents=True)
        path=cache._entry(("bad",),private=True)
        path.write_bytes(b"Pshould-not-be-decrypted")
        self.assertIsNone(cache.get(("bad",),private=True))

    def test_reader_uses_verified_cached_bytes_across_sessions(self):
        cache=GithubCache(self.root,self.vault)
        first=GithubCodeReader(FakeApi(),cache)
        with patch.object(first,"_raw",return_value=first.client.content):
            self.assertEqual(first.read_file(REPO,SHA_A,"V3/main.cs")["content"],
                             first.client.content.decode())
        again=GithubCodeReader(FakeApi(),cache)
        with patch.object(again,"_raw",side_effect=AssertionError("must use cache")):
            result=again.read_file(REPO,SHA_A,"V3/main.cs")
        self.assertEqual(result["sha"],SHA_A)

if __name__=="__main__":
    unittest.main()
