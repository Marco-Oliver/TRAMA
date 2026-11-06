"""GitHub REST URL contracts and opt-in anonymous live version-discovery smoke.

Unit tests use exact Request.full_url assertions and no external connection.
The live test is opt-in on GitHub Actions, without a token or personal vault.
"""
from __future__ import annotations

import io
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from knowledge_bridge.github_mapping import GithubMapping, GithubRateLimitError
from knowledge_bridge.github_code import GithubCodeReader
from knowledge_bridge.github_auto_versions import GithubAutoMapper
from knowledge_bridge.store import Store


REPO = "https://github.com/academiadoprogramador-fullstack/delivery-app-2026"
BASE = "https://api.github.com/repos/academiadoprogramador-fullstack/delivery-app-2026"
SHA = "a" * 40
OTHER = "b" * 40


class FakeResponse(io.BytesIO):
    def __init__(self, payload):
        content = json.dumps(payload).encode("utf-8")
        super().__init__(content)
        self.headers = {"Content-Length": str(len(content))}


class GithubExactRestUrlTests(unittest.TestCase):
    def test_all_endpoint_urls_are_exact_and_metadata_has_no_trailing_slash(self):
        client = GithubMapping(token="")
        actual = []

        def open_request(req, timeout=0):
            actual.append(req.full_url)
            self.assertEqual(timeout, 20)
            self.assertIsNone(req.get_header("Authorization"))
            return FakeResponse({"private": False})

        endpoints = [
            ("", BASE),
            ("branches?per_page=100&page=1",
             BASE + "/branches?per_page=100&page=1"),
            ("tags?per_page=100&page=1",
             BASE + "/tags?per_page=100&page=1"),
            ("commits?per_page=1&sha=v8",
             BASE + "/commits?per_page=1&sha=v8"),
            (f"compare/{SHA}...{OTHER}",
             BASE + f"/compare/{SHA}...{OTHER}"),
            (f"git/trees/{SHA}?recursive=1",
             BASE + f"/git/trees/{SHA}?recursive=1"),
            (f"contents/src/DeliveryService.cs?ref={SHA}",
             BASE + f"/contents/src/DeliveryService.cs?ref={SHA}"),
        ]
        with patch.object(client._opener, "open", side_effect=open_request):
            for endpoint, expected_url in endpoints:
                self.assertEqual(client._get(REPO, endpoint), {"private": False})
                self.assertEqual(actual[-1], expected_url)
            # is_private is an independent metadata consumer and must use
            # exactly the same slash-free URL, even without a token.
            reader = GithubCodeReader(client=client)
            self.assertFalse(reader.is_private(REPO))
        self.assertEqual(actual, [url for _, url in endpoints] + [BASE])
        self.assertNotIn(BASE + "/", (actual[0], actual[-1]))


@unittest.skipUnless(
    os.environ.get("TRAMA_GITHUB_REAL_SMOKE") == "1",
    "SMOKE_REAL RESULT=NOT_RUN (opt in using TRAMA_GITHUB_REAL_SMOKE=1)"
)
class GithubLiveRestSmoke(unittest.TestCase):
    def test_anonymous_public_delivery_app_v0_to_v8(self):
        # Explicit token="" prevents env/DPAPI fallbacks. No user vault,
        # checkout, AI provider, stored secrets, or write to the GitHub repo.
        with tempfile.TemporaryDirectory(prefix="trama-github-live-") as root:
            store = Store(Path(root) / "vault")
            try:
                client = GithubMapping(token="")
                self.assertEqual(client.token, "")
                mapper = GithubAutoMapper(store, client=client)
                try:
                    versions = mapper.discover(REPO)
                except GithubRateLimitError as exc:
                    message = f"SMOKE_REAL RESULT=SKIP RATE_LIMIT {exc}"
                    print(message, flush=True)
                    self.skipTest(message)
                status = next(
                    (r for r in store.auto_repositories() if r["repo_url"] == REPO),
                    None,
                )
                if versions is None and status and status["status"] == "paused":
                    message = (
                        "SMOKE_REAL RESULT=SKIP RATE_LIMIT "
                        + str(status["message"])[:250]
                    )
                    print(message, flush=True)
                    self.skipTest(message)
                if versions is None:
                    reason = status["message"] if status else "sem cadastro"
                    self.fail("SMOKE_REAL RESULT=FAIL repo metadata/versions: " + str(reason))

                expected = [f"v{i}" for i in range(9)]
                discovered = [v["name"] for v in versions]
                self.assertTrue(
                    all(name in discovered for name in expected),
                    "SMOKE_REAL RESULT=FAIL faltam versões entre v0 e v8: "
                    + ", ".join(discovered),
                )
                indices = [discovered.index(v) for v in expected]
                self.assertEqual(indices, sorted(indices))
                self.assertEqual(len(indices), len(set(indices)))
                for name in expected:
                    selected = next(v for v in versions if v["name"] == name)
                    self.assertRegex(selected["sha"], r"^[0-9a-f]{40}$")
                    self.assertEqual(selected["number"], int(name[1:]))
                self.assertEqual(status["status"], "ready")
                self.assertEqual(status["role"], "professor")
                self.assertEqual(status["private"], 0)
                print(
                    "SMOKE_REAL RESULT=PASS "
                    + "repo=" + REPO
                    + " anonymous=true"
                    + " versions=" + ",".join(expected)
                    + " discovered=" + ",".join(discovered)
                    + " REST_calls=" + str(client.rate["consultas"]),
                    flush=True,
                )
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
