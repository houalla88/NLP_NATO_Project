"""Projection de la matrice de divergence en deux dimensions.

Positionnement multidimensionnel classique (Torgerson). L'objectif est une
carte lisible : deux editions proches sur la carte cadrent le sujet de facon
similaire.

Condition de validite
---------------------
Le MDS classique suppose des *distances*, pas des divergences. La JSD n'est pas
une metrique : elle ne verifie pas l'inegalite triangulaire. Sa racine carree,
elle, en est une (Endres & Schindelin, 2003, IEEE Trans. Inf. Theory 49(7)).
C'est donc sqrt(JSD) qui est projetee, et c'est la seule forme sous laquelle la
projection est justifiee.

La qualite d'ajustement est renvoyee avec les coordonnees. Une carte dont
l'ajustement est faible ne doit pas etre montree : elle suggere des proximites
que les donnees ne portent pas.
"""

from __future__ import annotations

import math
import random
from typing import Sequence

# Les deux axes du plan suffisent : au-dela, une carte cesse d'etre lisible et
# l'analyse doit revenir a la matrice complete.
_COMPONENTS = 2
_POWER_ITERATIONS = 500
_CONVERGENCE = 1e-10


def _power_iteration(
    matrix: list[list[float]], seed: int = 7
) -> tuple[float, list[float]]:
    """Valeur propre dominante et son vecteur, par iteration de la puissance.

    Implementation volontairement explicite plutot qu'un appel a une bibliotheque
    d'algebre lineaire : le moteur n'a aucune dependance d'execution, et un
    auditeur peut verifier la methode sans sortir du fichier. Le vecteur initial
    est tire avec une graine fixe, donc le resultat est reproductible.
    """
    n = len(matrix)
    rng = random.Random(seed)
    vector = [rng.gauss(0.0, 1.0) for _ in range(n)]
    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    vector = [v / norm for v in vector]

    eigenvalue = 0.0
    for _ in range(_POWER_ITERATIONS):
        product = [sum(matrix[i][j] * vector[j] for j in range(n)) for i in range(n)]
        norm = math.sqrt(sum(v * v for v in product))
        if norm < _CONVERGENCE:
            return 0.0, [0.0] * n
        candidate = [v / norm for v in product]
        delta = sum(abs(candidate[i] - vector[i]) for i in range(n))
        vector = candidate
        eigenvalue = sum(
            vector[i] * sum(matrix[i][j] * vector[j] for j in range(n)) for i in range(n)
        )
        if delta < _CONVERGENCE:
            break

    return eigenvalue, vector


def _deflate(
    matrix: list[list[float]], eigenvalue: float, eigenvector: Sequence[float]
) -> list[list[float]]:
    """Retire la composante dominante pour extraire la suivante."""
    n = len(matrix)
    return [
        [matrix[i][j] - eigenvalue * eigenvector[i] * eigenvector[j] for j in range(n)]
        for i in range(n)
    ]


def classical_mds(
    distances: list[list[float]], labels: Sequence[str]
) -> tuple[dict[str, tuple[float, float]], float]:
    """Coordonnees 2D et qualite d'ajustement.

    La qualite est le rapport de la somme des deux valeurs propres retenues a la
    somme des valeurs propres positives : la part de la structure de distance
    effectivement restituee par le plan.
    """
    n = len(distances)
    if n < 2:
        return {label: (0.0, 0.0) for label in labels}, 0.0

    # Double centrage : B = -1/2 * J * D^2 * J
    squared = [[d * d for d in row] for row in distances]
    row_means = [sum(row) / n for row in squared]
    grand_mean = sum(row_means) / n
    gram = [
        [
            -0.5 * (squared[i][j] - row_means[i] - row_means[j] + grand_mean)
            for j in range(n)
        ]
        for i in range(n)
    ]

    eigenvalues: list[float] = []
    eigenvectors: list[list[float]] = []
    working = gram
    for component in range(min(_COMPONENTS, n)):
        value, vector = _power_iteration(working, seed=7 + component)
        if value <= _CONVERGENCE:
            break
        eigenvalues.append(value)
        eigenvectors.append(vector)
        working = _deflate(working, value, vector)

    while len(eigenvalues) < _COMPONENTS:
        eigenvalues.append(0.0)
        eigenvectors.append([0.0] * n)

    coordinates: dict[str, tuple[float, float]] = {}
    scale = [math.sqrt(max(0.0, value)) for value in eigenvalues[:_COMPONENTS]]
    for index, label in enumerate(labels):
        coordinates[label] = (
            eigenvectors[0][index] * scale[0],
            eigenvectors[1][index] * scale[1],
        )

    # Convention de signe deterministe : sans elle, deux executions identiques
    # peuvent produire des cartes en miroir, ce qui est desastreux pour un
    # rapport compare dans le temps.
    for axis in range(_COMPONENTS):
        extreme = max(labels, key=lambda l: abs(coordinates[l][axis]))
        if coordinates[extreme][axis] < 0:
            coordinates = {
                label: tuple(
                    -value if i == axis else value
                    for i, value in enumerate(coordinates[label])
                )
                for label in coordinates
            }

    total_positive = sum(v for v in eigenvalues if v > 0)
    # La trace de la matrice de Gram borne la structure totale disponible.
    trace = sum(gram[i][i] for i in range(n))
    denominator = max(total_positive, trace, _CONVERGENCE)
    goodness = sum(v for v in eigenvalues[:_COMPONENTS] if v > 0) / denominator

    return {k: (float(v[0]), float(v[1])) for k, v in coordinates.items()}, min(
        1.0, goodness
    )


def embed_divergence(
    grid: list[list[float]], langs: Sequence[str]
) -> tuple[dict[str, tuple[float, float]], float]:
    """Projette une grille de JSD apres passage en distance metrique."""
    distances = [[math.sqrt(max(0.0, value)) for value in row] for row in grid]
    return classical_mds(distances, langs)
