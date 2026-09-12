# PRISME — mesure de la réfraction narrative

> Un même référent factuel, décrit par plusieurs éditions linguistiques de
> Wikipédia. PRISME mesure de combien la répartition de l'attention change selon
> la langue, avec quelle incertitude, et à quel point chaque version est
> contestée par ses propres contributeurs.

[![tests](https://img.shields.io/badge/tests-70%20passants-09806c)](tests/)
[![étalonnage](https://img.shields.io/badge/%C3%A9talonnage-6%2F6%20conforme-09806c)](docs/METHOD.md#8-banc-détalonnage)
[![dépendances](https://img.shields.io/badge/d%C3%A9pendances%20d'ex%C3%A9cution-0-09806c)](pyproject.toml)

---

## Le problème avec la question de départ

Ce dépôt visait initialement une *analyse de sentiment de l'OTAN sur Wikipédia
en russe*. La question ne peut pas recevoir de réponse défendable sous cette
forme, pour trois raisons :

1. **Pas d'échelle.** Un score de sentiment sur un seul corpus n'a pas de zéro.
   Comparé à quoi, « négatif » ?
2. **Instruments non étalonnés.** Un lexique de sentiment russe et un lexique
   anglais n'ont ni la même couverture ni la même calibration. Comparer leurs
   sorties, c'est comparer deux thermomètres gradués différemment.
3. **Objet mal posé.** Wikipédia n'est pas l'opinion publique. Ses contributeurs
   sont une population très particulière, et l'édition russophone est lue et
   écrite bien au-delà de la Russie.

**Ce que PRISME mesure à la place.** Wikipédia offre un dispositif
quasi-expérimental rare : le *même* référent, identifié sans ambiguïté par un
QID Wikidata, est décrit indépendamment par des dizaines de communautés
éditoriales. Le cadrage devient mesurable **en écart relatif** entre
descriptions — ce qui ne demande aucun étalon absolu.

## L'idée technique

Un article n'est pas traité comme du texte, mais comme un **graphe d'attention**.

```
article ru  ──┐
article en  ──┼──►  liens internes  ──►  QID Wikidata  ──►  distribution
article fr  ──┘                          (neutre par                sur un
                                          construction)        espace commun
```

Chaque lien interne pointe vers une page qui porte un identifiant Wikidata
**identique dans toutes les langues**. Compter ces identifiants transforme un
article en distribution de probabilité sur un espace conceptuel neutre.

Conséquence : **aucun modèle de langue n'intervient dans la chaîne.** Ni
traduction, ni lemmatisation, ni lexique de sentiment, ni plongement — c'est-à-dire
aucun des composants dont la performance varie le plus d'une langue à l'autre et
dont le versionnement échappe à l'analyste. La mesure est reproductible à
l'identique dans dix ans à partir du seul corpus figé.

Le prix à payer : on ne mesure que ce qui est **lié**. La mesure porte sur le
cadrage *structurel*, pas sur la tonalité. C'est un objet plus étroit que « la
perception », et nettement plus objectivable.

## Ce qui est mesuré

| Sortie | Question | Méthode |
|---|---|---|
| **Divergence** | De combien deux éditions s'écartent-elles ? | Jensen-Shannon corrigée du biais (Miller-Madow) |
| **Dispersion** | De combien ce chiffre bougerait-il sur un autre tirage ? | Bootstrap multinomial |
| **Significativité** | L'écart dépasse-t-il le bruit d'échantillonnage ? | Permutation exacte |
| **Concepts distinctifs** | Qu'est-ce que cette édition met en avant ? | Log-odds à prior de Dirichlet (Monroe *et al.* 2008) |
| **Silences structurels** | Qu'est-ce qu'elle est seule à ne pas lier ? | Absence sous double seuil |
| **Contestation** | À quel point le texte fait-il consensus ? | Reverts par identité SHA-1, indice mutuel |
| **Carte** | Quelles éditions se ressemblent ? | MDS classique sur √JSD (seule forme métrique) |

## Le banc d'étalonnage — et pourquoi il a changé le résultat

Un instrument qu'on ne peut pas étalonner ne vaut rien. `prisme calibrate`
génère des corpus dont la loi génératrice est **connue**, donc dont la
divergence vraie est calculable en forme close, et vérifie que la mesure la
retrouve.

```
[PASS] justesse (erreur absolue moyenne)  observe=0.0237     attendu < 0.05
[PASS] intervalle contenant l'estimation  observe=1.0000     attendu = 1.00
[PASS] taux de faux positifs (test nul)   observe=0.0100     attendu <= 0.10
[PASS] monotonie vs separation injectee   observe=0.0000     attendu 0 inversion
[PASS] rappel des concepts distinctifs    observe=0.8333     attendu >= 0.80
[PASS] detection des retours arriere      observe=1.0000     attendu = 1.00 (exact)

ETALONNAGE : CONFORME
```

Il n'est pas décoratif. Pendant le développement il a détecté **trois défauts
réels** qui auraient tous produit des chiffres faux et crédibles :

| Défaut | Détection | Conséquence évitée |
|---|---|---|
| Bascule vers l'approximation normale du tirage binomial sur un `and` au lieu d'un `or` — la loi normale était donc utilisée même pour une moyenne de 0,5 | moments du tireur : biais +15 %, variance −18 % | queues de la distribution nulle déformées, donc p-valeurs fausses |
| **Test de permutation paramétrique** au lieu d'exact | taux de faux positifs mesuré à **15,5 %** pour 5 % nominal | trois fois trop de divergences déclarées significatives |
| Estimateur JSD non corrigé du biais | **0,057** renvoyé là où la vraie valeur est **0** | le classement des éditions aurait reflété en partie la **longueur des articles** |

Le troisième mérite d'être souligné : c'est le mode de défaillance le plus
courant et le moins visible des analyses de corpus. Sans étalonnage, rien dans
le chiffre lui-même ne le signale. Correction appliquée : biais ramené de 0,057
à 0,018 (−68 %), résidu borné par le contrôle de justesse.

## Démarrage

```bash
git clone <ce dépôt> && cd NLP_NATO_Project

# 1. Étalonner l'instrument avant tout usage (≈ 4 s, aucune dépendance)
python3 -m prisme.cli calibrate

# 2. Voir à quoi ressemble une sortie (corpus SYNTHÉTIQUE, cf. avertissement)
python3 -m prisme.cli demo --out out
open out/demo.html

# 3. Collecter un corpus réel et le figer
python3 -m prisme.cli collect \
    --qid Q7184 --langs ru,en,fr,de,pl,uk \
    --out corpora/otan.json

# 4. Analyser
python3 -m prisme.cli analyse --corpus corpora/otan.json --out out

# 5. Interface web (seule étape nécessitant Flask)
pip install 'flask>=3.0' && python3 -m prisme.cli serve
```

Tests : `make test` — 70 tests, dont le banc d'étalonnage complet.

## ⚠ Sur les chiffres de la démonstration

**Le corpus de démonstration est entièrement généré. Il ne contient aucune
observation sur Wikipédia, sur l'OTAN, ni sur quoi que ce soit d'autre.**

La session de développement de cet outil n'avait pas d'accès sortant vers
`wikipedia.org` ni `wikidata.org` (refus 403 de la politique d'egress, vérifié
par deux voies). Fabriquer des chiffres présentés comme empiriques aurait été la
seule autre option. Elle n'a pas été retenue.

Trois garde-fous rendent la confusion impossible :

- les identifiants de concepts appartiennent à la plage réservée `Q9xxxxxxxx`,
  qui n'existe pas sur Wikidata — toute tentative de résolution échoue ;
- le corpus porte `nature: "synthetic-demo"`, valeur propagée jusque dans le
  rapport JSON, le manifeste d'audit, le HTML et l'interface web ;
- un bandeau non masquable apparaît sur toute page issue d'un corpus synthétique
  (test dédié : `test_synthetic_banner_is_not_optional`).

Le chemin vers de vraies mesures est `prisme collect`, dont le client MediaWiki
est complet et testé sur réponses d'API enregistrées.

## Architecture

```
prisme/
├── domain/        modèle métier immuable — aucun I/O, aucune dépendance
├── sources/       acquisition : client MediaWiki durci + corpus figés
├── metrics/       formules pures — divergence, distinctifs, contestation, MDS
├── pipeline/      orchestration — enchaîne les mesures, ne les définit pas
├── reporting/     export JSON scellé, manifeste d'audit, rendu HTML
├── calibration.py banc d'étalonnage sur corpus à divergence connue
└── scenarios.py   corpus de démonstration (synthétique, explicitement marqué)

app/               interface web Flask, lecture seule
```

**Le moteur de mesure n'a aucune dépendance d'exécution.** Choix délibéré :
surface d'approvisionnement nulle, métriques auditables ligne à ligne, exécution
possible en environnement contraint. Flask n'est requis que pour l'interface.

Points de sécurité, côté client MediaWiki : aucune URL acceptée en entrée (les
requêtes sont composées à partir d'un code de langue validé), contrôle de l'hôte
avant émission **et après redirection**, débit limité, taille de réponse
plafonnée, réessais bornés. Côté web : lecture seule, aucune route ne déclenche
d'appel sortant, CSP `default-src 'none'`, résolution des noms de corpus sur le
chemin *résolu* (protection contre la traversée, testée).

## Reproductibilité

Chaque rapport porte l'empreinte SHA-256 du corpus analysé, la version de la
méthode, les paramètres effectifs et les avertissements émis. Toutes les sources
d'aléa sont sous graine fixe : deux exécutions sur le même corpus produisent des
exports **identiques à l'octet près** (test dédié).

`METHOD_VERSION` doit être incrémentée à tout changement de formule ou de valeur
par défaut — seuls les rapports portant la même version sont comparables entre
eux.

## Transposition hors Wikipédia

La machinerie ne dépend pas de Wikipédia. Elle mesure la divergence entre
plusieurs descriptions d'un même objet, avec quantification de l'incertitude et
traçabilité. Applications directes :

- **Screening controverses / ESG** — divergence de cadrage d'un émetteur entre
  sources et juridictions, avec seuil de significativité plutôt qu'un score
  propriétaire non auditable.
- **Risque réputationnel de contrepartie** — l'indice de contestation appliqué à
  un flux documentaire signale l'instabilité narrative avant qu'elle n'atteigne
  le prix.
- **Test de message marketing multi-marchés** — mesurer si deux marchés
  reçoivent réellement le même cadrage produit, avec un test qui distingue
  l'écart réel du bruit d'échantillon.
- **Documentation de risque modèle** — la structure du bundle (empreinte
  d'entrée, version de méthode, paramètres effectifs, avertissements) est
  précisément ce qu'exige la revue d'un modèle intégrant des variables non
  structurées.

**Mise en garde explicite** : l'intensité d'édition lissée par EWMA *ressemble* à
une volatilité réalisée. Elle n'en est pas une — pas de rendement sous-jacent,
processus non stationnaire, échantillon endogène, aucune propriété de martingale.
Usage légitime : variable **ordinale** de classement et détection de rupture de
niveau. Usage illégitime : injection directe dans un modèle de risque calibré.
Voir [`docs/METHOD.md` §7](docs/METHOD.md).

## Ce que l'outil ne prouve pas

1. Ce qui n'est pas lié n'est pas mesuré — cadrage structurel ≠ cadrage sémantique.
2. Les pondérations de section sont **posées, pas mesurées**. Toute conclusion
   doit survivre à leur neutralisation.
3. Wikipédia n'est pas l'opinion publique. Un écart entre éditions documente un
   écart entre **communautés éditoriales**.
4. L'absence totale d'article n'est pas mesurée — le silence le plus fort est
   invisible dans le rapport.
5. Un écart de cadrage n'est pas un mensonge ; une contestation éditoriale n'est
   pas une erreur factuelle.

Liste complète et hiérarchisée : [`docs/METHOD.md` §9](docs/METHOD.md).

## Origine

Le dépôt contenait un script de six lignes (`import wikipediaapi.py`) appelant
`wikipedia.set_lang("ru")` puis demandant la page
`Північноатланти́чний алья́нс` — un titre **ukrainien**, qui n'existe pas sur
l'édition russophone. Le script échouait donc à l'exécution. Son intention est
reprise, corrigée et étendue par `prisme collect`, qui résout les titres via les
liens de site Wikidata plutôt que par saisie manuelle — ce qui rend ce type
d'erreur structurellement impossible.

---

*DataOptimization.be — méthode documentée dans [`docs/METHOD.md`](docs/METHOD.md).*
