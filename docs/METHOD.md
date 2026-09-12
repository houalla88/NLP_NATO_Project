# Méthode

## 1. Le problème posé

Mesurer « la perception de l'OTAN sur Wikipédia en russe » suppose résolu ce qui
ne l'est pas : *comparé à quoi ?* Un score de sentiment sur un seul corpus n'a
pas d'échelle. Il n'existe pas de zéro absolu du cadrage.

Wikipédia offre une sortie à ce problème, et c'est ce qui fonde cet outil. Un
même référent factuel — identifié par un QID Wikidata, donc sans ambiguïté —
est décrit indépendamment par des dizaines de communautés éditoriales. Chaque
édition linguistique constitue une description alternative du même objet. Le
cadrage devient alors mesurable **en écart relatif** entre descriptions, ce qui
ne requiert aucun étalon absolu.

C'est le dispositif quasi-expérimental exploité par la littérature sur le biais
culturel dans Wikipédia (Hecht & Gergle 2010 ; Callahan & Herring 2011 ;
Bao *et al.* 2012 ; Massa & Scrinzi 2012). PRISME en reprend le principe et y
ajoute ce qui manque le plus souvent dans ce type de travail : la quantification
de l'incertitude, la correction du biais d'estimation, et un banc d'étalonnage.

## 2. La représentation : liens internes → QID Wikidata

Un article n'est pas traité comme du texte, mais comme un **graphe d'attention**.
Chaque lien interne pointe vers une page, et cette page porte un identifiant
Wikidata identique dans toutes les langues. Compter les QID cités par un article
produit une distribution de probabilité sur un espace conceptuel **neutre
linguistiquement**.

### Ce que cela évite

| Composant évité | Problème qu'il pose en comparaison multilingue |
|---|---|
| Traduction automatique | Qualité très inégale selon la paire de langues ; introduit son propre cadrage |
| Lemmatisation / segmentation | Performances hétérogènes ; le russe et le turc ne se segmentent pas comme l'anglais |
| Lexiques de sentiment | Ni la même couverture ni la même calibration d'une langue à l'autre. Comparer deux sorties de lexiques non étalonnés revient à comparer deux thermomètres gradués différemment |
| Plongements lexicaux multilingues | Boîte noire, non auditable, et versionnés hors du contrôle de l'analyste |

Aucun modèle de langue n'intervient dans la chaîne. La mesure est donc
reproductible à l'identique dans dix ans, à partir du seul corpus figé.

### Ce que cela coûte

On ne mesure que ce qui est **lié**. Un thème traité en prose sans lien interne
est invisible. La mesure porte sur le cadrage *structurel* — quels concepts
l'article rattache-t-il au sujet — et non sur la tonalité du texte. C'est un
objet plus étroit que « la perception », et nettement plus objectivable.

### Pondération structurelle

La position d'un concept dans l'article est prise en compte : le chapeau
introductif pèse 2,5, le corps 1,0, « Voir aussi » 0,3, les références 0,1.

**Ces coefficients sont une hypothèse, pas une mesure.** Ils sont exposés en
paramètre (`AnalysisConfig.section_weights`) pour qu'une analyse de sensibilité
puisse être conduite. Toute conclusion qui ne survivrait pas à leur mise à 1,0
doit être présentée comme conditionnelle à cette hypothèse.

## 3. La mesure de divergence

### Choix de la Jensen-Shannon

| Mesure | Symétrique | Finie sur support disjoint | Bornée | Retenue |
|---|---|---|---|---|
| Kullback-Leibler | non | non | non | ✗ |
| Jensen-Shannon | oui | oui | [0, 1] en base 2 | ✓ |
| Hellinger | oui | oui | [0, 1] | ✓ (contre-mesure) |

L'asymétrie de la KL est rédhibitoire ici : « le russe s'écarte de l'anglais »
et l'inverse donneraient deux chiffres différents. Son caractère infini sur
support disjoint l'est tout autant, puisque l'absence d'un concept d'un côté est
précisément le cas le plus intéressant.

La racine de la JSD est une métrique au sens mathématique (Endres & Schindelin
2003), ce qui autorise la projection par positionnement multidimensionnel sans
violer les hypothèses de la méthode. C'est sous cette forme, et sous elle seule,
que la carte 2D est construite.

### Correction du biais de sous-échantillonnage

L'estimateur par substitution de la JSD est **biaisé vers le haut**, et le biais
est loin d'être négligeable.

> Mesure effectuée sur l'implémentation : deux échantillons de 900 occurrences
> tirés de la **même** loi à queue lourde (100 concepts, Zipf α = 1,05)
> produisent une JSD plug-in moyenne de **0,057** alors que la valeur vraie est
> **0**.

Conséquence directe : un classement d'éditions établi sur l'estimateur naïf
classe en partie les **longueurs d'articles**. Une édition courte paraîtra
systématiquement plus divergente qu'une édition longue.

La cause est connue : l'entropie de Shannon étant concave, son estimateur par
substitution sous-estime l'entropie vraie d'environ (K−1)/2n nats (Miller 1955 ;
synthèse dans Paninski 2003). Comme

    JSD = H(M) − [H(P) + H(Q)]/2     avec M = (P+Q)/2

les trois termes sont biaisés mais pas de la même quantité, et le déséquilibre
laisse un résidu positif.

La correction de Miller-Madow est appliquée aux trois entropies, l'effectif
attribué au mélange étant celui qui reproduit sa variance réelle :

    n_M = 4 · n_a · n_b / (n_a + n_b)

soit 2n lorsque les deux éditions ont le même nombre d'occurrences.

**Effet mesuré : biais moyen ramené de 0,057 à 0,018 (−68 %).** La correction
est asymptotique au premier ordre en 1/n ; elle réduit fortement le biais sans
l'annuler. Le résidu est borné par le contrôle de justesse du banc.

## 4. L'incertitude

Deux dispositifs distincts, qui répondent à deux questions différentes.

### Dispersion (bootstrap)

« De combien ce chiffre bougerait-il si les deux articles étaient un autre
tirage de même longueur ? »

L'intervalle **n'est pas** un intervalle de couverture à 95 % de la valeur
vraie, et il serait malhonnête de le présenter comme tel. Rééchantillonner un
support déjà creux le creuse davantage : la distribution bootstrap de la JSD se
situe systématiquement **au-dessus** du point estimé, au point qu'un intervalle
percentile brut ne contient même pas sa propre estimation ponctuelle — constat
mesuré, pas supposé.

La construction retenue mesure la dispersion autour de la médiane bootstrap puis
la transplante sur le point estimé :

    borne_basse = θ̂ − (médiane* − quantile_bas*)
    borne_haute = θ̂ + (quantile_haut* − médiane*)

L'intervalle contient donc toujours l'estimation, et sa largeur est bien celle
de la variabilité d'échantillonnage.

### Significativité (permutation exacte)

« Cet écart dépasse-t-il ce qu'on obtiendrait sans aucune différence de
cadrage ? »

Les occurrences des deux éditions sont mises en commun puis redistribuées au
hasard en deux groupes conservant les effectifs réels. Sous l'hypothèse nulle
cette redistribution est équiprobable : la loi obtenue est donc **exactement**
celle de la statistique sous H₀, sans hypothèse paramétrique.

> **Incident de développement, conservé ici parce qu'il est instructif.** Une
> première version tirait les deux groupes dans la distribution mise en commun
> (bootstrap paramétrique) au lieu de permuter les occurrences réelles. Le banc
> d'étalonnage a mesuré un taux de faux positifs de **15,5 %** pour un seuil
> nominal de 5 % — soit environ trois fois trop de divergences déclarées
> significatives. Le passage à la permutation exacte ramène le taux à **0,045**.
> Sans le banc, cette erreur serait passée en production et aurait produit des
> conclusions à partir de bruit.

La p-valeur porte la correction de Davison & Hinkley (1997) : `(k+1)/(B+1)`,
qui interdit une p-valeur exactement nulle.

## 5. Concepts distinctifs

Méthode log-odds à prior de Dirichlet informatif (Monroe, Colaresi & Quinn 2008,
« Fightin' Words »).

Classer les concepts par simple écart de fréquence fait remonter en tête les
concepts **rares** : un QID vu une seule fois dans une seule édition obtient un
rapport de fréquences infini. Le classement mesure alors la taille de
l'échantillon, pas le cadrage.

Le prior, construit sur la distribution de fond avec une intensité α₀ = 500
occurrences virtuelles, régularise ces cas. Le score z rapporte le log-odds à
son écart-type : un concept rare doit être très déséquilibré pour atteindre le
score d'un concept fréquent modérément déséquilibré.

Transposition : Monroe *et al.* travaillent sur des mots, on travaille sur des
QID. La structure statistique est identique et la formule ne demande aucune
adaptation. L'avantage est que le « vocabulaire » est déjà désambiguïsé et
neutre linguistiquement.

## 6. Silences structurels

Un concept présent dans au moins deux éditions, y pesant au moins 0,5 % de
l'attention, et **totalement absent** d'une autre.

Les deux seuils évitent de transformer du hasard rédactionnel en constat.
L'absence d'un lien n'est pas l'absence d'un sujet : une édition peut traiter un
thème en prose sans jamais le lier. Le silence mesuré est *structurel*, ce qui
est un signal plus faible qu'une absence sémantique mais nettement plus
objectivable.

## 7. Contestation éditoriale

### Détection des retours arrière

MediaWiki expose l'empreinte SHA-1 du contenu de chaque révision. Si une
révision reproduit exactement l'empreinte d'une révision antérieure, l'état du
texte a été restauré : c'est la définition opérationnelle du *revert d'identité*
employée dans la littérature (Sumi *et al.* 2011 ; Yasseri *et al.* 2012).

Définition volontairement stricte. Elle rate les annulations partielles et les
reformulations qui suppriment le même contenu sans restaurer le texte au
caractère près. Elle ne produit en revanche quasiment aucun faux positif : **le
taux mesuré est un plancher, il ne peut pas inventer du conflit.**

### Indice de revert mutuel

Adaptation de la mesure M de Yasseri *et al.* (2012). Formule implémentée :

    MRI = Σ sur les paires {a,b}  min(r_ab, r_ba) · max(N_a, N_b)  /  n_révisions

où `r_ab` est le nombre de fois où a a défait b, et `N_a` le nombre total
d'éditions de a.

Seules les paires **mutuelles** comptent, ce qui distingue un conflit d'une
patrouille anti-vandalisme, où le flux est à sens unique.

**Ce n'est pas la mesure M publiée au coefficient près** : Yasseri *et al.*
pondèrent en outre par le nombre d'éditeurs et traitent spécifiquement les
paires dominantes. L'indice est donc comparable entre éditions au sein d'une
même exécution PRISME, mais ne doit pas être confronté à des valeurs de M issues
de la littérature.

### Sur l'analogie financière — mise en garde

L'intensité d'édition lissée par EWMA (λ = 0,94) **ressemble** à une volatilité
réalisée. Elle n'en est pas une :

1. **Pas de rendement sous-jacent.** Une volatilité mesure la dispersion d'une
   variation de prix ; ici on mesure une fréquence d'événements. Le parallèle
   est morphologique, pas théorique.
2. **Processus non stationnaire et échantillon endogène.** L'attention
   médiatique crée simultanément l'événement et son édition.
3. **Aucune propriété de martingale n'est vérifiée**, donc aucune agrégation
   temporelle en racine du temps n'est justifiée.

Usage légitime : variable **ordinale** pour classer des entités entre elles à
date donnée, et détection de rupture de niveau. Usage illégitime : injection
directe dans un modèle de risque calibré.

## 8. Banc d'étalonnage

Un instrument qu'on ne peut pas étalonner ne vaut rien. Le banc
(`prisme calibrate`) génère des corpus dont la loi génératrice est connue —
donc dont la divergence vraie est calculable en forme close — et vérifie que la
mesure la retrouve.

| Contrôle | Ce qu'il empêche |
|---|---|
| Justesse (erreur absolue moyenne < 0,05) | Un biais systématique d'estimation |
| Intervalle contenant l'estimation | Un intervalle inexploitable en rapport |
| Taux de faux positifs ≤ 2α | **Déclarer significatif un écart inexistant** |
| Monotonie vs séparation injectée | Un classement d'éditions non fiable |
| Rappel des distinctifs ≥ 0,80 | Un classement de concepts dominé par le bruit |
| Détection des reverts = exacte | Une mesure de conflit fausse |

Le troisième est le plus important : c'est le mode de défaillance le plus
courant et le moins visible des analyses de corpus. C'est lui qui a détecté
l'erreur de test décrite en §4.

Le banc tourne en moins de quatre secondes et fait partie de la suite de tests :
une régression sur une formule échoue avant que les chiffres n'atteignent un
rapport.

## 9. Limites, dans l'ordre de leur importance

1. **Ce qui n'est pas lié n'est pas mesuré.** Le cadrage structurel n'est pas le
   cadrage sémantique.
2. **Les pondérations de section sont posées, pas mesurées.** Toute conclusion
   doit survivre à leur neutralisation.
3. **Wikipédia n'est pas l'opinion publique.** Les contributeurs sont une
   population très particulière — fortement masculine, technophile, non
   représentative. Un écart entre l'édition russophone et l'édition anglophone
   documente un écart entre deux communautés éditoriales, **pas** entre deux
   populations nationales. L'édition russophone est d'ailleurs lue et écrite
   bien au-delà de la Russie.
4. **L'absence d'article n'est pas mesurée.** Seules les éditions possédant un
   article entrent dans la comparaison. Le silence le plus fort — ne pas avoir
   d'article du tout — est invisible dans le rapport.
5. **Un écart de cadrage n'est pas un mensonge**, et une contestation éditoriale
   n'est pas une erreur factuelle.
6. **Le biais résiduel n'est pas nul.** La correction de Miller-Madow est
   asymptotique. Sur des articles très courts (< 25 occurrences pondérées), le
   rapport émet un avertissement explicite.
7. **La comparaison entre entités différentes n'est pas calibrée.** Les valeurs
   de JSD sont comparables entre paires d'éditions d'une même entité ; les
   comparer d'une entité à l'autre suppose des espaces conceptuels de taille
   comparable, ce que rien ne garantit.

## 10. Références

- Bao, P., Hecht, B., Carton, S., Quaderi, M., Horn, M., & Gergle, D. (2012).
  *Omnipedia: bridging the Wikipedia language gap.* CHI '12.
- Callahan, E. S., & Herring, S. C. (2011). *Cultural bias in Wikipedia content
  on famous persons.* JASIST, 62(10).
- Davison, A. C., & Hinkley, D. V. (1997). *Bootstrap Methods and their
  Application.* Cambridge University Press.
- Endres, D. M., & Schindelin, J. E. (2003). *A new metric for probability
  distributions.* IEEE Trans. Inf. Theory, 49(7).
- Entman, R. M. (1993). *Framing: Toward Clarification of a Fractured Paradigm.*
  Journal of Communication, 43(4).
- Hecht, B., & Gergle, D. (2010). *The Tower of Babel meets Web 2.0.* CHI '10.
- Kachitvichyanukul, V., & Schmeiser, B. W. (1988). *Binomial random variate
  generation.* Communications of the ACM, 31(2).
- Lin, J. (1991). *Divergence measures based on the Shannon entropy.* IEEE
  Trans. Inf. Theory, 37(1).
- Massa, P., & Scrinzi, F. (2012). *Manypedia: comparing language points of view
  of Wikipedia communities.* WikiSym '12.
- Miller, G. A. (1955). *Note on the bias of information estimates.*
- Monroe, B. L., Colaresi, M. P., & Quinn, K. M. (2008). *Fightin' Words.*
  Political Analysis, 16(4).
- Paninski, L. (2003). *Estimation of entropy and mutual information.* Neural
  Computation, 15(6).
- Sumi, R., Yasseri, T., Rung, A., Kornai, A., & Kertész, J. (2011). *Edit wars
  in Wikipedia.* IEEE SocialCom/PASSAT.
- Torgerson, W. S. (1952). *Multidimensional scaling: I. Theory and method.*
  Psychometrika, 17.
- Yasseri, T., Sumi, R., Rung, A., Kornai, A., & Kertész, J. (2012). *Dynamics of
  conflicts in Wikipedia.* PLoS ONE, 7(6).

> **Sur la vérification de ces références.** Elles sont citées de mémoire. La
> session de développement n'avait pas d'accès sortant permettant de les
> confronter à une base bibliographique. Les vérifier (DOI, pagination) avant
> toute publication externe ou tout usage réglementaire.
