"""PRISME - mesure de la refraction narrative.

Un meme referent factuel (une entite Wikidata) est decrit par plusieurs
editions linguistiques de Wikipedia. PRISME mesure l'angle de refraction :
de combien la distribution de l'attention conceptuelle change selon la
langue, avec quelle incertitude, et a quel point chaque version est
contestee par ses propres contributeurs.

Le coeur de mesure est en Python standard, sans dependance externe.
"""

__version__ = "0.1.0"

# Identifiant de version des metriques. Tout changement de formule,
# de valeur par defaut ou de convention de comptage DOIT l'incrementer :
# les bundles de resultats le portent, ce qui rend comparables entre eux
# uniquement les rapports produits par la meme revision methodologique.
METHOD_VERSION = "1.0.0"
