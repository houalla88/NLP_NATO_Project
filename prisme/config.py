"""Configuration d'execution.

Aucun secret n'est requis par PRISME : les API MediaWiki et Wikidata sont
publiques et anonymes. Ce module existe pour que les parametres operationnels
(identification, debit, delais, plafonds) soient declares en un seul endroit,
surchargeables par variable d'environnement, et traces dans le rapport.

Regle : aucune valeur sensible ne doit jamais etre ajoutee ici sans passer par
l'environnement. Les valeurs presentes sont toutes publiques par nature.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from .domain.errors import ConfigurationError

# Wikimedia exige un User-Agent identifiant l'outil et un moyen de contact
# (https://foundation.wikimedia.org/wiki/Policy:User-Agent_policy). Un agent
# generique expose a un blocage cote serveur : ce n'est pas une politesse,
# c'est une condition d'acces.
DEFAULT_USER_AGENT = (
    "PRISME/0.1 (https://dataoptimization.be; outil de recherche en cadrage "
    "narratif; contact via le depot) Python-urllib"
)

_ALLOWED_HOST_SUFFIXES = (".wikipedia.org", ".wikidata.org", "wikidata.org")


@dataclass(frozen=True, slots=True)
class HttpSettings:
    """Parametres de transport. Toutes les valeurs sont des garde-fous."""

    user_agent: str = DEFAULT_USER_AGENT
    timeout_seconds: float = 20.0
    max_retries: int = 4
    backoff_base_seconds: float = 1.5
    # Plafond de lecture par reponse. Protege contre une reponse anormalement
    # volumineuse qui saturerait la memoire du processus.
    max_response_bytes: int = 16 * 1024 * 1024
    # Debit maximal soutenu. Wikimedia ne publie pas de quota anonyme ferme ;
    # 5 requetes/seconde est un usage raisonnable et defendable pour un outil
    # de recherche. Reduire avant d'augmenter.
    max_requests_per_second: float = 5.0

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise ConfigurationError("timeout_seconds doit etre strictement positif")
        if self.max_requests_per_second <= 0:
            raise ConfigurationError("max_requests_per_second doit etre positif")
        if "http" in self.user_agent.lower() and "://" not in self.user_agent:
            raise ConfigurationError("user_agent mal forme")


@dataclass(frozen=True, slots=True)
class Settings:
    """Configuration complete, resolue depuis l'environnement."""

    http: HttpSettings = field(default_factory=HttpSettings)
    cache_dir: str = ".prisme-cache"
    offline: bool = False

    @classmethod
    def from_env(cls) -> "Settings":
        """Construit la configuration depuis les variables PRISME_*.

        Variables reconnues :
          PRISME_USER_AGENT, PRISME_TIMEOUT, PRISME_MAX_RETRIES,
          PRISME_RPS, PRISME_CACHE_DIR, PRISME_OFFLINE
        """

        def _float(name: str, fallback: float) -> float:
            raw = os.environ.get(name)
            if raw is None or not raw.strip():
                return fallback
            try:
                return float(raw)
            except ValueError as exc:
                raise ConfigurationError(f"{name}: nombre attendu, recu {raw!r}") from exc

        def _int(name: str, fallback: int) -> int:
            return int(_float(name, float(fallback)))

        http = HttpSettings(
            user_agent=os.environ.get("PRISME_USER_AGENT", DEFAULT_USER_AGENT),
            timeout_seconds=_float("PRISME_TIMEOUT", 20.0),
            max_retries=_int("PRISME_MAX_RETRIES", 4),
            max_requests_per_second=_float("PRISME_RPS", 5.0),
        )
        return cls(
            http=http,
            cache_dir=os.environ.get("PRISME_CACHE_DIR", ".prisme-cache"),
            offline=os.environ.get("PRISME_OFFLINE", "").strip().lower()
            in {"1", "true", "yes", "oui"},
        )


def assert_allowed_host(hostname: str) -> None:
    """Refuse toute destination hors du perimetre Wikimedia.

    Le client ne prend jamais d'URL arbitraire en entree : il compose ses URL
    a partir d'un code de langue valide. Ce controle est la seconde barriere,
    celle qui tient si la premiere est contournee - notamment en cas de
    redirection HTTP vers un hote tiers.
    """
    host = (hostname or "").lower()
    if not any(
        host == suffix.lstrip(".") or host.endswith(suffix)
        for suffix in _ALLOWED_HOST_SUFFIXES
    ):
        raise ConfigurationError(f"hote hors perimetre Wikimedia : {hostname!r}")
