# Vidéo de démonstration : « Mes vues »

Une vidéo d'environ 57 secondes (1920 × 1080, 30 images/s), écrite en JSX avec [Remotion](https://www.remotion.dev),
qui montre le prototype « Mes vues » : un tableau de bord qui se compose en langage naturel
(voir [`../tableau-de-bord-ia.md`](../tableau-de-bord-ia.md)).

## Ce que montre la vidéo

1. **Titre** : « Caffein · Mes vues — Votre tableau de bord, à portée de mots ».
2. **Composer** : la page vide, la demande « Montre-moi mon chiffre d'affaires par mois et mes factures impayées »
   se tape dans la barre ; le graphique du chiffre d'affaires (12 mois) et le tableau des factures à encaisser
   apparaissent, avec « Compris : voici votre vue. » et le badge « Analyse locale ».
3. **Ajouter** : « Ajoute le total à encaisser et mes dépenses par catégorie cette année » ajoute la carte
   « À encaisser » et le graphique des dépenses.
4. **Retirer** : « Enlève les impayés » retire le tableau, la grille se réorganise.
5. **Lecture seule** : « Change l'échéance de la facture 14 au 30 » est refusé (message orange), rien ne change :
   l'IA ne modifie jamais les données.
6. **Enregistrer** : la vue est enregistrée sous « Pilotage mensuel » ; elle se recharge sans rappeler l'IA.
7. **Comment ça marche** : demande → IA ou analyse locale → description JSON (catalogue fermé) → validation →
   données calculées sur le serveur → affichage. L'IA ne voit jamais les chiffres.
8. **La suite** : les quatre étapes du plan (lecture seule, vues enrichies, formulaires préremplis,
   actions avec confirmation), puis « Caffein — logiciel libre (AGPL-3.0) ».

L'interface est redessinée dans la vidéo avec les couleurs, polices (DM Sans, JetBrains Mono), icônes (lucide-react)
et textes de l'application ; elle n'importe pas le code du frontend.

## Les chiffres

Les montants, libellés et messages viennent de `src/data.json` : ce sont les réponses réelles de
`POST /api/dashboards/compose` sur l'instance de démonstration (connexion par `POST /api/auth/demo`),
réduites à ce qu'utilise la vidéo. Rien n'est inventé ; pour mettre la vidéo à jour, il suffit de remplacer ce fichier.

## Prévisualiser et produire la vidéo

Il faut Node.js 20 ou plus récent.

```bash
cd docs/video
npm ci
npm run studio   # prévisualisation interactive dans le navigateur
npm run render   # produit out/caffein-mes-vues.mp4 (H.264)
```

Remotion télécharge un Chromium headless au premier rendu. Pour utiliser un navigateur déjà installé, ajoutez
`-- --browser-executable=/chemin/vers/chrome`. Pour une image fixe : `npx remotion still src/index.jsx MesVues out/image.png --frame=370`.

Le dossier `out/` et `node_modules/` sont ignorés par git.

## Fichiers

- `src/index.jsx` : point d'entrée (polices, `registerRoot`).
- `src/Root.jsx` : la composition `MesVues`.
- `src/MesVues.jsx` : la vidéo, découpée en scènes (titre, démonstration, explication, feuille de route, fin).
- `src/data.json` : les données de l'instance de démonstration.

Remotion est distribué sous sa propre licence (gratuite pour les particuliers et les petites structures) :
voir [remotion.dev/license](https://www.remotion.dev/license).
