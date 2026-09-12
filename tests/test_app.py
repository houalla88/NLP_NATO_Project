"""Interface web : routes, durcissement, refus des entrees hostiles.

L'application etant optionnelle, ces tests s'effacent si Flask est absent -
le moteur de mesure, lui, n'a aucune dependance.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

try:
    from app import create_app

    FLASK_AVAILABLE = True
except ImportError:  # pragma: no cover
    FLASK_AVAILABLE = False

from prisme.scenarios import build_demo_dossier
from prisme.sources.local import dump_dossier


@unittest.skipUnless(FLASK_AVAILABLE, "Flask absent - interface optionnelle")
class TestWebInterface(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        dump_dossier(
            build_demo_dossier(), "synthetic-demo", Path(cls._tmp.name) / "demo.json"
        )
        cls.client = create_app(cls._tmp.name).test_client()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_index_lists_corpus(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"demo", response.data)

    def test_report_renders(self) -> None:
        response = self.client.get("/rapport/demo")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Refraction narrative".encode(), response.data)

    def test_synthetic_banner_is_not_optional(self) -> None:
        """Aucune configuration ne doit pouvoir retirer l'avertissement."""
        response = self.client.get("/rapport/demo")
        self.assertIn("Corpus synthetique".encode(), response.data)

    def test_json_endpoint(self) -> None:
        payload = self.client.get("/api/rapport/demo").get_json()
        self.assertEqual(payload["schema"], "prisme-report/1")
        self.assertIn("report_fingerprint", payload)

    def test_security_headers_on_every_response(self) -> None:
        for url in ("/", "/rapport/demo", "/sante", "/rapport/absent"):
            with self.subTest(url=url):
                headers = self.client.get(url).headers
                self.assertIn("Content-Security-Policy", headers)
                self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff")
                self.assertEqual(headers.get("X-Frame-Options"), "DENY")

    def test_csp_forbids_scripts(self) -> None:
        policy = self.client.get("/rapport/demo").headers["Content-Security-Policy"]
        self.assertIn("default-src 'none'", policy)
        self.assertNotIn("script-src", policy)

    def test_hostile_corpus_names_refused(self) -> None:
        for name in ("..%2F..%2Fetc%2Fpasswd", "..", ".env", "a%2Fb", "absent"):
            with self.subTest(name=name):
                self.assertEqual(self.client.get(f"/rapport/{name}").status_code, 404)

    def test_no_outbound_routes(self) -> None:
        """Aucune route ne doit pouvoir declencher une collecte reseau."""
        rules = {r.rule for r in create_app(self._tmp.name).url_map.iter_rules()}
        self.assertNotIn("/collect", rules)
        for rule in rules:
            self.assertNotIn("collect", rule)


if __name__ == "__main__":
    unittest.main()
