# Politique de sécurité

## Versions maintenues

Seule la dernière version publiée reçoit des correctifs de sécurité. Mettez à jour régulièrement :
`git pull && sudo ./install.sh` ou `docker compose pull && docker compose up -d`.

## Signaler une vulnérabilité

**N'ouvrez pas de ticket public.** Utilisez le signalement privé de GitHub : onglet **Security** du dépôt →
**Report a vulnerability**. Indiquez :

- la version concernée et le type d'installation ;
- les étapes pour reproduire, et l'impact estimé ;
- si possible, une piste de correction.

Vous recevrez un accusé de réception sous 7 jours. Le correctif sera publié avant toute divulgation, en vous créditant
si vous le souhaitez.

## Modèle de sécurité (résumé)

- Authentification par email et mot de passe (scrypt). Sessions côté serveur, révocables, dans un cookie `HttpOnly` et `SameSite=Lax`.
- Rôles administrateur et membre. Les paramètres de l'entreprise, les utilisateurs et les réinitialisations sont réservés aux administrateurs.
- Protection CSRF par vérification de l'origine, CSP stricte, limitation des tentatives de connexion.
- Champs financiers des justificatifs chiffrés en AES-256-GCM.
- Le service systemd tourne sous un utilisateur dédié, avec un système de fichiers en lecture seule hors du dossier de données.

## Recommandations d'exploitation

- Exposez Caffein uniquement derrière un reverse proxy **HTTPS** et réglez `CAFFEIN_APP_URL` en `https://…`.
- Ne gardez **jamais** `CAFFEIN_DEMO=1` sur une instance qui contient de vraies données : le mode démo donne un accès
  administrateur sans mot de passe.
- Sauvegardez régulièrement (`caffein backup`) et conservez les archives hors du serveur : elles contiennent la clé de chiffrement.
- Protégez le fichier de configuration (`/etc/caffein/caffein.env`, mode 640) : il contient vos clés SMTP et IA.
