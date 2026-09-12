"""Le banc d'etalonnage est lui-meme un test de non-regression.

Si une modification des formules degrade la justesse, la calibration du test
nul ou la detection des reverts, ce test echoue avant que les chiffres n'aient
la moindre chance d'atteindre un rapport.
"""

from __future__ import annotations

import unittest

from prisme.calibration import (
    build_synthetic_corpus,
    check_null_calibration,
    run_calibration,
    EditionSpec,
)


class TestCalibrationBench(unittest.TestCase):
    def test_bench_is_conform(self) -> None:
        result = run_calibration(fast=True)
        failures = [c.name for c in result.checks if not c.passed]
        self.assertEqual(failures, [], f"controles en echec : {failures}")

    def test_bench_covers_every_family_of_defect(self) -> None:
        names = {c.name for c in run_calibration(fast=True).checks}
        self.assertGreaterEqual(len(names), 6)

    def test_null_test_is_not_anticonservative(self) -> None:
        """Le defaut le plus grave : declarer significatif un ecart inexistant."""
        check = check_null_calibration(trials=60, tolerance=2.5, seed=31)
        self.assertTrue(check.passed, f"taux de faux positifs mesure : {check.observed}")

    def test_synthetic_qids_are_outside_wikidata(self) -> None:
        """Garde-fou : un chiffre synthetique ne doit jamais passer pour une observation."""
        corpus = build_synthetic_corpus(
            specs=[EditionSpec("aa", [1] * 6), EditionSpec("bb", [2, 1, 1, 1, 1, 1])],
            seed=1,
            revisions_per_edition=0,
            planted_reverts=0,
        )
        for qid in corpus.concept_space:
            self.assertGreaterEqual(int(qid[1:]), 900_000_000)


if __name__ == "__main__":
    unittest.main()
