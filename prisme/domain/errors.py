"""Hierarchie d'erreurs du domaine.

Une seule racine : tout appelant peut attraper `PrismeError` sans connaitre
les couches internes, et les couches internes ne remontent jamais d'exception
de transport brute a l'appelant.
"""

from __future__ import annotations


class PrismeError(Exception):
    """Racine de toutes les erreurs PRISME."""


class ConfigurationError(PrismeError):
    """Parametre invalide ou incoherent fourni a une couche."""


class SourceError(PrismeError):
    """Echec d'acquisition de donnees (reseau, politique, format)."""


class SourceUnavailableError(SourceError):
    """La source est joignable mais refuse ou n'a pas la ressource."""


class CorpusError(PrismeError):
    """Corpus local absent, illisible ou structurellement invalide."""


class InsufficientDataError(PrismeError):
    """Donnees presentes mais sous le seuil ou une mesure a un sens."""
