import {
  PanelSection,
  PanelSectionRow,
  ButtonItem,
  DialogButton,
  TextField,
  Focusable,
  Navigation,
  staticClasses,
} from "@decky/ui";
import { callable, definePlugin, routerHook } from "@decky/api";
import { useEffect, useState, VFC } from "react";
import { FaSpotify } from "react-icons/fa";
import { IoPlaySkipBack, IoPlayCircle, IoPauseCircle, IoPlaySkipForward } from "react-icons/io5";

// ---------- Backend calls ----------

type StatusResult = { has_client_id: boolean; is_authenticated: boolean; redirect_uri: string };
type StartAuthResult = { ok: boolean; auth_url?: string; error?: string };
type PlaylistsResult = { ok: boolean; playlists?: { uri: string; name: string; image: string | null }[]; error?: string };
type SearchResult = {
  ok: boolean;
  tracks?: { uri: string; name: string; artist: string }[];
  playlists?: { uri: string; name: string }[];
  error?: string;
};
type PlaybackState = {
  ok: boolean;
  status?: string | null;
  title?: string | null;
  artist?: string | null;
  art_url?: string | null;
  error?: string;
};

const getStatus = callable<[], StatusResult>("get_status");
const setClientId = callable<[string], { ok: boolean }>("set_client_id");
const startAuth = callable<[], StartAuthResult>("start_auth");
const getPlaylists = callable<[], PlaylistsResult>("get_playlists");
const search = callable<[string], SearchResult>("search");
const playPause = callable<[], { ok: boolean }>("play_pause");
const nextTrack = callable<[], { ok: boolean }>("next_track");
const previousTrack = callable<[], { ok: boolean }>("previous_track");
const openUri = callable<[string], { ok: boolean }>("open_uri");
const getPlaybackState = callable<[], PlaybackState>("get_playback_state");

const PLAYLISTS_ROUTE = "/spotifha-playlists";

// ---------- Now playing block (pochette + artiste + titre) ----------

const NowPlaying: VFC<{ state: PlaybackState | null }> = ({ state }) => {
  const title = state?.title || "Aucune lecture en cours";
  const artist = state?.artist || "";
  const art = state?.art_url || null;

  return (
    <PanelSectionRow>
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", width: "100%" }}>
        <div
          style={{
            width: "140px",
            height: "140px",
            borderRadius: "6px",
            overflow: "hidden",
            background: "#222",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            marginBottom: "8px",
          }}
        >
          {art ? (
            <img src={art} alt="cover" style={{ width: "100%", height: "100%", objectFit: "cover" }} />
          ) : (
            <FaSpotify size={48} color="#1DB954" />
          )}
        </div>
        <div style={{ fontSize: "13px", opacity: 0.8, textAlign: "center" }}>{artist}</div>
        <div style={{ fontSize: "15px", fontWeight: 600, textAlign: "center" }}>{title}</div>
      </div>
    </PanelSectionRow>
  );
};

// ---------- Playback controls row ----------

const PlaybackControls: VFC<{ isPlaying: boolean; onAfterAction: () => void }> = ({ isPlaying, onAfterAction }) => {
  const btnStyle = {
    width: "60px",
    minWidth: "60px",
    padding: "10px 0",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
  };
  const iconSize = 26;

  const handle = async (action: () => Promise<{ ok: boolean }>) => {
    await action();
    onAfterAction();
  };

  return (
    <PanelSectionRow>
      <Focusable style={{ display: "flex", justifyContent: "center", gap: "8px", width: "100%" }}>
        <DialogButton style={btnStyle} onClick={() => handle(previousTrack)}>
          <IoPlaySkipBack size={iconSize} />
        </DialogButton>
        <DialogButton style={btnStyle} onClick={() => handle(playPause)}>
          {isPlaying ? <IoPauseCircle size={iconSize} /> : <IoPlayCircle size={iconSize} />}
        </DialogButton>
        <DialogButton style={btnStyle} onClick={() => handle(nextTrack)}>
          <IoPlaySkipForward size={iconSize} />
        </DialogButton>
      </Focusable>
    </PanelSectionRow>
  );
};

// ---------- Separate "Playlists" page ----------

const PlaylistsPage: VFC = () => {
  const [playlists, setPlaylists] = useState<PlaylistsResult["playlists"]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      setLoading(true);
      const res = await getPlaylists();
      if (res.ok) {
        setPlaylists(res.playlists || []);
        setError(null);
      } else {
        setError(res.error || "unknown_error");
      }
      setLoading(false);
    })();
  }, []);

  return (
    <div style={{ marginTop: "40px", padding: "0 10px" }}>
      <PanelSection title="Tes playlists">
        {loading && <PanelSectionRow>Chargement...</PanelSectionRow>}
        {!loading && error && <PanelSectionRow>Erreur: {error}</PanelSectionRow>}
        {!loading && !error && (playlists?.length ?? 0) === 0 && (
          <PanelSectionRow>Aucune playlist trouvee.</PanelSectionRow>
        )}
        {!loading &&
          playlists?.map((p) => (
            <PanelSectionRow key={p.uri}>
              <ButtonItem layout="below" onClick={() => openUri(p.uri)}>
                {p.name}
              </ButtonItem>
            </PanelSectionRow>
          ))}
      </PanelSection>
    </div>
  );
};

// ---------- Main QAM panel ----------

const Content: VFC = () => {
  const [status, setStatus] = useState<StatusResult | null>(null);
  const [clientIdInput, setClientIdInput] = useState("");
  const [authUrl, setAuthUrl] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<SearchResult | null>(null);
  const [searching, setSearching] = useState(false);
  const [playbackState, setPlaybackState] = useState<PlaybackState | null>(null);

  const refreshPlayback = async () => {
    try {
      const res = await getPlaybackState();
      setPlaybackState(res);
    } catch {
      // on retentera au prochain tick
    }
  };

  useEffect(() => {
    if (!status?.is_authenticated) return;
    refreshPlayback();
    const id = setInterval(refreshPlayback, 3000);
    return () => clearInterval(id);
  }, [status?.is_authenticated]);

  const refreshStatus = async () => {
    const s = await getStatus();
    setStatus(s);
    return s;
  };

  useEffect(() => {
    refreshStatus();
  }, []);

  // Poll tant qu'on attend la connexion OAuth
  useEffect(() => {
    if (!authUrl) return;
    const id = setInterval(async () => {
      const s = await refreshStatus();
      if (s.is_authenticated) {
        setAuthUrl(null);
        clearInterval(id);
      }
    }, 3000);
    return () => clearInterval(id);
  }, [authUrl]);

  const handleSaveClientId = async () => {
    if (!clientIdInput.trim()) return;
    await setClientId(clientIdInput.trim());
    await refreshStatus();
  };

  const handleStartAuth = async () => {
    const res = await startAuth();
    if (res.ok && res.auth_url) {
      setAuthUrl(res.auth_url);
    }
  };

  const handleSearch = async () => {
    const q = searchQuery.trim();
    if (!q) return;
    setSearching(true);
    try {
      const res = await search(q);
      setSearchResults(res);
    } finally {
      setSearching(false);
    }
  };

  const openPlaylistsPage = () => {
    Navigation.Navigate(PLAYLISTS_ROUTE);
    Navigation.CloseSideMenus();
  };

  if (!status) {
    return (
      <PanelSection>
        <PanelSectionRow>Chargement...</PanelSectionRow>
      </PanelSection>
    );
  }

  // Etape 1 : pas de Client ID enregistre
  if (!status.has_client_id) {
    return (
      <PanelSection title="Configuration Spotify">
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            onClick={() => window.open("https://developer.spotify.com/dashboard/create", "_blank")}
          >
            Ouvrir le dashboard développeur Spotify
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          Crée une app Spotify, puis ajoute cette Redirect URI exactement :
        </PanelSectionRow>
        <PanelSectionRow>
          <TextField value={status.redirect_uri} disabled />
        </PanelSectionRow>
        <PanelSectionRow>
          <TextField
            label="Client ID"
            value={clientIdInput}
            onChange={(e) => setClientIdInput(e.target.value)}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={handleSaveClientId}>
            Enregistrer
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>
    );
  }

  // Etape 2 : Client ID present mais pas encore authentifie
  if (!status.is_authenticated) {
    return (
      <PanelSection title="Connexion Spotify">
        {!authUrl && (
          <PanelSectionRow>
            <ButtonItem layout="below" onClick={handleStartAuth}>
              Se connecter à Spotify
            </ButtonItem>
          </PanelSectionRow>
        )}
        {authUrl && (
          <>
            <PanelSectionRow>
              Depuis le Mode Bureau (Steam → Mode Bureau), ouvre Firefox et colle ce lien :
            </PanelSectionRow>
            <PanelSectionRow>
              <TextField value={authUrl} disabled />
            </PanelSectionRow>
            <PanelSectionRow>
              <ButtonItem layout="below" onClick={() => navigator.clipboard.writeText(authUrl)}>
                Copier le lien
              </ButtonItem>
            </PanelSectionRow>
            <PanelSectionRow>
              En attente de connexion... reviens sur le Deck une fois connecté.
            </PanelSectionRow>
          </>
        )}
      </PanelSection>
    );
  }

  // Etape 3 : connecte
  return (
    <>
      <PanelSection>
        <NowPlaying state={playbackState} />
        <PlaybackControls
          isPlaying={playbackState?.status === "Playing"}
          onAfterAction={refreshPlayback}
        />
      </PanelSection>

      <PanelSection title="Recherche">
        <PanelSectionRow>
          <TextField
            label="Titre, artiste..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={handleSearch} disabled={searching}>
            {searching ? "Recherche..." : "Rechercher"}
          </ButtonItem>
        </PanelSectionRow>
        {searchResults && !searchResults.ok && (
          <PanelSectionRow>Erreur de recherche : {searchResults.error}</PanelSectionRow>
        )}
        {searchResults?.ok && (
          <>
            {(searchResults.playlists ?? []).map((p) => (
              <PanelSectionRow key={p.uri}>
                <ButtonItem layout="below" onClick={() => openUri(p.uri)}>
                  📁 {p.name}
                </ButtonItem>
              </PanelSectionRow>
            ))}
            {(searchResults.tracks ?? []).map((t) => (
              <PanelSectionRow key={t.uri}>
                <ButtonItem layout="below" onClick={() => openUri(t.uri)}>
                  {t.name} — {t.artist}
                </ButtonItem>
              </PanelSectionRow>
            ))}
            {(searchResults.tracks?.length ?? 0) === 0 && (searchResults.playlists?.length ?? 0) === 0 && (
              <PanelSectionRow>Aucun résultat.</PanelSectionRow>
            )}
          </>
        )}
      </PanelSection>

      <PanelSection>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={openPlaylistsPage}>
            Playlists
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>
    </>
  );
};

export default definePlugin(() => {
  routerHook.addRoute(PLAYLISTS_ROUTE, PlaylistsPage, { exact: true });

  return {
    name: "SpotifHA",
    title: <div className={staticClasses.Title}>SpotifHA</div>,
    content: <Content />,
    icon: <FaSpotify />,
    onDismount() {
      routerHook.removeRoute(PLAYLISTS_ROUTE);
    },
  };
});
