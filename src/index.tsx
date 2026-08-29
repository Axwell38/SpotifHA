import {
  ButtonItem,
  PanelSection,
  PanelSectionRow,
  TextField,
  Focusable,
  staticClasses,
} from "@decky/ui";
import { callable, definePlugin } from "@decky/api";
import { useEffect, useState, VFC } from "react";
import { FaSpotify } from "react-icons/fa";

// -- Wrappers typés autour des méthodes du backend Python --------------------

const getStatus = callable<[], { has_client_id: boolean; is_authenticated: boolean; redirect_uri: string }>(
  "get_status"
);
const setClientId = callable<[client_id: string], { ok: boolean }>("set_client_id");
const startAuth = callable<[], { ok: boolean; error?: string }>("start_auth");
type PlaylistsResult = { ok: boolean; playlists?: { uri: string; name: string; image: string | null }[]; error?: string };
const getPlaylists = callable<[], PlaylistsResult>("get_playlists");
const playPause = callable<[], { ok: boolean }>("play_pause");
const nextTrack = callable<[], { ok: boolean }>("next_track");
const previousTrack = callable<[], { ok: boolean }>("previous_track");
const openUri = callable<[uri: string], { ok: boolean }>("open_uri");

type Playlist = { uri: string; name: string; image: string | null };

const Content: VFC = () => {
  const [hasClientId, setHasClientId] = useState(false);
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [clientIdInput, setClientIdInput] = useState("");
  const [redirectUri, setRedirectUri] = useState("");
  const [playlists, setPlaylists] = useState<Playlist[]>([]);
  const [loading, setLoading] = useState(false);

  const refreshStatus = async () => {
    const status = await getStatus();
    setHasClientId(status.has_client_id);
    setIsAuthenticated(status.is_authenticated);
    setRedirectUri(status.redirect_uri);
  };

  useEffect(() => {
    refreshStatus();
  }, []);

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
    return (
      <PanelSection title="Connexion Spotify">
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            onClick={async () => {
              setLoading(true);
              const res = await startAuth();
              setLoading(false);
              if (res.ok) await refreshStatus();
            }}
          >
            {loading ? "Connexion en cours…" : "Se connecter à Spotify"}
          </ButtonItem>
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
            <ButtonItem layout="inline" onClick={() => previousTrack()}>
              ⏮
            </ButtonItem>
            <ButtonItem layout="inline" onClick={() => playPause()}>
              ⏯
            </ButtonItem>
            <ButtonItem layout="inline" onClick={() => nextTrack()}>
              ⏭
            </ButtonItem>
          </Focusable>
        </PanelSectionRow>
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
