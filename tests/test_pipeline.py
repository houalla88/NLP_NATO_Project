"""Bout en bout : reproductibilite, avertissements, export."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from prisme.domain.errors import InsufficientDataError
from prisme.domain.models import EntityDossier
from prisme.metrics.divergence import UncertaintyConfig
from prisme.pipeline import AnalysisConfig, analyse
from prisme.reporting import audit_manifest, render_document, to_payload, write_bundle
from prisme.scenarios import build_demo_dossier

FAST = AnalysisConfig(uncertainty=UncertaintyConfig(bootstrap=60, permutations=60))


class TestPipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dossier = build_demo_dossier()
        cls.report = analyse(cls.dossier, FAST)

    def test_all_pairs_measured(self) -> None:
        n = len(self.report.langs)
        self.assertEqual(len(self.report.divergence.pairs), n * (n - 1) // 2)

    def test_reproducible(self) -> None:
        """Meme corpus, memes parametres : memes chiffres au bit pres."""
        again = analyse(build_demo_dossier(), FAST)
        self.assertEqual(self.report.input_fingerprint, again.input_fingerprint)
        for first, second in zip(self.report.divergence.pairs, again.divergence.pairs):
            self.assertEqual(first.jsd, second.jsd)
            self.assertEqual(first.null_p_value, second.null_p_value)

    def test_synthetic_nature_propagates(self) -> None:
        """Un chiffre synthetique doit rester identifiable jusque dans le rendu."""
        self.assertEqual(self.report.data_nature, "synthetique")
        self.assertIn("CORPUS SYNTHETIQUE", audit_manifest(self.report))
        self.assertIn("Corpus synthetique", render_document(self.report))

    def test_single_edition_refused(self) -> None:
        solo = EntityDossier(
            entity_qid=self.dossier.entity_qid,
            label="x",
            snapshots=(self.dossier.snapshots[0],),
        )
        with self.assertRaises(InsufficientDataError):
            analyse(solo, FAST)

    def test_missing_edition_is_reported_not_hidden(self) -> None:
        """Une comparaison amputee en silence est une comparaison biaisee."""
        report = analyse(self.dossier, FAST, requested_langs=list(self.dossier.langs) + ["zz"])
        self.assertTrue(any("zz" in w for w in report.warnings))

    def test_embedding_covers_every_edition(self) -> None:
        self.assertEqual(set(self.report.embedding), set(self.report.langs))

    def test_scenario_structure_is_recovered(self) -> None:
        """Le scenario donne au russe le profil le plus atypique : il doit ressortir."""
        self.assertEqual(self.report.most_isolated_lang(), "ru")

    def test_significant_pairs_exceed_null_level(self) -> None:
        for pair in self.report.divergence.pairs:
            if pair.is_significant and pair.null_median is not None:
                self.assertGreater(pair.jsd, pair.null_median)


class TestReporting(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.report = analyse(build_demo_dossier(), FAST)

    def test_bundle_is_valid_json_and_sealed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = write_bundle(self.report, Path(tmp) / "r.json")
            payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(payload["schema"], "prisme-report/1")
        self.assertTrue(payload["report_fingerprint"].startswith("sha256:"))
        self.assertEqual(payload["data_nature"], "synthetique")

    def test_bundle_byte_identical_across_runs(self) -> None:
        first = json.dumps(to_payload(self.report), sort_keys=True)
        second = json.dumps(to_payload(self.report), sort_keys=True)
        self.assertEqual(first, second)

    def test_html_is_self_contained(self) -> None:
        """Aucune ressource distante : la page doit s'ouvrir hors ligne."""
        page = render_document(self.report)
        self.assertNotIn("http://", page)
        self.assertNotIn("<script", page.lower())
        for marker in ("https://cdn", "https://fonts", "src=\"http"):
            self.assertNotIn(marker, page)

    def test_html_escapes_corpus_values(self) -> None:
        page = render_document(self.report)
        self.assertNotIn("<script>alert", page)
        self.assertIn("Prisme", page)


if __name__ == "__main__":
    unittest.main()
