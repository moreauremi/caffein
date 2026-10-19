# Animation de présentation de Caffein

Une animation de 35 secondes (16:9) qui présente Caffein : un ERP libre et open source, où une IA fait les trucs
pénibles à votre place, mais où tout se fait aussi sans elle. Écrite en JSX, avec React seul, sans autre dépendance.

## La voir

Téléchargez [`apercu.html`](apercu.html) (bouton « Download raw file » sur GitHub) et ouvrez-le dans votre navigateur.
Le fichier contient tout : il n'y a rien à installer.

Contrôles sous l'animation : lecture et pause (aussi avec la barre d'espace), rejouer, timeline cliquable.

## L'exporter en MP4

Cliquez sur **MP4** sous l'animation. Elle est rendue image par image en **1920 × 1080, 30 images/s**, encodée par le
navigateur, puis téléchargée sous le nom `caffein-presentation.mp4`. Rien n'est envoyé sur un serveur. Gardez l'onglet
ouvert pendant l'export ; comptez une à trois minutes selon l'ordinateur.

| Navigateur | Résultat |
|---|---|
| Chrome, Edge (récents) | MP4 en **H.264** : se lit partout (QuickTime, téléphones, réseaux sociaux) |
| Chromium sans H.264 (certaines distributions Linux) | MP4 en **VP9** : se lit dans Chrome, Firefox et VLC, pas dans QuickTime |
| Safari, Firefox | non garantis : si l'export échoue, un message l'indique ; utilisez alors Chrome ou Edge |

Les polices (DM Sans, Instrument Serif, JetBrains Mono) sont chargées depuis Google Fonts : sans connexion, l'animation
et l'export utilisent les polices du système.

## Le contenu

| Temps | Scène |
|---|---|
| 0 – 4 s | le logo arrive lettre par lettre : « L'ERP libre et modulaire des petites entreprises » |
| 4 – 9 s | les trucs chiants (relances, justificatifs, TVA, URSSAF…) tombent et s'empilent |
| 9 – 15 s | l'IA s'en charge : un devis complet à partir d'une seule phrase |
| 15 – 21 s | justificatifs classés tout seuls, relances rédigées, « Mes vues » à la demande |
| 21 – 26 s | et sans IA ? On coupe l'assistant, le devis se remplit à la main, le serveur calcule |
| 26 – 31 s | 100 % libre : `git clone`, `docker compose up -d`, les 13 modules |
| 31 – 35 s | « Libre. Auto-hébergé. Avec ou sans IA. » et l'adresse du dépôt |

Les textes et les exemples suivent les fonctionnalités décrites dans le [README](../../README.md).

## L'utiliser dans une page React

```jsx
import CaffeinPromo from './CaffeinPromo.jsx'

<CaffeinPromo />                                   // lecture automatique, contrôles et bouton MP4
<CaffeinPromo loop showControls={false} />          // en boucle, sans contrôles (écran d'accueil, salon)
<CaffeinPromo time={12.5} showControls={false} />   // image figée à 12,5 s
```

Toute l'animation est calculée à partir d'un seul temps `t` : chaque image est reproductible, ce qui permet la timeline
et l'export image par image. Les couleurs reprennent celles de l'interface (`frontend/src/index.css`) et le logo vient
de [`docs/logo/`](../logo/).

## La modifier

Modifiez [`CaffeinPromo.jsx`](CaffeinPromo.jsx), puis reconstruisez `apercu.html` (depuis la racine du dépôt) :

```bash
cd frontend && npm ci && cd ..     # une fois : fournit React
node docs/presentation/build.mjs
```

## Fichiers

- `CaffeinPromo.jsx` : l'animation, ses contrôles et l'export MP4 (encodage WebCodecs et écriture du fichier MP4,
  sans bibliothèque).
- `apercu.jsx` : le point d'entrée de l'aperçu.
- `apercu.html` : l'aperçu prêt à ouvrir, généré par `build.mjs`.
- `build.mjs` : reconstruit `apercu.html`.

Une autre vidéo, la démonstration de « Mes vues » (Remotion), est dans [`../video/`](../video/).
