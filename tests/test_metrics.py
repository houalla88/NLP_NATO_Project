"""Proprietes mathematiques des mesures.

Ces tests verifient des proprietes, pas des valeurs figees : une valeur
attendue codee en dur se contente de constater ce que fait le code, une
propriete dit ce qu'il doit faire.
"""

from __future__ import annotations

import random
import unittest
from datetime import datetime, timedelta, timezone

from prisme.domain.models import RevisionRecord
from prisme.metrics.contestedness import detect_identity_reverts, ewma, profile
from prisme.metrics.distinctive import fightin_words
from prisme.metrics.divergence import (
    UncertaintyConfig,
    _binomial,
    _multinomial,
    bootstrap_interval,
    hellinger,
    jensen_shannon,
    jensen_shannon_corrected,
    overlap,
    permutation_p_value,
)
from prisme.metrics.embedding import classical_mds

EPOCH = datetime(2020, 1, 1, tzinfo=timezone.utc)


class TestDivergenceProperties(unittest.TestCase):
    def test_identity_is_zero(self) -> None:
        p = [0.2, 0.5, 0.3]
        self.assertAlmostEqual(jensen_shannon(p, p), 0.0, places=12)

    def test_disjoint_support_is_one(self) -> None:
        self.assertAlmostEqual(jensen_shannon([1, 0], [0, 1]), 1.0, places=12)

    def test_symmetry(self) -> None:
        p, q = [0.7, 0.2, 0.1], [0.1, 0.3, 0.6]
        self.assertAlmostEqual(jensen_shannon(p, q), jensen_shannon(q, p), places=12)

    def test_bounded(self) -> None:
        rng = random.Random(3)
        for _ in range(200):
            p = [rng.random() for _ in range(8)]
            q = [rng.random() for _ in range(8)]
            p = [x / sum(p) for x in p]
            q = [x / sum(q) for x in q]
            self.assertGreaterEqual(jensen_shannon(p, q), 0.0)
            self.assertLessEqual(jensen_shannon(p, q), 1.0)

    def test_overlap_complements_intuition(self) -> None:
        self.assertAlmostEqual(overlap([0.5, 0.5], [0.5, 0.5]), 1.0)
        self.assertAlmostEqual(overlap([1.0, 0.0], [0.0, 1.0]), 0.0)

    def test_hellinger_bounds(self) -> None:
        self.assertAlmostEqual(hellinger([0.5, 0.5], [0.5, 0.5]), 0.0, places=12)
        self.assertAlmostEqual(hellinger([1, 0], [0, 1]), 1.0, places=12)


class TestBiasCorrection(unittest.TestCase):
    def test_reduces_bias_on_identical_laws(self) -> None:
        """Deux echantillons d'une meme loi : la vraie divergence est nulle.

        L'estimateur par substitution renvoie une valeur nettement positive.
        La correction doit reduire ce biais d'au moins la moitie - c'est la
        raison d'etre de son existence dans le moteur.
        """
        rng = random.Random(11)
        law = [1.0 / ((i + 1) ** 1.05) for i in range(100)]
        law = [x / sum(law) for x in law]

        plain, corrected = [], []
        for _ in range(120):
            a = _multinomial(rng, 600, law)
            b = _multinomial(rng, 600, law)
            sa, sb = sum(a), sum(b)
            plain.append(jensen_shannon([x / sa for x in a], [x / sb for x in b]))
            corrected.append(jensen_shannon_corrected(a, b))

        mean_plain = sum(plain) / len(plain)
        mean_corrected = sum(corrected) / len(corrected)
        self.assertGreater(mean_plain, 0.02, "le biais attendu doit etre visible")
        self.assertLess(mean_corrected, mean_plain / 2)

    def test_stays_in_bounds(self) -> None:
        self.assertGreaterEqual(jensen_shannon_corrected([10, 10], [10, 10]), 0.0)
        self.assertLessEqual(jensen_shannon_corrected([100, 0], [0, 100]), 1.0)


class TestSampling(unittest.TestCase):
    def test_binomial_moments(self) -> None:
        """Le biais du tireur se propage directement dans les p-valeurs."""
        rng = random.Random(5)
        for n, p in [(500, 0.01), (100, 0.005), (400, 0.25), (60, 0.5), (1000, 0.95)]:
            draws = [_binomial(rng, n, p) for _ in range(8000)]
            mean = sum(draws) / len(draws)
            variance = sum(d * d for d in draws) / len(draws) - mean**2
            with self.subTest(n=n, p=p):
                self.assertAlmostEqual(mean, n * p, delta=max(0.12, 0.05 * n * p))
                self.assertAlmostEqual(
                    variance, n * p * (1 - p), delta=max(0.12, 0.15 * n * p * (1 - p))
                )

    def test_multinomial_conserves_total(self) -> None:
        rng = random.Random(9)
        law = [0.1, 0.2, 0.3, 0.4]
        for _ in range(200):
            self.assertEqual(sum(_multinomial(rng, 250, law)), 250)


class TestInference(unittest.TestCase):
    def test_interval_contains_point_estimate(self) -> None:
        rng = random.Random(2)
        law_a = [0.4, 0.3, 0.2, 0.1]
        law_b = [0.1, 0.2, 0.3, 0.4]
        a = _multinomial(rng, 400, law_a)
        b = _multinomial(rng, 400, law_b)
        config = UncertaintyConfig(bootstrap=150, permutations=0)
        interval = bootstrap_interval(a, b, config)
        point = jensen_shannon_corrected(a, b)
        self.assertIsNotNone(interval)
        assert interval is not None
        self.assertLessEqual(interval.lower, point)
        self.assertGreaterEqual(interval.upper, point)

    def test_permutation_detects_real_difference(self) -> None:
        rng = random.Random(4)
        a = _multinomial(rng, 600, [0.7, 0.2, 0.05, 0.05])
        b = _multinomial(rng, 600, [0.05, 0.05, 0.2, 0.7])
        observed = jensen_shannon_corrected(a, b)
        p_value, _ = permutation_p_value(
            a, b, observed, UncertaintyConfig(permutations=200)
        )
        self.assertIsNotNone(p_value)
        assert p_value is not None
        self.assertLess(p_value, 0.05)

    def test_permutation_p_value_never_zero(self) -> None:
        """Correction de Davison & Hinkley : un nombre fini de tirages ne prouve pas 0."""
        rng = random.Random(6)
        a = _multinomial(rng, 300, [0.9, 0.05, 0.05])
        b = _multinomial(rng, 300, [0.05, 0.05, 0.9])
        p_value, _ = permutation_p_value(
            a, b, 1.0, UncertaintyConfig(permutations=50)
        )
        assert p_value is not None
        self.assertGreater(p_value, 0.0)


class TestDistinctive(unittest.TestCase):
    def test_prior_suppresses_rare_noise(self) -> None:
        """Un concept vu une fois ne doit pas dominer un concept massivement decale."""
        counts_in = {"Q1": 1.0, "Q2": 200.0}
        counts_out = {"Q2": 20.0, "Q3": 300.0}
        background = {"Q1": 1.0, "Q2": 220.0, "Q3": 300.0}
        scored = fightin_words(counts_in, counts_out, background, "aa", z_threshold=0.0)
        ranking = [item.qid for item in scored]
        self.assertIn("Q2", ranking)
        self.assertLess(ranking.index("Q2"), ranking.index("Q1"))

    def test_empty_inputs_are_safe(self) -> None:
        self.assertEqual(fightin_words({}, {}, {}, "aa"), [])


class TestContestedness(unittest.TestCase):
    def _series(self, digests: list[str]) -> list[RevisionRecord]:
        return [
            RevisionRecord(
                rev_id=i,
                timestamp=EPOCH + timedelta(days=i),
                sha1=d,
                size=10,
                editor=f"e{i % 3}",
            )
            for i, d in enumerate(digests)
        ]

    def test_detects_restoration(self) -> None:
        reverts = detect_identity_reverts(self._series(["a", "b", "c", "a"]))
        self.assertEqual(len(reverts), 1)
        self.assertEqual(reverts[0][1], [1, 2])

    def test_adjacent_duplicate_is_not_a_revert(self) -> None:
        """Une revision identique a son parent ne defait rien."""
        self.assertEqual(detect_identity_reverts(self._series(["a", "a"])), [])

    def test_missing_sha1_is_ignored(self) -> None:
        self.assertEqual(detect_identity_reverts(self._series(["", "", ""])), [])

    def test_empty_history_yields_zero_profile(self) -> None:
        result = profile("ru", [])
        self.assertEqual(result.n_revisions, 0)
        self.assertEqual(result.revert_rate, 0.0)

    def test_ewma_between_extremes(self) -> None:
        series = [1.0, 5.0, 2.0, 9.0]
        self.assertGreaterEqual(ewma(series), min(series))
        self.assertLessEqual(ewma(series), max(series))


class TestEmbedding(unittest.TestCase):
    def test_recovers_collinear_structure(self) -> None:
        """Trois points alignes a 1 et 2 unites doivent le rester en projection."""
        distances = [[0, 1, 2], [1, 0, 1], [2, 1, 0]]
        coords, fit = classical_mds(distances, ["a", "b", "c"])
        self.assertGreater(fit, 0.95)
        span = abs(coords["a"][0] - coords["c"][0])
        self.assertAlmostEqual(span, 2.0, delta=0.15)

    def test_deterministic(self) -> None:
        distances = [[0, 0.3, 0.9], [0.3, 0, 0.5], [0.9, 0.5, 0]]
        first, _ = classical_mds(distances, ["x", "y", "z"])
        second, _ = classical_mds(distances, ["x", "y", "z"])
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
