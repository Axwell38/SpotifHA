import {
  ButtonItem,
  DialogButton,
  PanelSection,
  PanelSectionRow,
  TextField,
  Focusable,
  staticClasses,
} from "@decky/ui";
import { callable, definePlugin } from "@decky/api";
import { useEffect, useState, VFC } from "react";
import { FaSpotify, FaStepBackward, FaStepForward, FaPlayCircle } from "react-icons/fa";

// -- Wrappers typés autour des méthodes du backend Python --------------------

const getStatus = callable<[], { has_client_id: boolean; is_authenticated: boolean; redirect_uri: string }>(
  "get_status"
);
const setClientId = callable<[client_id: string], { ok: boolean }>("set_client_id");
const startAuth = callable<[], { ok: boolean; auth_url?: string; error?: string }>("start_auth");
type PlaylistsResult = { ok: boolean; playlists?: { uri: string; name: string; image: string | null }[]; error?: string };
const getPlaylists = callable<[], PlaylistsResult>("get_playlists");
const playPause = callable<[], { ok: boolean }>("play_pause");
const nextTrack = callable<[], { ok: boolean }>("next_track");
const previousTrack = callable<[], { ok: boolean }>("previous_track");
const openUri = callable<[uri: string], { ok: boolean }>("open_uri");
type SearchResult = {
  ok: boolean;
  tracks?: { uri: string; name: string; artist: string }[];
  playlists?: { uri: string; name: string }[];
  error?: string;
};
const search = callable<[query: string], SearchResult>("search");

type Playlist = { uri: string; name: string; image: string | null };

const Content: VFC = () => {
  const [hasClientId, setHasClientId] = useState(false);
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [clientIdInput, setClientIdInput] = useState("");
  const [redirectUri, setRedirectUri] = useState("");
  const [playlists, setPlaylists] = useState<Playlist[]>([]);
  const [loading, setLoading] = useState(false);
  const [authUrl, setAuthUrl] = useState("");
  const [copied, setCopied] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<SearchResult | null>(null);
  const [searching, setSearching] = useState(false);

  const refreshStatus = async () => {
    const status = await getStatus();
    setHasClientId(status.has_client_id);
    setIsAuthenticated(status.is_authenticated);
    setRedirectUri(status.redirect_uri);
  };

  useEffect(() => {
    refreshStatus();
  }, []);

  // Une fois qu'un lien de connexion a été généré, on vérifie toutes les
  // 3 secondes si la connexion a abouti côté backend (le serveur local
  // attend la redirection en arrière-plan pendant 10 minutes).
  useEffect(() => {
    if (!authUrl || isAuthenticated) return;
    const interval = setInterval(async () => {
      const status = await getStatus();
      if (status.is_authenticated) {
        setIsAuthenticated(true);
        setAuthUrl("");
      }
    }, 3000);
    return () => clearInterval(interval);
  }, [authUrl, isAuthenticated]);

  useEffect(() => {
    if (isAuthenticated) {
      setLoading(true);
      getPlaylists()
        .then((res) => {
          if (res.ok && res.playlists) setPlaylists(res.playlists);
        })
        .finally(() => setLoading(false));
    }
  }, [isAuthenticated]);

  // -- Étape 1 : pas encore de Client ID -------------------------------------
  if (!hasClientId) {
    return (
      <PanelSection title="Connexion Spotify">
        <PanelSectionRow>
          Crée une app sur le tableau de bord développeur Spotify, puis colle
          son Client ID ci-dessous.
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            onClick={() => window.open("https://developer.spotify.com/dashboard/create", "_blank")}
          >
            Ouvrir le tableau de bord Spotify
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          Redirect URI à coller dans le formulaire : {redirectUri || "http://127.0.0.1:8069/callback"}
        </PanelSectionRow>
        <PanelSectionRow>
          <TextField
            label="Client ID"
            value={clientIdInput}
            onChange={(e) => setClientIdInput(e.target.value)}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            disabled={!clientIdInput.trim()}
            onClick={async () => {
              await setClientId(clientIdInput.trim());
              await refreshStatus();
            }}
          >
            Enregistrer
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>
    );
  }

  // -- Étape 2 : Client ID connu, pas encore connecté avec un compte Spotify --
  if (!isAuthenticated) {
    if (!authUrl) {
      return (
        <PanelSection title="Connexion Spotify">
          <PanelSectionRow>
            <ButtonItem
              layout="below"
              onClick={async () => {
                setLoading(true);
                const res = await startAuth();
                setLoading(false);
                if (res.ok && res.auth_url) setAuthUrl(res.auth_url);
              }}
            >
              {loading ? "Génération du lien…" : "Se connecter à Spotify"}
            </ButtonItem>
          </PanelSectionRow>
        </PanelSection>
      );
    }

    // Lien généré : le login Spotify (protégé par reCAPTCHA) ne s'affiche
    // dans aucun navigateur embarqué de Steam, et Spotify interdit les
    // redirect URI en HTTP hors loopback (127.0.0.1) — la connexion doit
    // donc se faire dans un vrai navigateur (Firefox) SUR le Deck lui-même.
    return (
      <PanelSection title="Connexion Spotify">
        <PanelSectionRow>
          Fais cette étape depuis le Mode Bureau : Steam → bascule en mode
          Big Picture (icône en haut à droite du client Steam) pour retrouver
          ce panneau sans quitter le Bureau — le copier-coller vers Firefox
          fonctionne alors normalement.
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            onClick={async () => {
              try {
                await navigator.clipboard.writeText(authUrl);
                setCopied(true);
                setTimeout(() => setCopied(false), 2000);
              } catch {
                // le champ ci-dessous reste sélectionnable manuellement
              }
            }}
          >
            {copied ? "Copié !" : "Copier le lien"}
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <TextField value={authUrl} disabled />
        </PanelSectionRow>
        <PanelSectionRow>
          Colle-le ensuite dans Firefox (déjà présent sur le Bureau). En
          attente de connexion… reviens ici une fois connecté, cet écran
          passe automatiquement à la suite.
        </PanelSectionRow>
      </PanelSection>
    );
  }

  // -- Étape 3 : connecté — contrôles + playlists ------------------------------
  return (
    <>
      <PanelSection title="Lecture">
        <PanelSectionRow>
          <Focusable style={{ display: "flex", gap: "8px", justifyContent: "center" }}>
            <DialogButton
              style={{ width: "60px", minWidth: "60px", padding: "10px 0" }}
              onClick={() => previousTrack()}
            >
              <FaStepBackward />
            </DialogButton>
            <DialogButton
              style={{ width: "60px", minWidth: "60px", padding: "10px 0" }}
              onClick={() => playPause()}
            >
              <FaPlayCircle />
            </DialogButton>
            <DialogButton
              style={{ width: "60px", minWidth: "60px", padding: "10px 0" }}
              onClick={() => nextTrack()}
            >
              <FaStepForward />
            </DialogButton>
          </Focusable>
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title="Rechercher">
        <PanelSectionRow>
          <TextField
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            label="Titre, artiste, playlist…"
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            disabled={!searchQuery.trim()}
            onClick={async () => {
              setSearching(true);
              const res = await search(searchQuery.trim());
              setSearching(false);
              setSearchResults(res);
            }}
          >
            {searching ? "Recherche…" : "Rechercher"}
          </ButtonItem>
        </PanelSectionRow>
        {searchResults && searchResults.ok && (
          <>
            {(searchResults.playlists?.length ?? 0) === 0 &&
              (searchResults.tracks?.length ?? 0) === 0 && (
                <PanelSectionRow>Aucun résultat.</PanelSectionRow>
              )}
            {searchResults.playlists?.map((pl) => (
              <PanelSectionRow key={pl.uri}>
                <ButtonItem layout="below" onClick={() => openUri(pl.uri)}>
                  📁 {pl.name}
                </ButtonItem>
              </PanelSectionRow>
            ))}
            {searchResults.tracks?.map((t) => (
              <PanelSectionRow key={t.uri}>
                <ButtonItem layout="below" onClick={() => openUri(t.uri)}>
                  {t.name} — {t.artist}
                </ButtonItem>
              </PanelSectionRow>
            ))}
          </>
        )}
      </PanelSection>

      <PanelSection title="Tes playlists">
        {loading && <PanelSectionRow>Chargement…</PanelSectionRow>}
        {!loading && playlists.length === 0 && (
          <PanelSectionRow>Aucune playlist trouvée.</PanelSectionRow>
        )}
        {playlists.map((pl) => (
          <PanelSectionRow key={pl.uri}>
            <ButtonItem layout="below" onClick={() => openUri(pl.uri)}>
              {pl.name}
            </ButtonItem>
          </PanelSectionRow>
        ))}
      </PanelSection>
    </>
  );
};

export default definePlugin(() => {
  return {
    name: "SpotifHA",
    titleView: <div className={staticClasses.Title}>Spotify</div>,
    content: <Content />,
    icon: <FaSpotify />,
  };
});
