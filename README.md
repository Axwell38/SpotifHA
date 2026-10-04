# SpotifHA

Contrôle et navigue dans Spotify (lecture, recherche, playlists) depuis le Quick Access Menu (QAM) du Steam Deck, pour le Spotify installé localement sur le Deck.

## Installation

1. Installe le plugin via Decky Loader (ou copie ce dossier dans `~/homebrew/plugins/SpotifHA` puis recharge Decky).
2. Ouvre le panneau SpotifHA dans le QAM.

## Configuration (à faire une seule fois, par utilisateur)

Chaque utilisateur doit créer **son propre Client ID Spotify**. C'est obligatoire : Spotify limite le nombre d'utilisateurs par app en mode développement, donc un Client ID unique partagé par toute la communauté serait vite bloqué.

1. Dans le panneau, clique sur **"Ouvrir le dashboard développeur Spotify"** (ça ouvre `developer.spotify.com/dashboard/create` dans ton navigateur).
2. Crée une app (nom/description libres).
3. Dans les paramètres de l'app, ajoute exactement la **Redirect URI** affichée dans le panneau SpotifHA (`http://127.0.0.1:8069/callback`).
4. Copie le **Client ID** de ton app Spotify et colle-le dans le champ du panneau, puis clique **"Enregistrer"**.
5. Clique **"Se connecter à Spotify"**. Le panneau affiche un lien à copier.
6. **Important** : Steam ne peut pas afficher la page de connexion Spotify (son navigateur intégré ne supporte pas le reCAPTCHA de Spotify). Passe en **Mode Bureau** (Steam → Mode Bureau), ouvre **Firefox**, et colle le lien copié. Connecte-toi avec le **même compte Spotify** que celui utilisé par l'appli Spotify installée sur le Deck.
7. Une fois connecté, reviens sur le Deck (Mode Jeu) : le panneau QAM se met à jour automatiquement.

## Fonctionnalités

- Pochette, artiste, titre du morceau en cours (lu directement depuis l'appli Spotify locale via MPRIS/DBus — aucune lecture via l'API Web).
- Précédent / Lecture-Pause / Suivant.
- Recherche de titres et de playlists (via l'API Web Spotify).
- Page "Playlists" séparée listant tes playlists.

## Limitation connue : playlists affichées

**Seules les playlists que tu as toi-même créées apparaissent** dans la page "Playlists". Ce n'est pas un bug du plugin : depuis le changement de l'API Web Spotify de novembre 2024, les apps en **mode développement** (donc toute app créée via un Client ID personnel — c'est le cas de chaque utilisateur de SpotifHA) ne reçoivent plus, via `/me/playlists`, les playlists "Spotify-owned" ou suivies (Discover Weekly, Release Radar, daylist, playlists créées par d'autres utilisateurs que tu suis).

L'appli Spotify Desktop, elle, voit tout car elle utilise une API interne privée à laquelle les apps tierces n'ont pas accès. Cette restriction est appliquée côté serveur Spotify et ne peut pas être contournée depuis le plugin.

Sources :
- https://github.com/LargeModGames/spotatui/issues/640
- https://github.com/LargeModGames/spotatui/pull/641
- https://community.spotify.com/t5/Spotify-for-Developers/Current-User-s-Playlist-doesn-t-list-Spotify-owned-playlists-e-g/td-p/6624238

## Dépannage

- **"Invalid limit" sur une recherche** : Spotify plafonne les apps en mode développement à 10 résultats par type sur `/v1/search`. Le plugin utilise déjà `limit=10`.
- **La page de connexion Spotify reste noire dans Steam** : normal, utilise Firefox en Mode Bureau comme décrit ci-dessus, jamais le navigateur intégré de Steam.
- **Logs** : `journalctl -b | grep "SpotifHA:"` affiche tous les messages du plugin (recherche, auth, erreurs MPRIS, etc.).
