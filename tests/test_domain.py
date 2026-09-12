"""Invariants du domaine : ce qui ne doit jamais pouvoir etre construit."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from prisme.domain import (
    ConceptObservation,
    ConfigurationError,
    EntityDossier,
    Provenance,
    RevisionRecord,
    canonical_hash,
    validate_lang,
    validate_qid,
)
from prisme.scenarios import build_demo_dossier


class TestValidation(unittest.TestCase):
    def test_lang_codes(self) -> None:
        self.assertEqual(validate_lang("RU"), "ru")
        self.assertEqual(validate_lang(" zh-yue "), "zh-yue")
        for bad in ("", "r", "russian-long-code", "../etc", "ru/../..", "r u"):
            with self.subTest(bad=bad), self.assertRaises(ConfigurationError):
                validate_lang(bad)

    def test_qids(self) -> None:
        self.assertEqual(validate_qid(" q7184 "), "Q7184")
        for bad in ("Q0", "Q", "7184", "P31", "Q01", "Q7184; DROP"):
            with self.subTest(bad=bad), self.assertRaises(ConfigurationError):
                validate_qid(bad)

    def test_negative_counts_rejected(self) -> None:
        with self.assertRaises(ConfigurationError):
            ConceptObservation(qid="Q42", count=-1)

    def test_naive_timestamp_rejected(self) -> None:
        """Un horodatage sans fuseau rend toute serie temporelle ambigue."""
        with self.assertRaises(ConfigurationError):
            RevisionRecord(rev_id=1, timestamp=datetime(2024, 1, 1), sha1="a", size=1)
        with self.assertRaises(ConfigurationError):
            Provenance(source_id="x", retrieved_at=datetime(2024, 1, 1))


class TestDossier(unittest.TestCase):
    def test_duplicate_langs_rejected(self) -> None:
        dossier = build_demo_dossier()
        with self.assertRaises(ConfigurationError):
            EntityDossier(
                entity_qid=dossier.entity_qid,
                label="x",
                snapshots=(dossier.snapshots[0], dossier.snapshots[0]),
            )

    def test_snapshot_entity_must_match(self) -> None:
        """Comparer deux articles decrivant des referents differents n'a pas de sens."""
        dossier = build_demo_dossier()
        foreign = dossier.snapshots[0]
        with self.assertRaises(ConfigurationError):
            EntityDossier(entity_qid="Q1", label="x", snapshots=(foreign,))

    def test_immutability(self) -> None:
        dossier = build_demo_dossier()
        with self.assertRaises(Exception):
            dossier.snapshots[0].concepts = ()  # type: ignore[misc]


class TestFingerprint(unittest.TestCase):
    def test_order_independent(self) -> None:
        self.assertEqual(
            canonical_hash({"a": 1, "b": [2, 3]}), canonical_hash({"b": [2, 3], "a": 1})
        )

    def test_detects_change(self) -> None:
        self.assertNotEqual(canonical_hash({"a": 1}), canonical_hash({"a": 2}))

    def test_dossier_fingerprint_stable(self) -> None:
        """Meme graine, meme empreinte : condition de la rejouabilite."""
        self.assertEqual(
            build_demo_dossier(seed=7).audit_fingerprint(),
            build_demo_dossier(seed=7).audit_fingerprint(),
        )
        self.assertNotEqual(
            build_demo_dossier(seed=7).audit_fingerprint(),
            build_demo_dossier(seed=8).audit_fingerprint(),
        )


if __name__ == "__main__":
    unittest.main()
