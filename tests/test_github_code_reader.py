"""Offline integration and security tests for GitHub code at a frozen SHA."""
from __future__ import annotations
import base64
import hashlib
import unittest
from unittest.mock import patch

from knowledge_bridge.github_code import GithubCodeReader
from knowledge_bridge.github_mapping import GithubMapping, MappingError

SHA_A = "a"*40
SHA_B = "b"*40
REPO = "https://github.com/example/course"

def blob(data):
    return hashlib.sha1(b"blob "+str(len(data)).encode()+b"\x00"+data).hexdigest()

class FakeApi:
    token = ""
    def __init__(self):
        self.calls = []
        self.content = b"public class Program {}\n"
    def _get(self, repo, endpoint):
        self.calls.append(endpoint)
        if endpoint == "":
            return {"private":False}
        if endpoint == f"git/trees/{SHA_A}?recursive=1":
            return {"truncated":False,"tree":[
                {"type":"tree","path":"V3","mode":"040000"},
                {"type":"blob","path":"V2/main.cs","mode":"100644","size":5,
                 "sha":blob(b"old\n")},
                {"type":"blob","path":"V3/main.cs","mode":"100644",
                 "size":len(self.content),"sha":blob(self.content)},
                {"type":"blob","path":"V3/evil","mode":"120000",
                 "size":5,"sha":blob(b"../../")},
            ]}
        if endpoint.startswith("contents/V3/main.cs?ref="):
            return {"type":"file","encoding":"base64","sha":blob(self.content),
                    "content":base64.b64encode(self.content).decode()}
        if endpoint.startswith("contents/V2/main.cs?ref="):
            return {"type":"file","encoding":"base64","sha":blob(b"old\n"),
                    "content":base64.b64encode(b"old\n").decode()}
        if endpoint == f"compare/{SHA_B}...{SHA_A}":
            return {"files":[{"filename":"V3/main.cs","status":"modified","patch":"@@ -1 +1 @@\n-old\n+new\n"},
                             {"filename":"../escape","patch":"secret"}]}
        raise AssertionError(endpoint)

class CodeReaderTests(unittest.TestCase):
    def setUp(self):
        self.api=FakeApi()
        self.reader=GithubCodeReader(self.api)

    def test_one_recursive_tree_and_raw_first_with_verified_blob(self):
        with patch.object(self.reader,"_raw",return_value=self.api.content) as raw:
            data=self.reader.read_file(REPO,SHA_A,"V3/main.cs")
            files=self.reader.list_files(REPO,SHA_A,"V3")
            self.assertEqual(data["content"],self.api.content.decode())
            self.assertEqual([x["path"] for x in files["files"]],["V3/main.cs"])
            self.assertEqual(self.api.calls.count(f"git/trees/{SHA_A}?recursive=1"),1)
            self.assertFalse(any(c.startswith("contents/") for c in self.api.calls))
            raw.assert_called_once()

    def test_fallback_contents_api_is_exact_blob_and_sha(self):
        with patch.object(self.reader,"_raw",return_value=None):
            result=self.reader.read_file(REPO,SHA_A,"V3/main.cs")
        self.assertIn("contents/V3/main.cs?ref="+SHA_A,self.api.calls)
        self.assertEqual(result["blob_sha"],blob(self.api.content))

    def test_mismatch_falls_back_then_rejects_malicious_rest_payload(self):
        with patch.object(self.reader,"_raw",return_value=b"changed"):
            result=self.reader.read_file(REPO,SHA_A,"V3/main.cs")
            self.assertEqual(result["content"],self.api.content.decode())
        def evil(repo,endpoint):
            if endpoint.startswith("contents/"):
                return {"type":"file","encoding":"base64","sha":"0"*40,
                        "content":base64.b64encode(b"secret").decode()}
            return self.api._get(repo,endpoint)
        new=GithubCodeReader()
        new.client._get=evil
        with patch.object(new,"_raw",return_value=None), self.assertRaises(MappingError):
            new.read_file(REPO,SHA_A,"V3/main.cs")

    def test_path_traversal_binary_symlink_and_invalid_sha_rejected(self):
        for path in ("../secret","V3/../secret","/etc/passwd","V3/evil"):
            with self.subTest(path=path),self.assertRaises(MappingError):
                self.reader.read_file(REPO,SHA_A,path)
        with self.assertRaises(MappingError):
            self.reader.list_files("https://github.com/user:secret@example/evil",SHA_A)
        with self.assertRaises(MappingError):
            self.reader.list_files(REPO,"main")

    def test_compare_rest_and_local_folder_diff(self):
        compare=self.reader.compare_commits(REPO,SHA_B,SHA_A,"V3")
        self.assertEqual(compare["source"],"github_compare_rest")
        self.assertEqual(len(compare["files"]),1)
        with patch.object(self.reader,"_raw",return_value=None):
            local=self.reader.diff_folders(REPO,SHA_A,"V2","V3")
        self.assertEqual(local["source"],"local_folder_diff")
        self.assertEqual(local["files"][0]["status"],"modified")
        self.assertIn("-old",local["files"][0]["patch"])
        self.assertEqual(self.api.calls.count(f"git/trees/{SHA_A}?recursive=1"),1)

if __name__=="__main__":
    unittest.main()
