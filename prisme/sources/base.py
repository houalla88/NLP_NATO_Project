"""Contrat d'acquisition.

Une seule interface separe le moteur de mesure de la provenance des donnees.
Consequence directe : le pipeline est identique qu'il tourne sur l'API en
direct, sur un corpus fige, ou sur un jeu de validation synthetique. C'est ce
qui rend les resultats rejouables des annees apres, quand l'article a change.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, Sequence, runtime_checkable

from ..domain.models import ArticleSnapshot, EntityDossier


@runtime_checkable
class DossierSource(Protocol):
    """Fournit les instantanes d'une entite dans plusieurs langues."""

    source_id: str

    def fetch(self, entity_qid: str, langs: Sequence[str]) -> EntityDossier:
        """Instantanes courants de l'entite dans chacune des langues demandees."""
        ...


@runtime_checkable
class HistorySource(Protocol):
    """Fournit les etats passes d'un article - support de l'analyse de derive."""

    def fetch_at(
        self, entity_qid: str, lang: str, moments: Sequence[datetime]
    ) -> list[ArticleSnapshot]:
        """Instantanes de l'article aux dates demandees, au plus proche avant."""
        ...
