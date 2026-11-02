"""Regression for hostile API URLs/redirects and crafted DOCX XML."""
from __future__ import annotations

import tempfile
import unittest
import urllib.error
import zipfile
from pathlib import Path
from unittest.mock import patch

from knowledge_bridge.ai import _send, _NoRedirect, ProviderError
from knowledge_bridge.auto_ingest import _plain_document


class SafeNetworkTests(unittest.TestCase):
    def test_unapproved_hosts_and_schemes_never_call_http(self):
        bad = (
            "file:///etc/passwd",
            "http://api.groq.com/openai/v1/chat/completions",
            "https://api.groq.com.evil.test/",
            "https://api.groq.com:444/",
            "https://user:token@api.groq.com/",
            "https://api.groq.com/path#fragment",
        )
        with patch("knowledge_bridge.ai.urllib.request.build_opener") as build:
            for url in bad:
                with self.subTest(url=url), self.assertRaises(ProviderError):
                    _send(url, {"messages": []}, {"Authorization": "Bearer SECRET"}, "groq")
        build.assert_not_called()

    def test_provider_redirect_is_not_followed(self):
        handler = _NoRedirect()
        self.assertIsNone(handler.redirect_request(
            None, None, 307, "redirect", {}, "https://attacker.test/steal"))
        with patch("knowledge_bridge.ai.urllib.request.build_opener") as build:
            opener = build.return_value
            opener.open.side_effect = urllib.error.HTTPError(
                "https://api.groq.com/path", 307, "redirect", {}, None)
            with self.assertRaises(ProviderError) as result:
                _send("https://api.groq.com/openai/v1/chat/completions",
                      {"messages": []}, {"Authorization": "Bearer SECRET"}, "groq")
        self.assertIn("HTTP 307", str(result.exception))
        self.assertNotIn("SECRET", str(result.exception))

    def test_provider_response_is_size_limited(self):
        class BigReply:
            def __enter__(self):return self
            def __exit__(self,*args):return False
            def read(self,count):return b"x" * (count + 1)
        with patch("knowledge_bridge.ai.urllib.request.build_opener") as build:
            build.return_value.open.return_value = BigReply()
            with self.assertRaisesRegex(ProviderError, "excede 2 MB"):
                _send("https://api.groq.com/openai/v1/chat/completions",
                      {"messages": []}, {}, "groq")


class DefusedDocumentTests(unittest.TestCase):
    def test_xml_entity_in_docx_is_rejected(self):
        malicious = """<?xml version="1.0"?>
<!DOCTYPE w:document [<!ENTITY leak "PRIVATE-DATA">]>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:body><w:p><w:r><w:t>&leak;</w:t></w:r></w:p></w:body></w:document>"""
        with tempfile.TemporaryDirectory() as home:
            path=Path(home)/"crafted.docx"
            with zipfile.ZipFile(path,"w") as z:
                z.writestr("word/document.xml", malicious)
            self.assertEqual(_plain_document(path), "")

    def test_normal_docx_text_still_loads(self):
        good = """<?xml version="1.0"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:body><w:p><w:r><w:t>Olá, mundo em C#</w:t></w:r></w:p></w:body></w:document>"""
        with tempfile.TemporaryDirectory() as home:
            path=Path(home)/"safe.docx"
            with zipfile.ZipFile(path,"w") as z:
                z.writestr("word/document.xml", good)
            self.assertEqual(_plain_document(path), "Olá, mundo em C#")


if __name__ == "__main__":
    unittest.main()
