"""Rendu HTML d'un rapport.

Une seule implementation sert trois usages : export statique hors ligne, vue de
l'application Flask, et tableau de bord publie. Le rendu est donc le produit de
l'outil, pas une maquette redigee a cote - ce que montre l'ecran est ce que
calcule le moteur.

Conformite a la charte DataOptimization.be :
- la menthe vive n'apparait jamais en texte ni en element porteur de sens ;
- les echelles de data-visualisation sont distinctes de la palette de marque ;
- l'etat est toujours double par un texte, jamais porte par la couleur seule ;
- `prefers-reduced-motion` neutralise integralement animations et transitions ;
- le motif de grille menthe reste sur les surfaces d'accueil, jamais derriere
  une zone de donnees.
"""

from __future__ import annotations

import html
from datetime import timezone
from typing import Iterable, Sequence

from .. import METHOD_VERSION, __version__
from ..domain.models import AnalysisReport
from . import brand

LANG_NAMES = {
    "en": "anglais", "fr": "francais", "de": "allemand", "ru": "russe",
    "pl": "polonais", "uk": "ukrainien", "es": "espagnol", "it": "italien",
    "tr": "turc", "zh": "chinois", "nl": "neerlandais", "pt": "portugais",
    "aa": "test A", "bb": "test B", "cc": "test C", "dd": "test D",
}


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def lang_name(code: str) -> str:
    return LANG_NAMES.get(code, code)


def _css_variables() -> str:
    """Bloc de variables CSS derive de `brand.py`, seule source de verite."""
    light = [
        f"--ink:{brand.INK}", f"--surface:{brand.SURFACE}",
        f"--brand:{brand.BRAND}", f"--brand-deep:{brand.BRAND_DEEP}",
        f"--brand-soft:{brand.BRAND_SOFT}", f"--accent:{brand.ACCENT}",
        f"--accent-deep:{brand.ACCENT_DEEP}", f"--grid:{brand.GRID}",
        f"--warning:{brand.SEMANTIC['warning']}", f"--danger:{brand.SEMANTIC['danger']}",
        "--panel:#ffffff", "--muted:#525a6b", "--line:#dde1e8",
        "--zebra:#f7f8fa", "--hover:#eef0f4",
        f"--elev:{brand.ELEVATION_BRAND}",
    ]
    # En sombre, la contrainte s'inverse : la menthe vive atteint 10,7:1 sur
    # l'encre et redevient utilisable pour du texte. C'est la seule inversion
    # autorisee par la charte.
    dark = [
        "--ink:#eef0f4", "--surface:#090b10", "--panel:#11151c",
        "--brand-deep:#3fe0bd", "--accent-deep:#b9a5f5", "--muted:#9aa3b4",
        "--line:#242c38", "--zebra:#0e131a", "--hover:#18202b", "--grid:#242c38",
        "--warning:#e0a344", "--danger:#f08b81",
        "--elev:0 20px 48px rgba(0,0,0,.45)",
    ]
    joined_light = ";".join(light)
    joined_dark = ";".join(dark)
    return (
        f":root{{{joined_light};color-scheme:light}}"
        f"@media (prefers-color-scheme:dark){{:root:not([data-theme='light']){{{joined_dark};color-scheme:dark}}}}"
        f":root[data-theme='dark']{{{joined_dark};color-scheme:dark}}"
    )


_STATIC_CSS = """
*{box-sizing:border-box}
body{margin:0;background:var(--surface);color:var(--ink);
  font-family:Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;
  font-size:15px;line-height:1.6;text-rendering:optimizeLegibility;
  -webkit-font-smoothing:antialiased;-moz-osx-font-smoothing:grayscale}
.wrap{max-width:1120px;margin:0 auto;padding-block:40px;padding-left:20px;padding-right:20px}
h1,h2,h3{line-height:1.25;margin:0;font-weight:650;letter-spacing:-.015em}
h1{font-size:clamp(1.9rem,4vw,2.7rem)}
h2{font-size:1.35rem;margin-bottom:6px}
h3{font-size:1rem;margin-bottom:4px}
p{margin:.5em 0}
a{color:var(--brand-deep);text-underline-offset:3px}
.mono{font-family:"JetBrains Mono",ui-monospace,SFMono-Regular,Menlo,monospace;
  font-variant-numeric:tabular-nums}
.muted{color:var(--muted)}
.small{font-size:.82rem}
.micro{font-size:.74rem;letter-spacing:.04em;text-transform:uppercase;font-weight:600}

/* Motif signature : surfaces d'accueil uniquement, jamais derriere des donnees. */
.hero{position:relative;border-radius:1.25rem;overflow:hidden;padding:34px 28px;
  border:1px solid var(--line);background:var(--panel)}
.hero::before{content:"";position:absolute;inset:0;pointer-events:none;
  background-image:linear-gradient(var(--brand) 1px,transparent 1px),
    linear-gradient(90deg,var(--brand) 1px,transparent 1px);
  background-size:34px 34px;opacity:.08}
.hero>*{position:relative}
.eyebrow{display:inline-flex;align-items:center;gap:8px;font-size:.72rem;
  letter-spacing:.16em;text-transform:uppercase;font-weight:700;color:var(--brand-deep)}
.eyebrow::before{content:"";width:22px;height:2px;background:var(--brand-deep);border-radius:2px}
.lede{font-size:1.05rem;max-width:66ch;color:var(--muted);margin-top:14px}

.chips{display:flex;flex-wrap:wrap;gap:8px;margin-top:20px}
.chip{border:1px solid var(--line);border-radius:9999px;padding:5px 12px;font-size:.78rem;
  background:var(--surface);color:var(--muted)}
.chip b{color:var(--ink);font-weight:600}

.banner{display:flex;gap:14px;align-items:flex-start;border-radius:.875rem;padding:16px 18px;
  margin:24px 0;border:1px solid var(--warning);
  background:color-mix(in srgb,var(--warning) 9%,var(--surface))}
.banner .icon{flex:none;width:22px;height:22px;border-radius:50%;border:2px solid var(--warning);
  color:var(--warning);font-weight:800;font-size:13px;display:grid;place-items:center;margin-top:2px}
.banner strong{color:var(--warning)}

section{margin-top:44px}
.sec-head{display:flex;align-items:baseline;justify-content:space-between;gap:16px;
  flex-wrap:wrap;border-bottom:1px solid var(--line);padding-bottom:10px;margin-bottom:18px}
.note{max-width:72ch;color:var(--muted);font-size:.9rem}

.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:14px}
.kpi{border:1px solid var(--line);border-radius:.875rem;padding:16px 18px;background:var(--panel);
  transition:transform 220ms var(--ease),box-shadow 220ms var(--ease)}
.kpi:hover{transform:translateY(-3px);box-shadow:var(--elev)}
.kpi .v{font-size:1.9rem;font-weight:680;letter-spacing:-.02em;line-height:1.1;margin-top:6px}
.kpi .k{color:var(--muted);font-size:.75rem;letter-spacing:.05em;text-transform:uppercase;font-weight:600}
.kpi .h{color:var(--muted);font-size:.8rem;margin-top:6px}

.panel{border:1px solid var(--line);border-radius:.875rem;background:var(--panel);padding:18px}
.scroll{overflow-x:auto}
.cols{display:grid;grid-template-columns:repeat(auto-fit,minmax(330px,1fr));gap:20px}

table{border-collapse:collapse;width:100%;font-size:.88rem}
th,td{text-align:left;padding:9px 12px;border-bottom:1px solid var(--line);white-space:nowrap}
th{font-size:.72rem;letter-spacing:.05em;text-transform:uppercase;color:var(--muted);font-weight:650}
td.num,th.num{text-align:right;font-family:"JetBrains Mono",ui-monospace,monospace;
  font-variant-numeric:tabular-nums}
tbody tr:nth-child(even){background:var(--zebra)}
tbody tr:hover{background:var(--hover)}
td.wrap-cell{white-space:normal;min-width:220px}

.tag{display:inline-flex;align-items:center;gap:5px;border-radius:9999px;padding:2px 9px;
  font-size:.72rem;font-weight:650;border:1px solid currentColor}
.tag-ok{color:var(--brand-deep)}
.tag-no{color:var(--muted)}

.ivbar{position:relative;height:22px;min-width:150px}
.ivbar .track{position:absolute;inset:9px 0 auto 0;height:3px;background:var(--line);border-radius:2px}
.ivbar .band{position:absolute;top:5px;height:11px;border-radius:3px;
  background:color-mix(in srgb,var(--brand-deep) 15%,transparent)}
.ivbar .pt{position:absolute;top:3px;width:3px;height:15px;border-radius:2px;background:var(--brand-deep)}
.ivbar .null{position:absolute;top:1px;width:1px;height:19px;background:var(--muted);opacity:.55}

.bars{display:grid;gap:7px}
.bar{display:grid;grid-template-columns:1fr auto;gap:10px;align-items:center;font-size:.85rem}
.bar .lbl{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.bar .track{grid-column:1/-1;height:7px;border-radius:4px;background:var(--line);overflow:hidden}
.bar .fill{height:100%;border-radius:4px;transition:width 700ms var(--ease)}

.legend{display:flex;gap:14px;flex-wrap:wrap;align-items:center;margin-top:12px;
  font-size:.78rem;color:var(--muted)}
.swatch{display:inline-block;width:12px;height:12px;border-radius:3px;margin-right:6px;
  vertical-align:-2px}

.audit{font-size:.82rem}
.audit dt{color:var(--muted);font-size:.72rem;letter-spacing:.05em;text-transform:uppercase;
  font-weight:650;margin-top:12px}
.audit dd{margin:2px 0 0;word-break:break-all;font-family:"JetBrains Mono",ui-monospace,monospace}

footer{margin-top:56px;padding-top:20px;border-top:1px solid var(--line);
  color:var(--muted);font-size:.82rem}

.reveal{opacity:0;transform:translateY(22px);animation:reveal 700ms var(--ease) forwards}
@keyframes reveal{to{opacity:1;transform:none}}

@media (max-width:560px){
  th,td{padding:8px 9px;font-size:.82rem}
  .wrap{padding-block:26px}
  .hero{padding:24px 18px}
}
@media (prefers-reduced-motion:reduce){
  *,*::before,*::after{animation:none!important;transition:none!important;
    transform:none!important;scroll-behavior:auto!important}
  .reveal{opacity:1}
}
"""


# ---------------------------------------------------------------------------
# Composants
# ---------------------------------------------------------------------------


def _heatmap(report: AnalysisReport) -> str:
    """Matrice de chaleur des divergences, en SVG autonome."""
    langs = list(report.langs)
    grid = report.divergence.as_grid()
    peak = max((max(row) for row in grid), default=0.0) or 1.0

    cell, gutter, top = 64, 74, 34
    width = gutter + cell * len(langs) + 8
    height = top + cell * len(langs) + 8

    parts = [
        f'<svg viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
        f'role="img" aria-label="Matrice de divergence entre editions">'
    ]
    for index, lang in enumerate(langs):
        x = gutter + cell * index + cell / 2
        parts.append(
            f'<text x="{x:.0f}" y="{top - 12}" text-anchor="middle" font-size="12" '
            f'font-weight="650" fill="{brand.NEUTRAL["600"]}">{esc(lang)}</text>'
        )
        y = top + cell * index + cell / 2
        parts.append(
            f'<text x="{gutter - 10}" y="{y + 4:.0f}" text-anchor="end" font-size="12" '
            f'font-weight="650" fill="{brand.NEUTRAL["600"]}">{esc(lang)}</text>'
        )

    for row, lang_a in enumerate(langs):
        for col, lang_b in enumerate(langs):
            x = gutter + cell * col
            y = top + cell * row
            if row == col:
                parts.append(
                    f'<rect x="{x}" y="{y}" width="{cell - 3}" height="{cell - 3}" rx="7" '
                    f'fill="none" stroke="{brand.GRID}" stroke-dasharray="3 3"/>'
                )
                continue
            value = grid[row][col]
            fill = brand.scale_color(value / peak)
            ink = brand.readable_on(fill)
            pair = report.divergence.get(lang_a, lang_b)
            mark = "" if pair.is_significant else "○"
            parts.append(
                f'<g><title>{esc(lang_a)} / {esc(lang_b)} - JSD {value:.3f}'
                f'{"" if pair.is_significant else " (non significatif)"}</title>'
                f'<rect x="{x}" y="{y}" width="{cell - 3}" height="{cell - 3}" rx="7" fill="{fill}"/>'
                f'<text x="{x + (cell - 3) / 2:.0f}" y="{y + (cell - 3) / 2 + 5:.0f}" '
                f'text-anchor="middle" font-size="13" font-weight="600" fill="{ink}" '
                f'font-family="JetBrains Mono,ui-monospace,monospace">{value:.2f}{mark}</text></g>'
            )

    parts.append("</svg>")
    return "".join(parts)


def _map(report: AnalysisReport) -> str:
    """Carte 2D des editions, par positionnement multidimensionnel."""
    points = report.embedding
    if not points:
        return "<p class='muted'>Projection indisponible.</p>"

    xs = [p[0] for p in points.values()]
    ys = [p[1] for p in points.values()]
    span_x = max(max(xs) - min(xs), 1e-9)
    span_y = max(max(ys) - min(ys), 1e-9)
    width, height, pad = 560, 340, 54

    parts = [
        f'<svg viewBox="0 0 {width} {height}" width="100%" height="{height}" '
        'role="img" aria-label="Carte des proximites de cadrage entre editions">'
    ]
    for step in range(1, 4):
        y = pad + (height - 2 * pad) * step / 4
        parts.append(
            f'<line x1="{pad}" y1="{y:.0f}" x2="{width - pad}" y2="{y:.0f}" '
            f'stroke="{brand.GRID}" stroke-width="1"/>'
        )

    ordered = sorted(points.items(), key=lambda kv: kv[0])
    isolated = report.most_isolated_lang()
    for index, (lang, (x, y)) in enumerate(ordered):
        cx = pad + (x - min(xs)) / span_x * (width - 2 * pad)
        cy = height - pad - (y - min(ys)) / span_y * (height - 2 * pad)
        colour = brand.CATEGORICAL[index % len(brand.CATEGORICAL)]
        radius = 13 if lang == isolated else 9
        parts.append(
            f'<g><title>{esc(lang)} - divergence moyenne '
            f'{report.divergence.mean_divergence(lang):.3f}</title>'
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{radius + 7}" fill="{colour}" opacity=".12"/>'
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{radius}" fill="{colour}"/>'
            f'<text x="{cx:.1f}" y="{cy - radius - 9:.1f}" text-anchor="middle" font-size="13" '
            f'font-weight="700" fill="{colour}">{esc(lang)}</text></g>'
        )
    parts.append("</svg>")
    return "".join(parts)


def _sparkline(values: Sequence[float], colour: str) -> str:
    if len(values) < 2:
        return '<span class="muted small">-</span>'
    width, height = 120, 26
    peak = max(values) or 1.0
    step = width / (len(values) - 1)
    points = " ".join(
        f"{i * step:.1f},{height - 2 - (v / peak) * (height - 5):.1f}"
        for i, v in enumerate(values)
    )
    return (
        f'<svg viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
        f'aria-hidden="true"><polyline points="{points}" fill="none" stroke="{colour}" '
        f'stroke-width="1.6" stroke-linejoin="round"/></svg>'
    )


def _interval_bar(pair, peak: float) -> str:
    """Point estime, dispersion et niveau nul, sur une meme echelle."""
    def position(value: float) -> float:
        return max(0.0, min(100.0, value / peak * 100.0))

    segments = [f'<div class="ivbar" title="JSD {pair.jsd:.3f}">', '<span class="track"></span>']
    if pair.interval:
        left = position(pair.interval.lower)
        right = position(pair.interval.upper)
        segments.append(
            f'<span class="band" style="left:{left:.1f}%;width:{max(right - left, 0.6):.1f}%"></span>'
        )
    if pair.null_median is not None:
        segments.append(
            f'<span class="null" style="left:{position(pair.null_median):.1f}%" '
            f'title="niveau nul {pair.null_median:.3f}"></span>'
        )
    segments.append(f'<span class="pt" style="left:{position(pair.jsd):.1f}%"></span>')
    segments.append("</div>")
    return "".join(segments)


def _pairs_table(report: AnalysisReport) -> str:
    pairs = sorted(report.divergence.pairs, key=lambda p: p.jsd, reverse=True)
    peak = max((p.jsd for p in pairs), default=1.0) or 1.0
    rows = []
    for pair in pairs:
        interval = (
            f"{pair.interval.lower:.3f} – {pair.interval.upper:.3f}"
            if pair.interval
            else "-"
        )
        null_level = f"{pair.null_median:.3f}" if pair.null_median is not None else "-"
        p_value = f"{pair.null_p_value:.3f}" if pair.null_p_value is not None else "-"
        verdict = (
            '<span class="tag tag-ok">✓ mesure</span>'
            if pair.is_significant
            else '<span class="tag tag-no">○ bruit</span>'
        )
        rows.append(
            f"<tr><td><b>{esc(pair.lang_a)}</b> / <b>{esc(pair.lang_b)}</b></td>"
            f"<td>{_interval_bar(pair, peak)}</td>"
            f'<td class="num">{pair.jsd:.3f}</td>'
            f'<td class="num">{esc(interval)}</td>'
            f'<td class="num">{esc(null_level)}</td>'
            f'<td class="num">{esc(p_value)}</td>'
            f'<td class="num">{pair.overlap:.0%}</td>'
            f"<td>{verdict}</td></tr>"
        )

    return (
        '<div class="panel scroll"><table><thead><tr>'
        "<th>Paire d'editions</th><th>Echelle</th><th class='num'>JSD</th>"
        "<th class='num'>Dispersion 95%</th><th class='num'>Niveau nul</th>"
        "<th class='num'>p</th><th class='num'>Recouvrement</th><th>Verdict</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"
    )


def _distinctive_blocks(report: AnalysisReport) -> str:
    blocks = []
    for index, lang in enumerate(report.langs):
        top = report.distinctive_for(lang, limit=6)
        colour = brand.CATEGORICAL[index % len(brand.CATEGORICAL)]
        if not top:
            body = "<p class='muted small'>Aucun concept ne depasse le seuil de significativite.</p>"
        else:
            peak = max(d.z_score for d in top) or 1.0
            bars = []
            for item in top:
                share = f"{item.share_in:.1%} ici contre {item.share_out:.1%} ailleurs"
                bars.append(
                    f'<div class="bar"><span class="lbl" title="{esc(share)}">'
                    f"{esc(item.label)}</span>"
                    f'<span class="mono small muted">z={item.z_score:.1f}</span>'
                    f'<span class="track"><span class="fill" style="width:'
                    f'{item.z_score / peak * 100:.0f}%;background:{colour}"></span></span></div>'
                )
            body = f'<div class="bars">{"".join(bars)}</div>'
        blocks.append(
            f'<div class="panel"><h3 style="color:{colour}">{esc(lang)} '
            f'<span class="muted small" style="font-weight:400">- {esc(lang_name(lang))}</span></h3>'
            f'<p class="muted small" style="margin-top:0">Divergence moyenne aux autres editions : '
            f'<b class="mono">{report.divergence.mean_divergence(lang):.3f}</b></p>{body}</div>'
        )
    return f'<div class="cols">{"".join(blocks)}</div>'


def _silences_table(report: AnalysisReport, limit: int = 12) -> str:
    if not report.silences:
        return (
            "<div class='panel'><p class='muted'>Aucun silence structurel detecte : "
            "tout concept installe dans au moins deux editions est present partout.</p></div>"
        )
    rows = "".join(
        f'<tr><td class="wrap-cell">{esc(item.label)}</td>'
        f"<td><b>{esc(item.absent_in)}</b></td>"
        f'<td class="muted">{esc(", ".join(item.present_in))}</td>'
        f'<td class="num">{item.mean_share_elsewhere:.2%}</td></tr>'
        for item in report.silences[:limit]
    )
    more = (
        f"<p class='muted small'>{len(report.silences) - limit} autres silences dans l'export JSON.</p>"
        if len(report.silences) > limit
        else ""
    )
    return (
        '<div class="panel scroll"><table><thead><tr><th>Concept</th><th>Absent de</th>'
        "<th>Present dans</th><th class='num'>Part moyenne ailleurs</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>{more}</div>"
    )


def _contestedness_table(report: AnalysisReport) -> str:
    profiles = sorted(report.contestedness, key=lambda p: p.revert_rate, reverse=True)
    if not any(p.n_revisions for p in profiles):
        return "<div class='panel'><p class='muted'>Aucun historique de revision dans le corpus.</p></div>"

    rows = []
    for index, item in enumerate(profiles):
        colour = brand.CATEGORICAL[index % len(brand.CATEGORICAL)]
        series = [value for _, value in item.intensity_series]
        rows.append(
            f"<tr><td><b>{esc(item.lang)}</b> <span class='muted small'>{esc(lang_name(item.lang))}</span></td>"
            f'<td class="num">{item.n_revisions}</td>'
            f'<td class="num">{item.identity_reverts}</td>'
            f'<td class="num">{item.revert_rate:.1%}</td>'
            f'<td class="num">{item.mutual_revert_index:.2f}</td>'
            f'<td class="num">{item.distinct_editors}</td>'
            f'<td class="num">{item.anonymous_share:.0%}</td>'
            f"<td>{_sparkline(series, colour)}</td></tr>"
        )
    return (
        '<div class="panel scroll"><table><thead><tr><th>Edition</th>'
        "<th class='num'>Revisions</th><th class='num'>Reverts</th><th class='num'>Taux</th>"
        "<th class='num'>Indice mutuel</th><th class='num'>Contributeurs</th>"
        "<th class='num'>Anonymes</th><th>Intensite</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )


def _kpis(report: AnalysisReport) -> str:
    pairs = report.divergence.pairs
    significant = sum(1 for p in pairs if p.is_significant)
    mean_jsd = sum(p.jsd for p in pairs) / len(pairs) if pairs else 0.0
    isolated = report.most_isolated_lang()
    most_contested = max(
        report.contestedness, key=lambda c: c.revert_rate, default=None
    )

    cards = [
        ("Editions comparees", str(len(report.langs)), ", ".join(report.langs)),
        ("Espace conceptuel", str(report.parameters.get("concept_space_size", "-")),
         "concepts distincts, identifies par QID"),
        ("Divergence moyenne", f"{mean_jsd:.3f}", "JSD corrigee, sur toutes les paires"),
        ("Paires mesurees", f"{significant}/{len(pairs)}",
         "au-dela du bruit d'echantillonnage (p &lt; 0,05)"),
        ("Cadrage le plus singulier", isolated,
         f"divergence moyenne {report.divergence.mean_divergence(isolated):.3f}"),
    ]
    if most_contested and most_contested.n_revisions:
        cards.append(
            ("Edition la plus contestee", most_contested.lang,
             f"{most_contested.revert_rate:.1%} de revisions annulees")
        )

    return '<div class="kpis">' + "".join(
        f'<div class="kpi reveal" style="animation-delay:{i * 80}ms">'
        f'<div class="k">{esc(k)}</div><div class="v">{esc(v)}</div>'
        f'<div class="h">{h}</div></div>'
        for i, (k, v, h) in enumerate(cards)
    ) + "</div>"


def _banner(report: AnalysisReport) -> str:
    if not report.data_nature.startswith("synth"):
        return ""
    return (
        '<div class="banner" role="note"><span class="icon" aria-hidden="true">!</span><div>'
        "<strong>Corpus synthetique - aucune valeur empirique.</strong> "
        "Les chiffres de cette page proviennent d'un corpus genere et ne decrivent "
        "ni Wikipedia, ni l'OTAN, ni aucun sujet reel. Les identifiants de concepts "
        "appartiennent a une plage reservee (Q9xxxxxxxx) qui n'existe pas sur "
        "Wikidata. La page montre <em>la forme</em> d'un resultat PRISME, pas un resultat."
        "</div></div>"
    )


def _audit(report: AnalysisReport) -> str:
    parameters = "".join(
        f"<dt>{esc(k)}</dt><dd>{esc(v)}</dd>" for k, v in sorted(report.parameters.items())
    )
    warnings = (
        "".join(f"<li>{esc(w)}</li>" for w in report.warnings)
        if report.warnings
        else "<li class='muted'>aucun</li>"
    )
    return (
        '<div class="cols"><div class="panel audit"><h3>Tracabilite</h3><dl>'
        f"<dt>Nature des donnees</dt><dd>{esc(report.data_nature)}</dd>"
        f"<dt>Corpus</dt><dd>{esc(report.corpus_id)}</dd>"
        f"<dt>Empreinte du corpus</dt><dd>{esc(report.input_fingerprint)}</dd>"
        f"<dt>Version de methode</dt><dd>{esc(report.method_version)}</dd>"
        f"<dt>Genere le</dt>"
        f"<dd>{esc(report.generated_at.astimezone(timezone.utc).isoformat(timespec='seconds'))}</dd>"
        "</dl></div>"
        f'<div class="panel audit"><h3>Parametres effectifs</h3><dl>{parameters}</dl></div>'
        f'<div class="panel"><h3>Avertissements</h3><ul class="small">{warnings}</ul></div></div>'
    )


_METHOD_NOTE = """
<div class="cols">
<div class="panel"><h3>Ce qui est mesure</h3>
<p class="small muted">Chaque lien interne d'un article pointe vers une page qui porte un
identifiant Wikidata, identique dans toutes les langues. Compter ces identifiants transforme
un article en distribution d'attention sur un espace de concepts neutre linguistiquement.
Deux editions deviennent alors directement comparables, sans traduction automatique, sans
lemmatisation et sans lexique de sentiment - c'est-a-dire sans les trois composants dont la
performance varie le plus d'une langue a l'autre.</p></div>

<div class="panel"><h3>Comment l'ecart est valide</h3>
<p class="small muted">Deux echantillons tires d'une meme population produisent deja une
divergence non nulle. Chaque paire est donc accompagnee de son niveau nul - la divergence
qu'on obtiendrait sans aucun ecart de cadrage - etabli par permutation exacte des occurrences
mises en commun. La mesure elle-meme est corrigee du biais de sous-echantillonnage
(Miller-Madow) : sans cette correction, l'estimateur renvoie environ 0,058 la ou la
valeur vraie est zero, et le classement des editions refleterait en partie la longueur des
articles.</p></div>

<div class="panel"><h3>Ce que la mesure ne dit pas</h3>
<p class="small muted">Un ecart de cadrage n'est pas un mensonge, une contestation editoriale
n'est pas une erreur factuelle, et un silence structurel signale l'absence d'un lien, pas
l'absence d'un sujet - une edition peut traiter un theme en prose sans jamais le lier. La
ponderation par section repose sur une hypothese posee, pas mesuree. Enfin, ne sont comparees
que les editions qui possedent un article : l'absence totale d'article est une information
que cette page ne contient pas.</p></div>
</div>
"""


# ---------------------------------------------------------------------------
# Assemblage
# ---------------------------------------------------------------------------


def render_fragment(report: AnalysisReport) -> str:
    """Titre, styles et contenu - sans squelette HTML.

    Cette forme est directement publiable comme page hebergee, et sert de corps
    au document autonome renvoye par `render_document`.
    """
    fit = float(report.parameters.get("embedding_fit", 0.0))
    fit_note = (
        f"Ajustement de la projection : {fit:.0%}."
        if fit >= 0.6
        else f"Ajustement faible ({fit:.0%}) : se referer a la matrice complete."
    )

    return f"""<title>Prisme - {esc(report.entity_label)}</title>
<style>{_css_variables()}:root{{--ease:{brand.EASING}}}{_STATIC_CSS}</style>
<div class="wrap">
  <header class="hero reveal">
    <div class="eyebrow">DataOptimization.be &middot; Prisme</div>
    <h1>Refraction narrative</h1>
    <p class="lede">Un meme referent, decrit par plusieurs editions linguistiques de
    Wikipedia. Cette page mesure de combien la repartition de l'attention change selon
    la langue, avec quelle incertitude, et a quel point chaque version est contestee par
    ses propres contributeurs.</p>
    <div class="chips">
      <span class="chip">Entite <b>{esc(report.entity_label)}</b></span>
      <span class="chip">QID <b class="mono">{esc(report.entity_qid)}</b></span>
      <span class="chip">Corpus <b>{esc(report.corpus_id)}</b></span>
      <span class="chip">Methode <b class="mono">v{esc(report.method_version)}</b></span>
      <span class="chip">Nature <b>{esc(report.data_nature)}</b></span>
    </div>
  </header>

  {_banner(report)}

  <section><div class="sec-head"><h2>Synthese</h2></div>{_kpis(report)}</section>

  <section>
    <div class="sec-head"><h2>Carte des cadrages</h2>
      <span class="small muted">{esc(fit_note)}</span></div>
    <p class="note">Positionnement multidimensionnel de la racine de la divergence -
    seule forme metrique de la mesure, donc seule projection justifiee. Deux editions
    proches repartissent leur attention de facon comparable. Le point le plus large est
    l'edition dont le cadrage s'ecarte le plus de l'ensemble.</p>
    <div class="panel scroll">{_map(report)}</div>
  </section>

  <section>
    <div class="sec-head"><h2>Matrice de divergence</h2>
      <span class="small muted">JSD corrigee, 0 = cadrages identiques</span></div>
    <p class="note">Un cercle apres la valeur signale une paire dont l'ecart ne depasse
    pas le bruit d'echantillonnage : il ne doit pas etre interprete.</p>
    <div class="panel scroll">{_heatmap(report)}</div>
    <div class="legend">
      <span><span class="swatch" style="background:{brand.SEQUENTIAL[0]}"></span>proche</span>
      <span><span class="swatch" style="background:{brand.SEQUENTIAL[3]}"></span>intermediaire</span>
      <span><span class="swatch" style="background:{brand.SEQUENTIAL[5]}"></span>eloigne</span>
      <span>&#9675; ecart non distinguable du bruit</span>
    </div>
  </section>

  <section>
    <div class="sec-head"><h2>Divergences par paire</h2>
      <span class="small muted">point estime, dispersion et niveau nul</span></div>
    <p class="note">La bande claire est la dispersion d'echantillonnage a 95 % : de combien
    le chiffre bougerait si les deux articles etaient un autre tirage de meme longueur. Le
    trait gris est le niveau nul, celui qu'obtiendraient deux editions sans aucun ecart de
    cadrage. Un point proche du trait gris ne mesure rien.</p>
    {_pairs_table(report)}
  </section>

  <section>
    <div class="sec-head"><h2>Ce que chaque edition met en avant</h2>
      <span class="small muted">log-odds a prior de Dirichlet informatif</span></div>
    <p class="note">Score z de sur-representation contre toutes les autres editions reunies.
    Le prior informatif empeche qu'un concept vu une seule fois domine le classement - defaut
    systematique des comparaisons par simple difference de frequences.</p>
    {_distinctive_blocks(report)}
  </section>

  <section>
    <div class="sec-head"><h2>Silences structurels</h2>
      <span class="small muted">concepts installes ailleurs, absents ici</span></div>
    <p class="note">Concepts pesant au moins 0,5 % de l'attention dans au moins deux editions,
    et totalement absents d'une autre. L'absence d'un lien n'est pas l'absence d'un sujet :
    c'est un signal plus faible qu'une absence semantique, mais nettement plus objectivable.</p>
    {_silences_table(report)}
  </section>

  <section>
    <div class="sec-head"><h2>Contestation editoriale</h2>
      <span class="small muted">stabilite du texte, pas veracite</span></div>
    <p class="note">Un retour arriere est detecte lorsqu'une revision reproduit exactement
    l'empreinte SHA-1 d'une revision anterieure. Definition stricte : elle rate les annulations
    partielles, mais ne produit quasiment aucun faux positif. Le taux mesure est donc un
    plancher. L'indice mutuel ne compte que les contributeurs qui se defont reciproquement,
    ce qui distingue un conflit d'une patrouille anti-vandalisme.</p>
    {_contestedness_table(report)}
  </section>

  <section>
    <div class="sec-head"><h2>Methode, portee et limites</h2></div>
    {_METHOD_NOTE}
  </section>

  <section>
    <div class="sec-head"><h2>Audit</h2>
      <span class="small muted">de quoi rejouer le calcul</span></div>
    {_audit(report)}
  </section>

  <footer>
    <p><b>Prisme {esc(__version__)}</b> &middot; methode {esc(METHOD_VERSION)} &middot;
    moteur de mesure sans dependance d'execution &middot; DataOptimization.be</p>
    <p>Chaque chiffre de cette page est reproductible a partir de l'empreinte du corpus et
    des parametres listes ci-dessus. Le banc d'etalonnage (<span class="mono">prisme
    calibrate</span>) verifie sur corpus a divergence connue que l'instrument restitue ce
    qu'on y injecte.</p>
  </footer>
</div>"""


def render_document(report: AnalysisReport) -> str:
    """Page HTML autonome, utilisable hors ligne."""
    return (
        "<!doctype html><html lang='fr'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<meta name='robots' content='noindex'>"
        "</head><body>" + render_fragment(report) + "</body></html>"
    )
