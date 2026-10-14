# Tableau de bord à la demande (« Mes vues »)

Plan et architecture du prototype, étape 1 de la piste « tout ce que l'utilisateur veut faire est à portée de mots ».

## L'idée

L'utilisateur écrit ce qu'il veut voir, et la page se compose :

> « Montre-moi mon chiffre d'affaires par mois et mes factures impayées »
> → un graphique et un tableau s'affichent.
>
> « Ajoute mes dépenses par catégorie sur l'année » → une carte de plus.
> « Enlève les impayés » → la carte disparaît.
> « Enregistrer la vue » → la vue revient en un clic, sans rappeler l'IA.

## Le principe : l'IA assemble, elle ne fabrique pas

L'IA ne génère **ni code, ni SQL, ni HTML**. Elle choisit des briques dans un catalogue fermé et renvoie une
**description de l'écran** en JSON, que le serveur valide avant d'afficher quoi que ce soit.

```
« montre-moi mon CA par mois »
        │
        ▼
  IA (Claude) ou analyse locale  ──▶  description : {"widgets": [{"source": "revenue_by_month", "visual": "bar", …}]}
        │                                   │
        │   ne reçoit que la demande,       ▼
        │   le catalogue et la vue    validation stricte (sources, visuels, paramètres connus, 8 cartes au plus)
        │   actuelle : jamais les           │
        │   chiffres de l'entreprise        ▼
        │                             calcul des données, en local, par des fonctions fixes (services.py)
        │                                   │
        └──────────────────────────────────▶▼
                                      React affiche avec les composants existants (StatCard, BarsChart, tableaux)
```

Pourquoi :

- **Prévisible** : une même vue s'affiche toujours de la même façon ; une description invalide est refusée, pas devinée.
- **Sûr** : l'IA ne peut ni lire ni modifier les données. Elle ne voit jamais les montants, les clients ou les documents :
  seulement la demande, la liste des briques et la vue en cours.
- **Économique** : choisir des briques est une petite tâche. Une vue enregistrée se recharge sans aucun appel à l'IA.
- **Hors ligne** : sans clé Anthropic, une analyse locale par mots-clés compose la vue (comme pour les autres fonctions
  IA de Caffein). Le logiciel reste entièrement utilisable.

## Le catalogue (étape 1 : lecture seule)

| Source | Ce qu'elle montre | Visuels | Paramètres |
|---|---|---|---|
| `kpi` | un chiffre clé : à encaisser, en retard, encaissé ce mois, CA de l'année, devis en attente, solde de TVA, temps gagné | carte | `metric` |
| `revenue_by_month` | chiffre d'affaires HT facturé et encaissé, mois par mois | barres, tableau | `period` (6 ou 12 mois, année) |
| `revenue_by_client` | chiffre d'affaires HT par client | barres, tableau | `period`, `limit` |
| `unpaid_invoices` | factures à encaisser, les plus en retard d'abord | tableau | `only_overdue`, `limit` |
| `expenses_by_category` | dépenses HT par catégorie (justificatifs classés) | barres, tableau | `period` |
| `vat_by_month` | TVA collectée et déductible, mois par mois | barres, tableau | `period` |
| `pending_quotes` | devis en attente de réponse | tableau | `limit` |
| `deadlines` | prochaines échéances TVA et URSSAF | liste | — |

Chaque source est une fonction Python qui s'appuie sur la logique métier existante (`services.py`) : mêmes règles de
calcul que le reste de l'application, mêmes données déchiffrées côté serveur.

## Ce qui est construit

**Serveur**

- `backend/caffein/dashboard.py` : le catalogue, la validation des descriptions, le calcul des données, l'analyse locale
  par mots-clés, et les vues enregistrées.
- `backend/caffein/ai.py` : `compose_dashboard()`, sortie structurée avec un schéma dont les sources et les visuels sont
  des énumérations fermées ; repli sur l'analyse locale si Claude est indisponible.
- Migration 3 : table `dashboard_views` (vues enregistrées, propres à chaque utilisateur).
- API (utilisateur connecté) :
  - `POST /api/dashboards/compose` : demande + vue actuelle → nouvelle vue, avec ses données ;
  - `POST /api/dashboards/render` : vue → données (pour recharger sans IA) ;
  - `GET/POST /api/dashboards`, `GET/PUT/DELETE /api/dashboards/{id}` : vues enregistrées. Un utilisateur ne voit que
    les siennes.

**Interface**

- Page « Mes vues » (`/vues`) : barre de demande avec exemples, grille de cartes, retrait d'une carte d'un clic,
  vues enregistrées en onglets, message « Compris : … » et badge IA ou analyse locale.
- Rendu avec les composants existants (cartes de statistiques, graphiques à barres avec vue tableau), thème clair et
  sombre, français et anglais.

**Garde-fous**

- Demande limitée à 500 caractères, 8 cartes au plus par vue, 30 vues enregistrées au plus par utilisateur.
- Toute description passe par `validate_spec()` : source inconnue, visuel non prévu ou paramètre hors liste sont écartés.
- Les textes affichés (titres choisis par l'IA ou l'utilisateur) sont du texte, jamais du HTML.

## Les étapes suivantes

1. **Lecture seule** (ce prototype) : « montre-moi… » ne fait qu'afficher, donc aucun risque.
2. **Vues enregistrées enrichies** : réorganiser les cartes, épingler une vue sur l'accueil, partager une vue entre
   utilisateurs.
3. **Formulaires préremplis** : « change l'échéance de la facture 14 au 30 » ouvre le vrai formulaire de la facture,
   prérempli ; l'utilisateur vérifie et enregistre. L'IA ne fait que remplir.
4. **Actions complètes avec confirmation** : relancer, dupliquer, créer un avoir. Les règles métier passent avant l'IA :
   une facture émise ne se modifie pas et ne se supprime pas (« supprime cette facture » → « je te prépare un avoir »).

## Tests

`backend/tests/test_dashboard.py` : validation des descriptions (sources, visuels et paramètres inconnus écartés),
analyse locale sur des demandes réelles (composer, ajouter, retirer, période), calcul de chaque source sur les données
de démonstration, parcours complet par l'API (composer, enregistrer, recharger, supprimer) et isolement des vues entre
utilisateurs.
