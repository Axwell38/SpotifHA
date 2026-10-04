import os
import re
import json
import ssl
import time
import secrets
import hashlib
import base64
import asyncio
import subprocess
import urllib.request
import urllib.parse
import urllib.error
import http.server
import threading
import traceback

import decky_plugin

REDIRECT_PORT = 8069
SCOPES = "playlist-read-private playlist-read-collaborative user-read-playback-state"
AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"

SETTINGS_PATH = os.path.join(decky_plugin.DECKY_PLUGIN_SETTINGS_DIR, "settings.json")

MPRIS_BUS_NAME = "org.mpris.MediaPlayer2.spotify"
MPRIS_PATH = "/org/mpris/MediaPlayer2"
MPRIS_PLAYER_IFACE = "org.mpris.MediaPlayer2.Player"
MPRIS_PROPS_IFACE = "org.freedesktop.DBus.Properties"


def _clean_subprocess_env():
    env = dict(os.environ)
    env.pop("LD_LIBRARY_PATH", None)
    env.pop("LD_PRELOAD", None)
    if "DBUS_SESSION_BUS_ADDRESS" not in env:
        uid = os.getuid()
        env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path=/run/user/{uid}/bus"
    return env


def _ssl_context():
    candidates = [
        "/etc/ssl/certs/ca-certificates.crt",
        "/etc/ssl/cert.pem",
        "/etc/pki/tls/certs/ca-bundle.crt",
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                ctx = ssl.create_default_context(cafile=path)
                return ctx
            except Exception:
                continue
    return ssl.create_default_context()


def _load_settings():
    try:
        with open(SETTINGS_PATH, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_settings(data):
    os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
    with open(SETTINGS_PATH, "w") as f:
        json.dump(data, f)


def _new_pkce_pair():
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).decode("utf-8").rstrip("=")
    digest = hashlib.sha256(verifier.encode("utf-8")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")
    return verifier, challenge


class _CallbackServer(http.server.HTTPServer):
    allow_reuse_address = True

    def __init__(self, *args, timeout_seconds=65, **kwargs):
        super().__init__(*args, **kwargs)
        self.code = None
        self.error = None
        self.timeout = timeout_seconds


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        if "code" in qs:
            self.server.code = qs["code"][0]
            body = b"<html><body><h1>Connecte ! Tu peux revenir sur le Deck.</h1></body></html>"
        else:
            self.server.error = qs.get("error", ["unknown_error"])[0]
            body = b"<html><body><h1>Erreur de connexion Spotify.</h1></body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass


class Plugin:
    async def _main(self):
        self.redirect_uri = f"http://127.0.0.1:{REDIRECT_PORT}/callback"
        decky_plugin.logger.info(f"SpotifHA: backend demarre, redirect_uri={self.redirect_uri}")

    async def _unload(self):
        decky_plugin.logger.info("SpotifHA: backend arrete")

    # ---------- Settings / auth status ----------

    async def set_client_id(self, client_id: str):
        settings = _load_settings()
        settings["client_id"] = client_id.strip()
        _save_settings(settings)
        return {"ok": True}

    async def get_status(self):
        settings = _load_settings()
        return {
            "has_client_id": bool(settings.get("client_id")),
            "is_authenticated": bool(settings.get("access_token")),
            "redirect_uri": getattr(self, "redirect_uri", f"http://127.0.0.1:{REDIRECT_PORT}/callback"),
        }

    # ---------- OAuth PKCE flow ----------

    async def start_auth(self):
        settings = _load_settings()
        client_id = settings.get("client_id")
        if not client_id:
            return {"ok": False, "error": "no_client_id"}

        verifier, challenge = _new_pkce_pair()
        settings["pkce_verifier"] = verifier
        _save_settings(settings)

        params = {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": self.redirect_uri,
            "scope": SCOPES,
            "code_challenge_method": "S256",
            "code_challenge": challenge,
        }
        auth_url = f"{AUTH_URL}?{urllib.parse.urlencode(params)}"

        try:
            server = _CallbackServer(("127.0.0.1", REDIRECT_PORT), _CallbackHandler, timeout_seconds=600)
        except OSError as e:
            decky_plugin.logger.error(f"SpotifHA: impossible d'ouvrir le port {REDIRECT_PORT}: {e}")
            return {"ok": False, "error": "port_busy"}

        asyncio.create_task(self._wait_for_callback(server, verifier, client_id))
        return {"ok": True, "auth_url": auth_url}

    async def _wait_for_callback(self, server, verifier, client_id):
        deadline = time.time() + 600
        try:
            while time.time() < deadline:
                server.handle_request()
                if server.code or server.error:
                    break
            if server.code:
                await self._exchange_code(server.code, verifier, client_id)
            elif server.error:
                decky_plugin.logger.error(f"SpotifHA: erreur callback OAuth: {server.error}")
        except Exception:
            decky_plugin.logger.error("SpotifHA: exception pendant l'attente du callback:\n" + traceback.format_exc())
        finally:
            try:
                server.close()
                server.server_close()
            except Exception:
                pass

    async def _exchange_code(self, code, verifier, client_id):
        data = urllib.parse.urlencode({
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.redirect_uri,
            "client_id": client_id,
            "code_verifier": verifier,
        }).encode("utf-8")

        req = urllib.request.Request(TOKEN_URL, data=data, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")

        try:
            with urllib.request.urlopen(req, context=_ssl_context(), timeout=30) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except Exception:
            decky_plugin.logger.error("SpotifHA: echec exchange_code:\n" + traceback.format_exc())
            return

        settings = _load_settings()
        settings["access_token"] = payload.get("access_token")
        settings["refresh_token"] = payload.get("refresh_token", settings.get("refresh_token"))
        settings["expires_at"] = time.time() + payload.get("expires_in", 3600) - 60
        settings.pop("pkce_verifier", None)
        _save_settings(settings)
        decky_plugin.logger.info("SpotifHA: token obtenu avec succes")

    async def _refresh_access_token(self):
        settings = _load_settings()
        refresh_token = settings.get("refresh_token")
        client_id = settings.get("client_id")
        if not refresh_token or not client_id:
            return False

        data = urllib.parse.urlencode({
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
        }).encode("utf-8")

        req = urllib.request.Request(TOKEN_URL, data=data, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")

        try:
            with urllib.request.urlopen(req, context=_ssl_context(), timeout=30) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except Exception:
            decky_plugin.logger.error("SpotifHA: echec refresh_token:\n" + traceback.format_exc())
            return False

        settings["access_token"] = payload.get("access_token")
        if payload.get("refresh_token"):
            settings["refresh_token"] = payload.get("refresh_token")
        settings["expires_at"] = time.time() + payload.get("expires_in", 3600) - 60
        _save_settings(settings)
        return True

    async def _ensure_token(self):
        """Renvoie un access_token valide, en le rafraichissant si besoin. None si pas connecte."""
        settings = _load_settings()
        access_token = settings.get("access_token")
        if not access_token:
            return None
        expires_at = settings.get("expires_at", 0)
        if time.time() >= expires_at:
            ok = await self._refresh_access_token()
            if not ok:
                return None
            settings = _load_settings()
            access_token = settings.get("access_token")
        return access_token

    def _api_get(self, path, access_token):
        req = urllib.request.Request(f"https://api.spotify.com/v1{path}")
        req.add_header("Authorization", f"Bearer {access_token}")
        with urllib.request.urlopen(req, context=_ssl_context(), timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))

    # ---------- Spotify Web API ----------

    async def get_playlists(self):
        access_token = await self._ensure_token()
        if not access_token:
            return {"ok": False, "error": "not_authenticated"}

        playlists = []
        total = None
        offset = 0
        page_limit = 50
        try:
            while True:
                data = self._api_get(f"/me/playlists?limit={page_limit}&offset={offset}", access_token)
                if total is None:
                    total = data.get("total")
                items = data.get("items", []) or []
                decky_plugin.logger.info(
                    f"SpotifHA: get_playlists page offset={offset} recus={len(items)} total_annonce={total}"
                )
                for item in items:
                    if not item:
                        continue
                    images = item.get("images") or []
                    playlists.append({
                        "uri": item.get("uri"),
                        "name": item.get("name"),
                        "image": images[0]["url"] if images else None,
                    })
                if not items or (total is not None and offset + len(items) >= total):
                    break
                offset += page_limit
        except Exception:
            decky_plugin.logger.error("SpotifHA: echec get_playlists:\n" + traceback.format_exc())
            return {"ok": False, "error": "request_failed"}

        decky_plugin.logger.info(f"SpotifHA: get_playlists termine, {len(playlists)} playlists retournees")
        return {"ok": True, "playlists": playlists}

    async def search(self, query: str):
        decky_plugin.logger.info(f"SpotifHA: recherche demandee: {query!r}")
        access_token = await self._ensure_token()
        if not access_token:
            decky_plugin.logger.error("SpotifHA: recherche refusee, pas de token (non authentifie)")
            return {"ok": False, "error": "not_authenticated"}

        query = (query or "").strip()
        if not query:
            return {"ok": False, "error": "empty_query"}

        q = urllib.parse.quote(query)
        # Spotify limite les apps en mode developpement a 10 resultats par type
        # sur /v1/search (une limite plus haute renvoie 400 "Invalid limit").
        path = f"/search?q={q}&type=track,playlist&limit=10"
        try:
            data = self._api_get(path, access_token)
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8")
            except Exception:
                pass
            decky_plugin.logger.error(f"SpotifHA: echec search HTTP {e.code}: {body}")
            return {"ok": False, "error": f"http_{e.code}"}
        except Exception:
            decky_plugin.logger.error("SpotifHA: echec search:\n" + traceback.format_exc())
            return {"ok": False, "error": "request_failed"}

        tracks = []
        for item in (data.get("tracks") or {}).get("items", []) or []:
            if not item:
                continue
            artists = ", ".join(a.get("name", "") for a in item.get("artists", []) or [])
            tracks.append({
                "uri": item.get("uri"),
                "name": item.get("name"),
                "artist": artists,
            })

        playlists = []
        for item in (data.get("playlists") or {}).get("items", []) or []:
            if not item:
                continue
            playlists.append({
                "uri": item.get("uri"),
                "name": item.get("name"),
            })

        decky_plugin.logger.info(f"SpotifHA: recherche OK, {len(tracks)} pistes, {len(playlists)} playlists")
        return {"ok": True, "tracks": tracks, "playlists": playlists}

    # ---------- MPRIS playback control ----------

    def _run(self, args):
        return subprocess.run(
            args,
            capture_output=True,
            text=True,
            env=_clean_subprocess_env(),
            timeout=10,
        )

    def _mpris_call(self, member, signature="", *values):
        args = [
            "dbus-send", "--session", "--print-reply", "--type=method_call",
            f"--dest={MPRIS_BUS_NAME}", MPRIS_PATH,
            f"{MPRIS_PLAYER_IFACE}.{member}",
        ]
        if signature:
            args.append(signature)
            args.extend(str(v) for v in values)
        result = self._run(args)
        if result.returncode != 0:
            decky_plugin.logger.error(f"SpotifHA: dbus-send echoue ({member}): {result.stderr.strip()}")
            return False
        return True

    def _mpris_set_property(self, prop_name, signature, value):
        args = [
            "dbus-send", "--session", "--print-reply", "--type=method_call",
            f"--dest={MPRIS_BUS_NAME}", MPRIS_PATH,
            f"{MPRIS_PROPS_IFACE}.Set",
            "string:org.mpris.MediaPlayer2.Player",
            f"string:{prop_name}",
            f"variant:{signature}:{value}",
        ]
        result = self._run(args)
        return result.returncode == 0

    def _mpris_get_all(self):
        args = [
            "dbus-send", "--session", "--print-reply", "--type=method_call",
            f"--dest={MPRIS_BUS_NAME}", MPRIS_PATH,
            f"{MPRIS_PROPS_IFACE}.GetAll",
            "string:org.mpris.MediaPlayer2.Player",
        ]
        result = self._run(args)
        if result.returncode != 0:
            decky_plugin.logger.error(f"SpotifHA: dbus-send GetAll echoue: {result.stderr.strip()}")
            return None
        return result.stdout

    async def play_pause(self):
        return {"ok": self._mpris_call("PlayPause")}

    async def next_track(self):
        return {"ok": self._mpris_call("Next")}

    async def previous_track(self):
        return {"ok": self._mpris_call("Previous")}

    async def open_uri(self, uri: str):
        return {"ok": self._mpris_call("OpenUri", "string:" + uri)}

    async def set_volume(self, volume: float):
        return {"ok": self._mpris_set_property("Volume", "double", volume)}

    async def get_playback_state(self):
        decky_plugin.logger.info("SpotifHA: get_playback_state appele")
        raw = self._mpris_get_all()
        if raw is None:
            decky_plugin.logger.error("SpotifHA: get_playback_state, raw=None (mpris indisponible)")
            return {"ok": False, "error": "mpris_unavailable"}
        parsed = _parse_mpris_getall(raw)
        decky_plugin.logger.info(f"SpotifHA: get_playback_state parse -> {parsed}")
        return {"ok": True, **parsed}


def _parse_mpris_getall(raw: str):
    """Parse la sortie texte de dbus-send pour GetAll(Player) et en extrait
    title / artist / art_url / status / position / volume.

    La sortie de dbus-send n'est pas du JSON, c'est un dump texte imbrique
    (dict entry / variant / struct ...). On extrait les champs un par un
    avec des regex cibles plutot que d'essayer de parser toute la grammaire.
    """
    result = {
        "status": None,
        "title": None,
        "artist": None,
        "art_url": None,
        "position": None,
        "volume": None,
    }

    # PlaybackStatus
    m = re.search(r'"PlaybackStatus"\s*variant\s*string\s*"([^"]*)"', raw)
    if m:
        result["status"] = m.group(1)

    # Volume
    m = re.search(r'"Volume"\s*variant\s*double\s*([0-9.]+)', raw)
    if m:
        try:
            result["volume"] = float(m.group(1))
        except ValueError:
            pass

    # Position (microseconds)
    m = re.search(r'"Position"\s*variant\s*int64\s*(\d+)', raw)
    if m:
        try:
            result["position"] = int(m.group(1))
        except ValueError:
            pass

    # Metadata block: isole le sous-texte entre "Metadata" et la fin du dict
    meta_match = re.search(r'"Metadata".*', raw, re.DOTALL)
    meta_text = meta_match.group(0) if meta_match else raw

    m = re.search(r'"xesam:title"\s*variant\s*string\s*"([^"]*)"', meta_text)
    if m:
        result["title"] = m.group(1)

    m = re.search(r'"mpris:artUrl"\s*variant\s*string\s*"([^"]*)"', meta_text)
    if m:
        result["art_url"] = m.group(1)

    # xesam:artist est un array de strings ; on prend toutes les valeurs string
    # qui suivent "xesam:artist" jusqu'a la cle suivante.
    artist_block_match = re.search(
        r'"xesam:artist"\s*variant\s*array\s*\[(.*?)\]', meta_text, re.DOTALL
    )
    if artist_block_match:
        names = re.findall(r'string\s*"([^"]*)"', artist_block_match.group(1))
        if names:
            result["artist"] = ", ".join(names)

    return result
