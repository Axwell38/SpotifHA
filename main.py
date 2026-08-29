"""
SpotifHA backend

Deux canaux de contrôle, volontairement séparés :
  - MPRIS/DBus : play/pause/next/prev/volume/seek + ouverture d'une URI
    (playlist/morceau) sur le client Spotify local. Aucune auth requise.
  - Web API (OAuth PKCE) : lecture seule, pour parcourir/rechercher les
    playlists de l'utilisateur et récupérer leurs URIs/pochettes.

Chaque utilisateur fournit son propre Client ID (créé sur
developer.spotify.com/dashboard) — voir README.md. Aucun secret n'est
jamais stocké : le flow PKCE ne nécessite qu'un Client ID public.
"""

import asyncio
import base64
import hashlib
import http.server
import json
import secrets
import threading
import urllib.parse
import urllib.request
from pathlib import Path

import decky_plugin  # fourni par le runtime Decky

# --- Config ---------------------------------------------------------------

REDIRECT_URI = "http://127.0.0.1:8069/callback"
REDIRECT_PORT = 8069
SCOPES = "playlist-read-private playlist-read-collaborative user-read-playback-state"
AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"

SETTINGS_PATH = Path(decky_plugin.DECKY_PLUGIN_SETTINGS_DIR) / "settings.json"

MPRIS_BUS_NAME = "org.mpris.MediaPlayer2.spotify"
MPRIS_PATH = "/org/mpris/MediaPlayer2"
MPRIS_PLAYER_IFACE = "org.mpris.MediaPlayer2.Player"


def _load_settings() -> dict:
    if SETTINGS_PATH.exists():
        return json.loads(SETTINGS_PATH.read_text())
    return {}


def _save_settings(data: dict) -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(data, indent=2))


# --- PKCE helpers -----------------------------------------------------------

def _new_pkce_pair() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    return verifier, challenge


class _CallbackServer:
    """Petit serveur HTTP local qui n'existe que le temps de récupérer le
    `code` renvoyé par Spotify après connexion de l'utilisateur."""

    def __init__(self):
        self.code: str | None = None
        self.error: str | None = None
        self._server: http.server.HTTPServer | None = None

    def start(self):
        handler = self._make_handler()
        self._server = http.server.HTTPServer(("127.0.0.1", REDIRECT_PORT), handler)
        thread = threading.Thread(target=self._server.handle_request, daemon=True)
        thread.start()
        return thread

    def _make_handler(self):
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                parsed = urllib.parse.urlparse(self.path)
                qs = urllib.parse.parse_qs(parsed.query)
                outer.code = qs.get("code", [None])[0]
                outer.error = qs.get("error", [None])[0]
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                msg = "Connecté ! Tu peux revenir sur le Deck." if outer.code else "Échec de la connexion."
                self.wfile.write(f"<html><body><h2>{msg}</h2></body></html>".encode())

            def log_message(self, *args):
                pass  # silence le logging par défaut de http.server

        return Handler


class Plugin:
    _auth_state: dict = {}

    # -- lifecycle -----------------------------------------------------------

    async def _main(self):
        decky_plugin.logger.info("SpotifHA: backend démarré")

    async def _unload(self):
        decky_plugin.logger.info("SpotifHA: backend arrêté")

    # -- settings --------------------------------------------------------------

    async def set_client_id(self, client_id: str) -> dict:
        settings = _load_settings()
        settings["client_id"] = client_id.strip()
        _save_settings(settings)
        return {"ok": True}

    async def get_status(self) -> dict:
        settings = _load_settings()
        return {
            "has_client_id": bool(settings.get("client_id")),
            "is_authenticated": bool(settings.get("refresh_token")),
            "redirect_uri": REDIRECT_URI,
        }

    # -- OAuth PKCE ------------------------------------------------------------

    async def start_auth(self) -> dict:
        settings = _load_settings()
        client_id = settings.get("client_id")
        if not client_id:
            return {"ok": False, "error": "no_client_id"}

        verifier, challenge = _new_pkce_pair()
        self._auth_state["verifier"] = verifier

        params = {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": REDIRECT_URI,
            "scope": SCOPES,
            "code_challenge_method": "S256",
            "code_challenge": challenge,
        }
        auth_url = f"{AUTH_URL}?{urllib.parse.urlencode(params)}"

        server = _CallbackServer()
        server.start()

        # Ouvre le navigateur système sur le Deck (Konsole/Game Mode -> mode bureau,
        # ou xdg-open si disponible dans l'environnement du plugin).
        import webbrowser
        webbrowser.open(auth_url)

        # Attend la redirection (timeout raisonnable pour ne pas bloquer le QAM)
        for _ in range(600):  # ~60s
            if server.code or server.error:
                break
            await asyncio.sleep(0.1)

        if server.error or not server.code:
            return {"ok": False, "error": server.error or "timeout"}

        return await self._exchange_code(server.code, verifier, client_id)

    async def _exchange_code(self, code: str, verifier: str, client_id: str) -> dict:
        data = urllib.parse.urlencode({
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": client_id,
            "code_verifier": verifier,
        }).encode()

        req = urllib.request.Request(TOKEN_URL, data=data, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")

        try:
            with urllib.request.urlopen(req) as resp:
                payload = json.loads(resp.read())
        except Exception as e:
            decky_plugin.logger.error(f"SpotifHA: échange de token échoué: {e}")
            return {"ok": False, "error": "token_exchange_failed"}

        settings = _load_settings()
        settings["refresh_token"] = payload["refresh_token"]
        settings["access_token"] = payload["access_token"]
        _save_settings(settings)
        return {"ok": True}

    async def _refresh_access_token(self) -> str | None:
        settings = _load_settings()
        client_id = settings.get("client_id")
        refresh_token = settings.get("refresh_token")
        if not client_id or not refresh_token:
            return None

        data = urllib.parse.urlencode({
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
        }).encode()
        req = urllib.request.Request(TOKEN_URL, data=data, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")

        try:
            with urllib.request.urlopen(req) as resp:
                payload = json.loads(resp.read())
        except Exception as e:
            decky_plugin.logger.error(f"SpotifHA: refresh token échoué: {e}")
            return None

        settings["access_token"] = payload["access_token"]
        if "refresh_token" in payload:  # Spotify en renvoie parfois un nouveau
            settings["refresh_token"] = payload["refresh_token"]
        _save_settings(settings)
        return payload["access_token"]

    # -- Web API (lecture seule : playlists / recherche) ------------------------

    async def get_playlists(self) -> dict:
        token = await self._refresh_access_token()
        if not token:
            return {"ok": False, "error": "not_authenticated"}

        req = urllib.request.Request(
            "https://api.spotify.com/v1/me/playlists?limit=50"
        )
        req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req) as resp:
                payload = json.loads(resp.read())
        except Exception as e:
            decky_plugin.logger.error(f"SpotifHA: get_playlists échoué: {e}")
            return {"ok": False, "error": "api_error"}

        playlists = [
            {
                "uri": item["uri"],
                "name": item["name"],
                "image": (item["images"][0]["url"] if item.get("images") else None),
            }
            for item in payload.get("items", [])
        ]
        return {"ok": True, "playlists": playlists}

    async def search(self, query: str) -> dict:
        token = await self._refresh_access_token()
        if not token:
            return {"ok": False, "error": "not_authenticated"}

        params = urllib.parse.urlencode({"q": query, "type": "playlist,track", "limit": 15})
        req = urllib.request.Request(f"https://api.spotify.com/v1/search?{params}")
        req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req) as resp:
                payload = json.loads(resp.read())
        except Exception as e:
            decky_plugin.logger.error(f"SpotifHA: search échoué: {e}")
            return {"ok": False, "error": "api_error"}

        return {"ok": True, "raw": payload}

    # -- MPRIS (contrôle temps réel, local, sans auth) ---------------------------

    async def play_pause(self) -> dict:
        return await self._mpris_call("PlayPause")

    async def next_track(self) -> dict:
        return await self._mpris_call("Next")

    async def previous_track(self) -> dict:
        return await self._mpris_call("Previous")

    async def open_uri(self, uri: str) -> dict:
        return await self._mpris_call("OpenUri", uri)

    async def set_volume(self, volume: float) -> dict:
        # volume: 0.0 - 1.0
        return await self._mpris_set_property("Volume", volume)

    async def get_playback_state(self) -> dict:
        return await self._mpris_get_properties()

    async def _mpris_call(self, method: str, *args: str) -> dict:
        cmd = [
            "dbus-send", "--print-reply", "--session",
            f"--dest={MPRIS_BUS_NAME}", MPRIS_PATH,
            f"{MPRIS_PLAYER_IFACE}.{method}",
        ]
        cmd += [f"string:{a}" for a in args]
        return await self._run(cmd)

    async def _mpris_set_property(self, prop: str, value: float) -> dict:
        cmd = [
            "dbus-send", "--session", f"--dest={MPRIS_BUS_NAME}", MPRIS_PATH,
            "org.freedesktop.DBus.Properties.Set",
            f"string:{MPRIS_PLAYER_IFACE}", f"string:{prop}",
            f"variant:double:{value}",
        ]
        return await self._run(cmd)

    async def _mpris_get_properties(self) -> dict:
        cmd = [
            "dbus-send", "--print-reply", "--session", f"--dest={MPRIS_BUS_NAME}",
            MPRIS_PATH, "org.freedesktop.DBus.Properties.GetAll",
            f"string:{MPRIS_PLAYER_IFACE}",
        ]
        result = await self._run(cmd)
        # NOTE: le parsing propre de la sortie dbus-send (format texte, pas JSON)
        # reste à écrire — prévoir un vrai binding (dbus-next) si on veut du
        # "now playing" fiable plutôt qu'une preuve de concept.
        return result

    async def _run(self, cmd: list[str]) -> dict:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            decky_plugin.logger.error(f"SpotifHA: dbus-send échoué: {stderr.decode()}")
            return {"ok": False, "error": stderr.decode()}
        return {"ok": True, "output": stdout.decode()}
