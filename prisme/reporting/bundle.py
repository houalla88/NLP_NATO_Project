"""Export auditable d'un rapport.

Un rapport PRISME n'est pas un fichier de resultats : c'est un dossier de
preuve. Il porte l'empreinte du corpus analyse, la version de la methode, les
parametres effectifs et les avertissements emis. Un tiers doit pouvoir, a partir
du seul export, rejouer le calcul et obtenir les memes chiffres - ou identifier
precisement ce qui a change.
"""

from __future__ import annotations

import json
from datetime import timezone
from pathlib import Path
from typing import Any

from .. import METHOD_VERSION, __version__
from ..domain.models import AnalysisReport, canonical_hash, to_jsonable

BUNDLE_SCHEMA = "prisme-report/1"


def to_payload(report: AnalysisReport) -> dict[str, Any]:
    """Structure JSON complete du rapport, scellee par une empreinte."""
    body = {
        "schema": BUNDLE_SCHEMA,
        "tool_version": __version__,
        "method_version": METHOD_VERSION,
        "generated_at": report.generated_at.astimezone(timezone.utc).isoformat(),
        "data_nature": report.data_nature,
        "entity": {"qid": report.entity_qid, "label": report.entity_label},
        "corpus_id": report.corpus_id,
        "input_fingerprint": report.input_fingerprint,
        "parameters": to_jsonable(report.parameters),
        "warnings": list(report.warnings),
        "langs": list(report.langs),
        "distributions": [
            {
                "lang": d.lang,
                "support": d.support,
                "total_mass": d.total_mass,
                "entropy_bits": d.entropy_bits(),
                "smoothing": d.smoothing,
            }
            for d in report.distributions
        ],
        "divergence": {
            "grid": report.divergence.as_grid(),
            "pairs": [to_jsonable(p) for p in report.divergence.pairs],
            "mean_by_lang": {
                lang: report.divergence.mean_divergence(lang) for lang in report.langs
            },
        },
        "distinctive": [to_jsonable(d) for d in report.distinctive],
        "silences": [to_jsonable(s) for s in report.silences],
        "contestedness": [
            {
                **{
                    k: v
                    for k, v in to_jsonable(c).items()
                    if k != "intensity_series"
                },
                "intensity_series": [
                    [moment.astimezone(timezone.utc).isoformat(), value]
                    for moment, value in c.intensity_series
                ],
            }
            for c in report.contestedness
        ],
        "drift": [to_jsonable(d) for d in report.drift],
        "embedding": {k: list(v) for k, v in report.embedding.items()},
    }
    # L'empreinte porte sur le corps du rapport, elle-meme exclue du calcul :
    # ajouter une valeur qui se contiendrait serait impossible a verifier.
    body["report_fingerprint"] = canonical_hash(body)
    return body


def write_bundle(report: AnalysisReport, path: str | Path) -> Path:
    """Ecrit le rapport JSON. Cles triees : deux exports identiques diffent a zero octet."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(to_payload(report), ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return target


def audit_manifest(report: AnalysisReport) -> str:
    """Manifeste d'audit en texte, destine a accompagner un livrable."""
    lines = [
        "MANIFESTE D'AUDIT - PRISME",
        "=" * 62,
        f"Outil               : prisme {__version__}",
        f"Version de methode  : {METHOD_VERSION}",
        f"Genere le           : {report.generated_at.astimezone(timezone.utc).isoformat()}",
        f"Entite              : {report.entity_label} ({report.entity_qid})",
        f"Corpus              : {report.corpus_id}",
        f"NATURE DES DONNEES  : {report.data_nature.upper()}",
        f"Empreinte du corpus : {report.input_fingerprint}",
        f"Editions comparees  : {', '.join(report.langs)}",
        "",
        "PARAMETRES EFFECTIFS",
        "-" * 62,
    ]
    for key, value in sorted(report.parameters.items()):
        lines.append(f"  {key:<26} {value}")

    lines += ["", "AVERTISSEMENTS", "-" * 62]
    if report.warnings:
        lines.extend(f"  - {w}" for w in report.warnings)
    else:
        lines.append("  aucun")

    if report.data_nature.startswith("synth"):
        lines += [
            "",
            "!" * 62,
            "CORPUS SYNTHETIQUE. Les chiffres de ce rapport decrivent une",
            "structure generee et n'ont AUCUNE valeur d'observation empirique.",
            "!" * 62,
        ]
    return "\n".join(lines)
