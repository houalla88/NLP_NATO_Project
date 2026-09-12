"""Couche d'acquisition : analyse du wikitexte, resolution, securite des chemins."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from prisme.config import assert_allowed_host
from prisme.domain.errors import ConfigurationError, CorpusError
from prisme.scenarios import build_demo_dossier
from prisme.sources.local import (
    LocalCorpusSource,
    dump_dossier,
    load_dossier,
    resolve_corpus_path,
)
from prisme.sources.mediawiki import MediaWikiSource, classify_section, parse_links


class TestWikitext(unittest.TestCase):
    WIKITEXT = """Le [[Traite de l'Atlantique Nord]] fonde l'[[Alliance]].
L'[[Alliance]] compte des membres.

== Histoire ==
Voir la [[Guerre froide]] et le [[Pacte de Varsovie]].
[[Fichier:carte.png|vignette|Une [[carte]]]]
[[Categorie:Organisation]]
[[en:NATO]] [[de:NATO]]

== Critiques ==
Des [[Controverses]] subsistent.

== Voir aussi ==
[[Union europeenne]]

== Notes et references ==
[[Ouvrage de reference]]
"""

    def test_sections_and_counts(self) -> None:
        links = parse_links(self.WIKITEXT, {"fichier", "categorie"})
        by_target: dict[str, list[str]] = {}
        for target, section in links:
            by_target.setdefault(target, []).append(section)

        self.assertEqual(by_target["Alliance"], ["lead", "lead"])
        self.assertEqual(by_target["Guerre froide"], ["body"])
        self.assertEqual(by_target["Controverses"], ["criticism"])
        self.assertEqual(by_target["Union europeenne"], ["seealso"])
        self.assertEqual(by_target["Ouvrage de reference"], ["references"])

    def test_technical_namespaces_excluded(self) -> None:
        """Une categorie apparait dans toutes les pages d'un domaine : elle noierait le signal."""
        targets = {t for t, _ in parse_links(self.WIKITEXT, {"fichier", "categorie"})}
        self.assertNotIn("Organisation", targets)
        self.assertNotIn("Carte.png", targets)

    def test_interlanguage_links_excluded(self) -> None:
        targets = {t for t, _ in parse_links(self.WIKITEXT, {"fichier", "categorie"})}
        self.assertFalse(any(t.lower().startswith(("en:", "de:")) for t in targets))

    def test_anchor_stripped_and_normalised(self) -> None:
        links = parse_links("[[guerre_froide#Origines]] [[  autre  ]]", set())
        self.assertEqual([t for t, _ in links], ["Guerre froide", "Autre"])

    def test_section_classification_ignores_diacritics(self) -> None:
        for heading in ("Notes et références", "NOTES ET RÉFÉRENCES", "Примечания", "Kaynakça"):
            with self.subTest(heading=heading):
                self.assertEqual(classify_section(heading), "references")
        self.assertEqual(classify_section("Chronologie detaillee"), "body")


class _StubHttp:
    """Client HTTP simule : rejoue des reponses MediaWiki enregistrees."""

    def __init__(self, payloads: list[dict]) -> None:
        self._payloads = payloads
        self.calls: list[tuple[str, dict]] = []

    def get_json(self, host: str, params: dict) -> dict:
        self.calls.append((host, params))
        return self._payloads.pop(0)


class TestQidResolution(unittest.TestCase):
    def test_follows_normalisation_and_redirects(self) -> None:
        """Sans suivi des redirections, tous les liens passant par un alias sont perdus."""
        source = MediaWikiSource.__new__(MediaWikiSource)
        source._TITLE_BATCH = 50
        source._http = _StubHttp(
            [
                {
                    "query": {
                        "normalized": [{"from": "otan", "to": "Otan"}],
                        "redirects": [{"from": "Otan", "to": "Organisation du traite"}],
                        "pages": [
                            {"title": "Organisation du traite", "pageprops": {"wikibase_item": "Q7184"}},
                            {"title": "Guerre froide", "pageprops": {"wikibase_item": "Q8683"}},
                            {"title": "Sans entite"},
                        ],
                    }
                }
            ]
        )
        resolved = MediaWikiSource._resolve_qids(
            source, "fr", ["otan", "Guerre froide", "Sans entite"]
        )
        self.assertEqual(resolved["otan"], "Q7184")
        self.assertEqual(resolved["Guerre froide"], "Q8683")
        self.assertNotIn("Sans entite", resolved)

    def test_sitelinks_ignore_non_language_wikis(self) -> None:
        source = MediaWikiSource.__new__(MediaWikiSource)
        source._http = _StubHttp(
            [
                {
                    "entities": {
                        "Q7184": {
                            "sitelinks": {
                                "frwiki": {"title": "OTAN"},
                                "ruwiki": {"title": "НАТО"},
                                "commonswiki": {"title": "Category:NATO"},
                                "frwikiquote": {"title": "OTAN"},
                            }
                        }
                    }
                }
            ]
        )
        links = MediaWikiSource.sitelinks(source, "Q7184")
        self.assertEqual(set(links), {"fr", "ru"})


class TestEgressPerimeter(unittest.TestCase):
    def test_wikimedia_hosts_allowed(self) -> None:
        for host in ("ru.wikipedia.org", "www.wikidata.org", "wikidata.org"):
            assert_allowed_host(host)

    def test_foreign_hosts_refused(self) -> None:
        """Seconde barriere : elle tient meme si une redirection sort du perimetre."""
        for host in ("evil.example.com", "wikipedia.org.attacker.net", "169.254.169.254", ""):
            with self.subTest(host=host), self.assertRaises(ConfigurationError):
                assert_allowed_host(host)


class TestCorpusFiles(unittest.TestCase):
    def test_round_trip_preserves_measurements(self) -> None:
        original = build_demo_dossier(seed=3)
        with tempfile.TemporaryDirectory() as tmp:
            path = dump_dossier(original, "synthetic-demo", Path(tmp) / "c.json")
            reloaded = load_dossier(path)
        self.assertEqual(original.audit_fingerprint(), reloaded.audit_fingerprint())

    def test_nature_is_mandatory(self) -> None:
        """Un corpus sans nature declaree ne doit pas pouvoir produire de rapport."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text(
                json.dumps({"schema": "prisme-corpus/1", "editions": [], "entity": {}}),
                encoding="utf-8",
            )
            with self.assertRaises(CorpusError):
                load_dossier(path)

    def test_schema_is_checked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text(json.dumps({"schema": "autre/9"}), encoding="utf-8")
            with self.assertRaises(CorpusError):
                load_dossier(path)

    def test_path_traversal_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "ok.json").write_text("{}", encoding="utf-8")
            self.assertTrue(resolve_corpus_path("ok", tmp).is_file())
            for name in ("../secret", "..", "/etc/passwd", "a/b", ".hidden", ""):
                with self.subTest(name=name), self.assertRaises(CorpusError):
                    resolve_corpus_path(name, tmp)

    def test_lang_subset_selection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = dump_dossier(build_demo_dossier(), "synthetic-demo", Path(tmp) / "c.json")
            subset = LocalCorpusSource(path).fetch("", ["ru", "en"])
            self.assertEqual(set(subset.langs), {"ru", "en"})


if __name__ == "__main__":
    unittest.main()
