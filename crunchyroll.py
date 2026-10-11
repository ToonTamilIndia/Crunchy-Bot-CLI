import time
import sys
import tls_client
import uuid
import random
import re
import json
from lxml import etree
import base64
from urllib.parse import urlencode, urljoin, urlparse
import os
import requests
import subprocess
import contextlib
import tempfile
from pathlib import Path
from tqdm import tqdm
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import shutil

from platform_tools import OperationCancelled, cancelled, run_cancellable

CR_API_BASE = "https://beta-api.crunchyroll.com"
CR_ETP_TOKEN_URL = "https://www.crunchyroll.com/auth/v1/token"
CR_SSO_LOGIN_URL = "https://sso.crunchyroll.com/api/login"
CR_SSO_AUTHORIZE_URL = "https://sso.crunchyroll.com/authorize"
CR_ETP_AUTHORIZATION = "Basic bm9haWhkZXZtXzZpeWcwYThsMHE6"
CR_ETP_USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/148.0.0.0 Mobile Safari/537.36"
)
CR_ETP_DEVICE_TYPE = "Chrome on Android"
CR_OAUTH_CLIENT_BASIC = "bm1oaGcwbDZ4eXhjZm02aHQ2aGY6SjR6bU1mdjNkMVFkWHk4dDk2d1NjeDdoUnkzclBHLTM="
CR_OAUTH_CLIENT_AUTH = f"Basic {CR_OAUTH_CLIENT_BASIC}"
CR_OAUTH_USER_AGENT = (
    "Crunchyroll/ANDROIDTV/3.61.0_22341 (Android 12; en-US; SHIELD Android TV Build/SR1A.211012.001)"
)
CR_PLAYBACK_BASE = "https://cr-play-service.prd.crunchyrollsvc.com/v3"
CR_PLAYBACK_TOKEN_BASE = "https://cr-play-service.prd.crunchyrollsvc.com/v1/token"
CR_LICENSE_URL = "https://cr-license-proxy.prd.crunchyrollsvc.com/v1/license/widevine"
CR_VILOS_BUNDLE_URL = "https://static.crunchyroll.com/vilos-v2/web/vilos/js/bundle.js"
CR_WEB_AUTHORIZATION = "Basic Y3Jfd2ViOg=="
CR_WEB_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:137.0) "
    "Gecko/20100101 Firefox/137.0"
)
# Seeded here so the library works before any entry point calls set_cr_debug().
# The effective value is resolved live by resolve_debug_settings().
CR_DEBUG = False

CRD_AUTH_DATA_URLS = (
    "https://Crunchy-DL.github.io/Crunchy-Downloader/data.json",
    "https://crunchy-dl.github.io/Crunchy-Downloader/data.json",
)
CR_ANDROID_USER_AGENT = "Crunchyroll/3.97.0 Android/16 okhttp/4.12.0"
CR_PLAYBACK_ENDPOINTS = ("web/firefox", "tv/android_tv", "android/phone", "web/chrome")
CR_AUTH_PROFILES = (
    {
        "name": "nx_androidtv",
        "endpoint": "tv/android_tv",
        "basic_token": "bm1oaGcwbDZ4eXhjZm02aHQ2aGY6SjR6bU1mdjNkMVFkWHk4dDk2d1NjeDdoUnkzclBHLTM=",
        "user_agent": "Crunchyroll/ANDROIDTV/3.61.0_22341 (Android 12; en-US; SHIELD Android TV Build/SR1A.211012.001)",
        "device_name": "emu64xa",
        "device_type": "ANDROIDTV",
        "client_form": True,
    },
    {
        "name": "android_phone",
        "endpoint": "android/phone",
        "authorization": "Basic bzJhNndsamdub3FtdjloMWJ5bHI6Ujk3S3ExZm5faExZVFk0bDJxTjJIT2lDQnpfYnpBSUU=",
        "user_agent": CR_ANDROID_USER_AGENT,
        "device_name": "CPH2449",
        "device_type": "OnePlus CPH2449",
    },
    {
        "name": "android_tv",
        "endpoint": "tv/android_tv",
        "authorization": "Basic eTJhcnZqYjBoMHJndnRpemxvdnk6SlZMdndkSXBYdnhVLXFJQnZUMU04b1FUcjFxbFFKWDI=",
        "user_agent": "ANDROIDTV/3.59.0 Android/16",
        "device_name": "Android TV",
        "device_type": "Android TV",
    },
)

APP_ROOT = Path(__file__).resolve().parent
DOWNLOADS_DIR = APP_ROOT / "Downloads"
TEMP_DIR = APP_ROOT / "Temp"


def ensure_workspace_dirs():
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    TEMP_DIR.mkdir(parents=True, exist_ok=True)


def get_download_path(*parts, create_parent=False):
    ensure_workspace_dirs()
    path = DOWNLOADS_DIR.joinpath(*parts)
    if create_parent:
        path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


def get_temp_path(*parts, create_parent=False):
    ensure_workspace_dirs()
    path = TEMP_DIR.joinpath(*parts)
    if create_parent:
        path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


def get_segment_temp_dir(name):
    path = Path(get_temp_path(name, "segments"))
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


def get_encrypted_media_path(name, extension):
    path = Path(get_temp_path(name, f"{name}.{extension}"))
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


def set_cr_debug(enabled):
    global CR_DEBUG
    CR_DEBUG = bool(enabled)


def cr_debug(message):
    if CR_DEBUG:
        print(f"[DEBUG] {message}")


LOG_LEVEL_NAMES = frozenset(
    {"CRITICAL", "FATAL", "ERROR", "WARN", "WARNING", "INFO", "DEBUG", "NOTSET"}
)

DEFAULT_DEBUG_LEVEL = "DEBUG"


def normalize_debug_level(value, default=DEFAULT_DEBUG_LEVEL):
    """Coerce a configured log level into a name `logging` will accept.

    An empty or unrecognised level must never be handed to logging.basicConfig:
    it raises ValueError and takes the whole program down. Returns the default
    instead so a typo degrades to normal logging instead of crashing.
    """
    if value is None:
        return default
    name = str(value).strip().upper()
    if not name:
        return default
    if name in LOG_LEVEL_NAMES:
        return name
    if name.isdigit():
        # logging accepts an int level, but never a numeric string, so convert
        # here instead of letting basicConfig raise on "--debug=5".
        number = int(name)
        if 0 <= number <= 50:
            return number
        return default
    return default


def config_value(name, default=None):
    """Public live accessor for a config.py setting.

    `from config import *` binds values at import time, so reading a setting
    from a bare global silently ignores any later change. Routing every read
    through this keeps config, cli and tg agreeing on the current value.
    """
    value = _config_value(name)
    return default if value is None else value


def _as_bool(value, default=False):
    """Coerce a config value to a bool.

    `use_watermark = "False"` is a truthy string, so a plain `if value:` would
    silently switch the watermark on. Spell the string values out explicitly.
    """
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("1", "true", "yes", "on"):
            return True
        if text in ("0", "false", "no", "off", ""):
            return False
        return default
    return bool(value)


def _config_int(name, default, minimum=None):
    """Read an integer setting, tolerating a quoted value in config.py.

    `max_retries = "3"` would otherwise raise TypeError from range(), and
    `retry_delay = "2"` would be repeated as a string before being added to a
    float. Coerce here so a quoting mistake degrades instead of crashing.
    """
    raw = _config_value(name)
    if raw is None or raw == "":
        value = default
    else:
        try:
            value = int(float(raw))
        except (TypeError, ValueError):
            value = default
    if minimum is not None and value < minimum:
        value = minimum
    return value


def _config_float(name, default, minimum=None):
    """Read a float setting, tolerating a quoted value in config.py."""
    raw = _config_value(name)
    if raw is None or raw == "":
        value = float(default)
    else:
        try:
            value = float(raw)
        except (TypeError, ValueError):
            value = float(default)
    if minimum is not None and value < minimum:
        value = float(minimum)
    return value


def resolve_debug_settings(argv=None, flag="--debug", negate_flag="--no-debug"):
    """Resolve debug on/off and log level from CLI arguments and config.

    Keeping this in one place means every entry point agrees on precedence:

        --no-debug          force off, overriding config
        --debug=LEVEL       force on at a given level
        --debug LEVEL       same, as a separate argument
        --debug             on, using the configured level
        (nothing)           follow config

    Returns (enabled, level_name). Never raises.
    """
    args = list(sys.argv[1:] if argv is None else argv)
    configured_on = bool(_config_value("debug"))
    configured_level = _config_value("level", "LOG_LEVEL")

    enabled = configured_on
    level = normalize_debug_level(configured_level)

    index = 0
    while index < len(args):
        arg = args[index]
        if arg == negate_flag:
            return False, level
        if arg == flag:
            enabled = True
            if "=" in arg:
                _, _, inline = arg.partition("=")
                if inline.strip():
                    level = normalize_debug_level(inline, level)
            elif index + 1 < len(args):
                candidate = args[index + 1].strip()
                if candidate.upper() in LOG_LEVEL_NAMES:
                    level = normalize_debug_level(candidate, level)
                    index += 1
            index += 1
            continue
        if arg.startswith(flag + "="):
            enabled = True
            _, _, inline = arg.partition("=")
            if inline.strip():
                level = normalize_debug_level(inline, level)
        index += 1

    return enabled, level


def _version_tuple(version):
    return tuple(int(part) for part in re.findall(r"\d+", version or "0"))


def _datetime_to_timestamp(value):
    text = str(value).replace("Z", "+00:00")
    match = re.match(r"(.+?\\.\\d{6})\\d+([+-]\\d\\d:?\\d\\d)?$", text)
    if match:
        text = "".join(part for part in match.groups() if part)
    parsed = datetime.fromisoformat(text)
    return int(parsed.timestamp())


class Miscellaneous:
    def randomize_user_agent(self) -> str:
        android_version = f"{random.randint(14, 16)}"
        okhttp_version = f"4.12.{random.randint(0, 9)}"
        return f"Crunchyroll/3.97.0 Android/{android_version} okhttp/{okhttp_version}"

CR_TRUSTED_HOSTS = {"crunchyroll.com", "www.crunchyroll.com"}
# Playback, token and license endpoints are served from crunchyrollsvc.com, which
# is a separate registrable domain from crunchyroll.com. The CDN is a third.
CR_TRUSTED_HOST_SUFFIXES = (
    ".crunchyroll.com",
    ".crunchyrollcdn.com",
    ".crunchyrollsvc.com",
)
_SENSITIVE_HEADERS = {"authorization", "cookie"}


def is_crunchyroll_url(url):
    """True when the URL belongs to a Crunchyroll-owned host.

    The session object is shared across every request the library makes,
    including fetches of community-maintained metadata such as data.json. Session
    cookies and session headers are not host-scoped by tls_client, so anything
    that is not a Crunchyroll host must never receive them.
    """
    try:
        host = (urlparse(str(url)).hostname or "").lower()
    except ValueError:
        return False
    if not host:
        return False
    if host in CR_TRUSTED_HOSTS:
        return True
    return any(host.endswith(suffix) for suffix in CR_TRUSTED_HOST_SUFFIXES)


class CrunchyrollBase:
    def __init__(self):
        self.session = tls_client.Session("okhttp4_android_13", random_tls_extension_order=True)

    def set_headers(self, headers, replace=False):
        if replace:
            self.session.headers.clear()
        self.session.headers.update(headers)

    def request(self, method, url, **kwargs):
        if config_value("use_proxy") and config_value("proxy"):
            kwargs.setdefault("proxy", config_value("proxy"))
        if is_crunchyroll_url(url):
            return getattr(self.session, method)(url, **kwargs)

        # Non-Crunchyroll host: tls_client merges per-request cookies into a
        # persistent jar and does not scope them by host, so a saved etp_rt would
        # ride along to any third party. Detach the jar and credentials for the
        # duration of this call, then restore them.
        saved_cookies = getattr(self.session, "cookies", None)
        saved_headers = {}
        session_headers = getattr(self.session, "headers", None)
        try:
            if session_headers:
                for key in list(session_headers):
                    if str(key).lower() in _SENSITIVE_HEADERS:
                        saved_headers[key] = session_headers.pop(key)
        except (AttributeError, TypeError, KeyError):
            saved_headers = {}

        kwargs.pop("cookies", None)
        headers = kwargs.pop("headers", None)
        if headers:
            headers = {
                key: value for key, value in headers.items()
                if str(key).lower() not in _SENSITIVE_HEADERS
            }
            if headers:
                kwargs["headers"] = headers

        detached = False
        try:
            if saved_cookies is not None:
                self.session.cookies = tls_client.cookies.RequestsCookieJar()
                detached = True
            return getattr(self.session, method)(url, **kwargs)
        finally:
            if detached:
                self.session.cookies = saved_cookies
            if session_headers is not None:
                for key, value in saved_headers.items():
                    session_headers[key] = value


def _http_request(method, url, **kwargs):
    if config_value("use_proxy") and config_value("proxy"):
        kwargs.setdefault("proxies", {"http": config_value("proxy"), "https": config_value("proxy")})
    return requests.request(method, url, **kwargs)


def _config_value(*names):
    """Read a setting from config, preferring the live module over the snapshot.

    `from config import *` binds values at import time, so a script or test that
    sets `config.debug = True` afterwards would silently be ignored. Consult the
    module itself first and fall back to the star-imported snapshot.
    """
    try:
        import config as _config_module
    except Exception:
        _config_module = None

    for name in names:
        if _config_module is not None and hasattr(_config_module, name):
            # Return the live value verbatim, including "" or None. A caller that
            # cleared a setting must not silently get the import-time snapshot
            # back; fall through to the snapshot only when the name is absent.
            return getattr(_config_module, name)
    for name in names:
        value = globals().get(name)
        if value:
            return value
    return None


def _candidate_dirs():
    dirs = [Path.cwd(), Path(__file__).resolve().parent]
    configured_dir = _config_value("widevine_device_dir", "WIDEVINE_DEVICE_DIR", "cdm_dir", "CDM_DIR")
    if configured_dir:
        dirs.insert(0, Path(configured_dir).expanduser())
    for base in list(dirs):
        dirs.extend([
            base / "widevine",
            base / "Widevine",
            base / "cdm",
            base / "CDM",
            base / "devices",
            base / "Devices",
        ])
    seen = set()
    unique_dirs = []
    for directory in dirs:
        resolved = directory.expanduser()
        key = str(resolved)
        if key not in seen:
            seen.add(key)
            unique_dirs.append(resolved)
    return unique_dirs


def _first_existing_path(*values):
    for value in values:
        if not value:
            continue
        path = Path(value).expanduser()
        if path.is_file():
            return path
    return None


def find_widevine_device_files():
    configured_device = _first_existing_path(
        _config_value("widevine_device_path", "WIDEVINE_DEVICE_PATH", "wvd_path", "WVD_PATH", "cdm_device_path", "CDM_DEVICE_PATH")
    )
    if configured_device and configured_device.suffix.lower() == ".wvd":
        return {"type": "wvd", "device": configured_device}

    configured_key = _first_existing_path(
        _config_value("widevine_private_key_path", "WIDEVINE_PRIVATE_KEY_PATH", "private_key_path", "PRIVATE_KEY_PATH")
    )
    configured_client_id = _first_existing_path(
        _config_value("widevine_client_id_path", "WIDEVINE_CLIENT_ID_PATH", "client_id_path", "CLIENT_ID_PATH")
    )
    if configured_key and configured_client_id:
        return {"type": "raw", "private_key": configured_key, "client_id": configured_client_id}

    for directory in _candidate_dirs():
        if not directory.is_dir():
            continue
        wvd_files = sorted(directory.glob("*.wvd"))
        if wvd_files:
            return {"type": "wvd", "device": wvd_files[0]}

    for directory in _candidate_dirs():
        if not directory.is_dir():
            continue
        pem_files = sorted(directory.glob("*.pem"))
        bin_files = sorted(directory.glob("*.bin"))
        if not pem_files or not bin_files:
            continue

        for pem_file in pem_files:
            same_stem = [bin_file for bin_file in bin_files if bin_file.stem == pem_file.stem]
            client_candidates = same_stem or [
                bin_file for bin_file in bin_files
                if "client" in bin_file.stem.lower() or "blob" in bin_file.stem.lower()
            ] or bin_files
            if client_candidates:
                return {"type": "raw", "private_key": pem_file, "client_id": client_candidates[0]}

    return {}


def load_widevine_device():
    from pywidevine.device import Device, DeviceTypes

    device_files = find_widevine_device_files()
    if device_files.get("type") == "wvd":
        return Device.load(device_files["device"])
    if device_files.get("type") == "raw":
        return Device(
            type_=DeviceTypes.ANDROID,
            security_level=int(globals().get("widevine_security_level", globals().get("WIDEVINE_SECURITY_LEVEL", 3))),
            flags={},
            private_key=device_files["private_key"].read_bytes(),
            client_id=device_files["client_id"].read_bytes(),
        )

    searched = ", ".join(str(path) for path in _candidate_dirs())
    raise FileNotFoundError(
        "No Widevine device found. Put l3.wvd in the project root, or set "
        "widevine_device_path, or set widevine_private_key_path + widevine_client_id_path. "
        f"Searched: {searched}"
    )


class CrunchyrollLicense(CrunchyrollBase):
    def get_license(self, pssh, token, content_id, vid_token):
        from pywidevine.cdm import Cdm
        from pywidevine.pssh import PSSH

        self.last_license_error = None
        try:
            device = load_widevine_device()
        except Exception as error:
            self.last_license_error = f"Could not load the Widevine device: {error}"
            return None

        cdm = Cdm.from_device(device)
        session_id = cdm.open()
        try:
            challenge = cdm.get_license_challenge(session_id, PSSH(pssh))

            self.set_headers({
                "User-Agent": CR_WEB_USER_AGENT,
                "Accept-Encoding": "gzip, deflate, br",
                "Accept": "*/*",
                "Connection": "Keep-Alive",
                "Authorization": f"Bearer {vid_token}",
                "content-type": "application/octet-stream",
                "origin": "https://static.crunchyroll.com",
                "referer": "https://static.crunchyroll.com/",
                "x-cr-video-token": token,
                "x-cr-content-id": content_id,
            }, replace=True)
            response = self.request("post", CR_LICENSE_URL, data=bytes(challenge))
            if response.status_code != 200:
                self.last_license_error = (
                    f"License server returned HTTP {response.status_code}: "
                    f"{response.text[:300]}"
                )
                return None

            try:
                encoded_license = response.json()["license"]
            except Exception as error:
                self.last_license_error = f"License response was not valid JSON: {error}"
                return None

            cdm.parse_license(session_id, base64.b64decode(encoded_license))
            keys = build_license_key_entries(cdm.get_keys(session_id))
            if not keys:
                self.last_license_error = "The license response contained no keys."
                return None
            return {"key": keys}
        except Exception as error:
            self.last_license_error = f"License exchange failed: {error}"
            return None
        finally:
            cdm.close(session_id)
            if token:
                self.set_headers({
                    "Authorization": f"Bearer {vid_token}",
                    "Content-Type": "application/json",
                    "User-Agent": CR_WEB_USER_AGENT,
                }, replace=True)
                with contextlib.suppress(Exception):
                    self.request("patch", f"{CR_PLAYBACK_TOKEN_BASE}/{content_id}/{token}/inactive", json={})

class LicenseError(RuntimeError):
    """Raised when a Widevine decryption key cannot be obtained."""


def extract_content_key(license_response, context="", kid=None):
    """Pull the decryption key out of a get_license() response.

    get_license() returns None whenever the license request fails (a 5xx, a
    timeout, a malformed body), so callers that index the result directly raise
    TypeError. Raising LicenseError with an actionable message instead lets
    callers skip one episode or one audio track without a traceback.

    A single license covers every track, so it carries one key per rendition
    and they are all typed CONTENT. `kid` is the track's default_KID from the
    MPD; matching on it is the only reliable way to tell the video key from an
    audio key. Without it, "the first CONTENT key" silently hands the video
    track an audio key and the result decodes as corrupt frames.
    """
    label = f" for {context}" if context else ""
    if not license_response:
        raise LicenseError(
            f"No decryption license was returned{label}. The license server may be "
            f"rate-limiting, or the current account may not have access to this title."
        )
    keys = license_response.get("key") or []
    usable = [k for k in keys if k.get("kid_hex") and k.get("key_hex")]
    if not usable:
        raise LicenseError(f"The license contained no usable content key{label}.")

    wanted = normalize_kid(kid) if kid else None
    if wanted:
        for key in usable:
            if normalize_kid(key.get("kid_hex")) == wanted:
                return "{}:{}".format(key["kid_hex"], key["key_hex"])
        raise LicenseError(
            f"The license returned {len(usable)} key(s) but none matched this "
            f"track's key ID{label}. The track stayed encrypted, so it would "
            f"decode as corrupt frames."
        )

    for key in usable:
        if str(key.get("type", "")).upper() == "CONTENT":
            return "{}:{}".format(key["kid_hex"], key["key_hex"])
    first = usable[0]
    return "{}:{}".format(first["kid_hex"], first["key_hex"])


def build_license_key_entries(cdm_keys):
    """Convert pywidevine Key objects into the payload extract_content_key reads.

    pywidevine stores ``kid`` as a uuid.UUID, whose ``.hex`` is a *property*,
    but ``key`` as bytes, whose ``.hex`` is a *method*. Writing ``key.key.hex``
    without the parentheses puts a bound-method repr into the payload, so every
    caller ends up asking mp4decrypt for
    "<valid kid>:<built-in method hex of bytes object at 0x...>". mp4decrypt
    cannot use that, the track stays encrypted, and ffmpeg decodes ciphertext.
    """
    entries = []
    for key in cdm_keys:
        kid = key.kid
        raw = key.key
        kid_hex = kid.hex if hasattr(kid, "hex") else str(kid)
        if callable(kid_hex):
            kid_hex = kid_hex()
        key_hex = raw.hex() if isinstance(raw, (bytes, bytearray, memoryview)) else raw
        entries.append({
            "type": getattr(key, "type", None),
            "kid_hex": kid_hex,
            "key_hex": key_hex,
            "permissions": list(getattr(key, "permissions", []) or []),
        })
    return entries


def normalize_kid(value):
    """Compare key IDs case- and separator-insensitively."""
    if value is None:
        return ""
    return re.sub(r"[^0-9a-f]", "", str(value).lower())


def track_key(track):
    """Stable identity for a subtitle/caption track across episodes.

    Language alone is ambiguous: an episode can offer both an en-US caption and
    an en-US subtitle, and matching on language alone replayed whichever came
    first, so a request for the subtitle silently muxed the caption.
    """
    if isinstance(track, dict):
        return (track.get("type"), track.get("language"))
    if isinstance(track, (tuple, list)):
        # Already a key: keep it idempotent so callers can pass either form.
        return tuple(track)[:2]
    return (None, track)


def resolve_batch_subtitles(selected_tracks, track_info_list, locale_map=None):
    """Re-resolve a one-time subtitle choice against one episode's track list.

    Batch mode prompts once and replays the answer for every episode, but track
    lists differ between episodes. Resolving by (type, language) instead of by
    the stored index avoids both IndexError and the silent failure where a
    differently ordered list muxes the wrong track.
    """
    locale_map = locale_map or {}
    selected = []
    for wanted in selected_tracks or []:
        wanted_key = track_key(wanted)
        entry = next((t for t in track_info_list if track_key(t) == wanted_key), None)
        if entry is None and wanted_key[1]:
            # Episode offers only one kind of track for that language; fall back
            # so a caption-only episode still gets the requested language.
            entry = next((t for t in track_info_list
                          if t.get("language") == wanted_key[1]), None)
        if entry is None:
            continue
        selected.append({
            "language": locale_map.get(entry["language"], entry["language"]),
            "url": entry["url"],
            "format": entry["format"],
            "type": entry["type"],
        })
    return selected


def resolve_batch_audios(selected_locales, versions, locale_map=None):
    """Re-resolve a one-time audio choice against one episode's version list.

    Returns (resolved, missing) so a caller can skip an absent dub and carry on
    rather than aborting every remaining episode.
    """
    locale_map = locale_map or {}
    resolved = []
    missing = []
    for locale in selected_locales or []:
        matches = [v for v in versions if v.get("audio_locale") == locale]
        if not matches:
            missing.append(locale)
            continue
        resolved.append({
            "audio_locale": locale_map.get(locale, locale),
            "guid": matches[0]["guid"],
        })
    return resolved, missing


def resolve_video_quality(video_list, chosen_index, chosen_height):
    """Return the requested rendition, preferring the stable height.

    A batch run stores the height the user picked, but chosen_index only refers
    to the rendition list it was typed against. On a later episode whose list
    differs, honouring the index silently downloaded whatever now sat there
    (asking for 720p returned 480p). Height is stable across episodes, so it
    wins; the index is only a fallback for the interactive single-title path.
    """
    if not video_list:
        return None
    if chosen_height:
        exact = [item for item in video_list if item.get("height") == chosen_height]
        if exact:
            return exact[0]
    if isinstance(chosen_index, int) and 0 <= chosen_index < len(video_list):
        return video_list[chosen_index]
    if chosen_height:
        return min(video_list, key=lambda item: abs(item.get("height", 0) - chosen_height))
    return video_list[0]


def dedup_preserving_order(values):
    """Order-preserving de-duplication for comma-separated track selections."""
    seen = []
    for value in values or []:
        if value not in seen:
            seen.append(value)
    return seen


def build_byte_ranges(total_size, parts):
    """Split total_size into up to `parts` contiguous inclusive byte ranges.

    Ranges tile the file exactly once, so a parallel fetch can be concatenated in
    order without duplicating or dropping bytes. Returns [] for an unusable size.
    """
    if not isinstance(total_size, int) or isinstance(total_size, bool):
        return []
    if total_size <= 0 or parts < 1:
        return []
    parts = min(parts, total_size)
    chunk_size = -(-total_size // parts)
    return [
        (start, min(start + chunk_size, total_size) - 1)
        for start in range(0, total_size, chunk_size)
    ]


def parse_content_range_total(header_text):
    """Read the complete resource size out of a `Content-Range: bytes a-b/TOTAL`.

    Returns None when the server sent no range header or an unsized (``*``) one,
    which means it ignored the Range request and cannot be split safely.
    """
    if not header_text:
        return None
    match = re.search(r'content-range:\s*bytes\s+\d+-\d+/(\d+|\*)', header_text, re.IGNORECASE)
    if not match or match.group(1) == '*':
        return None
    return int(match.group(1))


def download_segment(segment_links, name, format, max_threads=20, headers=None,
                     user_agent=None, cancel_event=None):
    # Always start from an empty scratch directory. Leftover parts from a previous
    # failed run would otherwise be resumed and concatenated into the output,
    # because multi-segment parts carry no expected length to validate against.
    if cancelled(cancel_event):
        raise OperationCancelled("download cancelled before it started")
    shutil.rmtree(get_segment_temp_dir(name), ignore_errors=True)
    base_temp_dir = get_segment_temp_dir(name)
    output_path = get_encrypted_media_path(name, format)

    if not segment_links:
        raise RuntimeError("No segments were resolved for this stream.")

    total = len(segment_links)
    configured_threads = _config_int("download_threads", max_threads, minimum=1)
    max_threads = configured_threads
    failed_segments = []
    assembled_expected_size = None

    progress_bar = tqdm(total=total, desc=f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} [INFO] : ", unit="file")

    

    def normalize_headers(raw_headers, ua_override):
        normalized = {}
        if raw_headers:
            for key, value in raw_headers.items():
                if value is None or value == "":
                    continue
                normalized[str(key)] = str(value)
        if ua_override:
            normalized.setdefault("User-Agent", ua_override)
        normalized.setdefault("User-Agent", CR_WEB_USER_AGENT)
        normalized.setdefault("Accept", "*/*")
        normalized.setdefault("Connection", "keep-alive")
        normalized.setdefault("Referer", "https://www.crunchyroll.com/")
        normalized.setdefault("Origin", "https://www.crunchyroll.com")
        return normalized

    normalized_headers = normalize_headers(headers, user_agent)

    def build_curl_cmd(url, temp_path, stall_time="30", resume=True):
        # --speed-limit/--speed-time abort only when throughput stays under the
        # floor for stall_time seconds. --max-time would instead cap the whole
        # transfer, which can never complete a large single-file representation.
        cmd = [
            "curl", "-sS", "-L", "--fail",
            "--connect-timeout", "10",
            "--speed-limit", "1024",
            "--speed-time", str(stall_time),
            "--retry", "2",
            "--retry-all-errors",
            "--retry-delay", "1",
            "--retry-max-time", "60",
        ]
        if resume:
            cmd.extend(["-C", "-"])
        for key, value in normalized_headers.items():
            cmd.extend(["-H", f"{key}: {value}"])
        cmd.extend([url.strip(), "-o", temp_path])
        if config_value("use_proxy"):
            cmd.insert(-2, "--proxy")
            cmd.insert(-2, config_value("proxy"))
        return cmd

    def run_curl(url, temp_path, stall_time):
        # Resume when a partial file exists; fall back to a clean fetch when the
        # server rejects byte ranges, otherwise the resume would never progress.
        if os.path.exists(temp_path) and os.path.getsize(temp_path) > 0:
            result = run_cancellable(
                build_curl_cmd(url, temp_path, stall_time, resume=True),
                cancel_event=cancel_event,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            if result.returncode != 33:
                return result
            with contextlib.suppress(Exception):
                os.remove(temp_path)
        return run_cancellable(
            build_curl_cmd(url, temp_path, stall_time, resume=False),
            cancel_event=cancel_event,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def run_curl_range(url, temp_path, stall_time, byte_range):
        start, end = byte_range
        cmd = build_curl_cmd(url, temp_path, stall_time, resume=False)
        cmd.extend(["-r", f"{start}-{end}"])
        result = run_cancellable(
            cmd,
            cancel_event=cancel_event,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        return result

    def probe_total_size(url):
        # One-byte Range request: confirms the CDN honours ranges and returns the
        # full size, which is what makes a split fetch safe.
        cmd = [
            "curl", "-sS", "-L", "--fail",
            "--connect-timeout", "10",
            "--max-time", "20",
            "-r", "0-0",
            "-D", "-",
            "-o", os.devnull,
        ]
        for key, value in normalized_headers.items():
            cmd.extend(["-H", f"{key}: {value}"])
        cmd.append(url.strip())
        if config_value("use_proxy"):
            cmd.extend(["--proxy", config_value("proxy")])
        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except Exception:
            return None
        if result.returncode != 0:
            return None
        return parse_content_range_total(result.stdout.decode('utf-8', errors='ignore'))

    # A SegmentBase representation is one large file, so segment-level threading
    # cannot help it. Fan it out into contiguous byte ranges instead, and fall
    # back to the single-stream path when the CDN will not serve ranges.
    tasks = []
    if total == 1:
        single_url = segment_links[0]
        single_size = probe_total_size(single_url)
        ranges = build_byte_ranges(single_size, max_threads) if single_size else []
        if len(ranges) > 1:
            progress_bar.reset(total=len(ranges))
            for part_index, (start, end) in enumerate(ranges):
                tasks.append({
                    "url": single_url,
                    "path": os.path.join(base_temp_dir, f"part_{part_index:04d}.ts"),
                    "byte_range": (start, end),
                    "expected": end - start + 1,
                })
            assembled_expected_size = single_size
            print(f"[INFO] Single-file representation ({single_size} bytes) split into {len(ranges)} parallel ranges.")

    if not tasks:
        for index, url in enumerate(segment_links):
            tasks.append({
                "url": url,
                "path": os.path.join(base_temp_dir, f"segment_{index}.ts"),
                "byte_range": None,
                "expected": None,
            })

    # Clamp concurrency to the work actually queued, which is the segment count
    # normally but the byte-range part count for a split single-file fetch.
    max_workers = max(1, min(max_threads, len(tasks)))

    def verify_task(task):
        if not os.path.exists(task["path"]):
            return False
        size = os.path.getsize(task["path"])
        expected = task["expected"]
        if expected is None:
            return size > 0
        return size == expected

    def fetch_task(task, stall_time):
        try:
            if task["byte_range"] is None:
                result = run_curl(task["url"], task["path"], stall_time)
            else:
                result = run_curl_range(task["url"], task["path"], stall_time, task["byte_range"])
            if result.returncode == 0 and verify_task(task):
                return True
            err_msg = result.stderr.decode('utf-8', errors='ignore').strip()
            print(f"\n[DEBUG] Segment fetch failed with returncode {result.returncode}. Error: {err_msg}. URL: {task['url'].strip()}")
        except Exception as e:
            print(f"\n[DEBUG] Segment fetch exception: {e}")
        return False

    def download_task(index, task):
        if cancelled(cancel_event):
            raise OperationCancelled("download cancelled")
        attempts = _config_int("max_retries", 3, minimum=1)
        delay = _config_float("retry_delay", 2, minimum=0)
        for retry in range(attempts):
            if cancelled(cancel_event):
                raise OperationCancelled("download cancelled")
            if fetch_task(task, "30"):
                return index, True
            if cancelled(cancel_event):
                raise OperationCancelled("download cancelled")
            backoff = delay * (2 ** retry)
            # Sleep in slices so a cancel does not wait out the whole backoff.
            deadline = time.time() + backoff
            while time.time() < deadline:
                if cancelled(cancel_event):
                    raise OperationCancelled("download cancelled")
                time.sleep(0.2)
            print(f"[WARN] Segment {index} failed retrying ({retry + 1}/{attempts}).")
        with contextlib.suppress(Exception):
            os.remove(task["path"])
        return index, False

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_index = {
            executor.submit(download_task, i, task): i
            for i, task in enumerate(tasks)
        }

        for future in as_completed(future_to_index):
            index, ok = future.result()
            if cancelled(cancel_event):
                raise OperationCancelled("download cancelled mid-flight")
            if not ok:
                failed_segments.append((index, tasks[index]["url"]))
            progress_bar.update(1)

    progress_bar.close()

    
    if failed_segments:
        print(f"[INFO] Retrying {len(failed_segments)} failed segments one last time...")
        for index, url in failed_segments[:]:
            task = tasks[index]
            try:
                if fetch_task(task, "60") and verify_task(task):
                    failed_segments.remove((index, url))
            except Exception as e:
                print(f"[DEBUG] Segment {index} final retry exception: {e}")
            time.sleep(_config_float("retry_delay", 2, minimum=0))

   
    if failed_segments:
        error_path = APP_ROOT / "error.txt"
        try:
            with open(error_path, "w", encoding="utf-8") as error_file:
                for index, url in failed_segments:
                    error_file.write(f"{index}: {url.strip()}\n")
        except OSError as exc:
            print(f"[WARN] Could not write failure report to {error_path}: {exc}")
        for index, url in failed_segments:
            print(f"[WARN] Segment {index} failed permanently after retries.")
        shutil.rmtree(base_temp_dir, ignore_errors=True)
        raise RuntimeError("Download failed: one or more segments could not be retrieved.")

   
    with open(output_path, 'wb') as out_file:
        # Copy in fixed-size chunks so peak memory stays flat regardless of
        # whether this is many small segments or one multi-hundred-MB file.
        for task in tasks:
            with open(task["path"], 'rb') as part:
                shutil.copyfileobj(part, out_file, length=1024 * 1024)

    if assembled_expected_size is not None:
        written = os.path.getsize(output_path)
        if written != assembled_expected_size:
            shutil.rmtree(base_temp_dir, ignore_errors=True)
            raise RuntimeError(
                f"Assembled file is truncated: expected {assembled_expected_size} bytes, wrote {written}."
            )

    shutil.rmtree(base_temp_dir, ignore_errors=True)

    print(f"[INFO] Downloaded and saved as: {output_path}")
    return output_path

def convert_vtt_to_srt_custom(vtt_path, srt_path):
    with open(vtt_path, "r", encoding="utf-8") as vtt_file:
        lines = vtt_file.readlines()

    srt_lines = []
    counter = 1
    buffer = []
    timestamp_line = None
    inside_style_block = False

    for line in lines:
        line = line.strip()

        if line.startswith("STYLE"):
            inside_style_block = True
            continue
        if inside_style_block:
            if line == "}":
                inside_style_block = False
            continue

        if line == "WEBVTT" or re.match(r"^c\d+$", line):
            continue

        if re.match(r"\d{2}:\d{2}:\d{2}\.\d{3} -->", line):
            if timestamp_line and buffer:
                srt_lines.append(f"{counter}")
                srt_lines.append(timestamp_line)
                srt_lines.extend(buffer)
                srt_lines.append("")
                counter += 1
                buffer = []

            
            timestamp_line = line.replace(".", ",")
            timestamp_line = re.sub(r" line:.*", "", timestamp_line)

        elif line == "":
            continue
        else:
            
            clean_line = re.sub(r"</?[^>]+>", "", line)
            buffer.append(clean_line)

    if timestamp_line and buffer:
        srt_lines.append(f"{counter}")
        srt_lines.append(timestamp_line)
        srt_lines.extend(buffer)
        srt_lines.append("")

    with open(srt_path, "w", encoding="utf-8") as srt_file:
        srt_file.write("\n".join(srt_lines))

    print(f"✅ Converted: {vtt_path} -> {srt_path}")

def parse_mpd_content(mpd_content):
    if isinstance(mpd_content, str):
        content = mpd_content.encode('utf-8')
    else:
        content = mpd_content

    root = etree.fromstring(content)
    namespace = {'ns': 'urn:mpeg:dash:schema:mpd:2011'}
    representations = root.findall(".//ns:Representation", namespace)

    video_list = []
    audio_list = []

    for elem in representations:
        rep_id = elem.attrib.get('id', '')
        bandwidth = int(elem.attrib.get('bandwidth', 0))
        codecs = elem.attrib.get('codecs', '')

        # width/height may be declared on the AdaptationSet and inherited, so
        # read the effective value. Otherwise a video Representation lands in
        # audio_list purely because its own element lacks the attributes.
        width = elem.attrib.get('width')
        height = elem.attrib.get('height')
        if not width or not height:
            ancestor = elem.getparent()
            while ancestor is not None and (not width or not height):
                if not width:
                    width = ancestor.attrib.get('width')
                if not height:
                    height = ancestor.attrib.get('height')
                ancestor = ancestor.getparent()
        width = int(width) if width else None
        height = int(height) if height else None

        base_url = get_mpd_base_url(elem)

        entry = {
            "name": rep_id,
            "bandwidth": bandwidth,
            "width": width,
            "height": height,
            "codecs": codecs,
            "base_url": base_url
        }
        # Every track in a license has its own key, so the caller needs to know
        # which key ID belongs to which rendition to pick the right one. It is
        # absent on unencrypted (free) renditions, which is not an error.
        kid = get_track_kid(elem)
        if kid:
            entry["kid"] = kid

        # Classify on effective dimensions first, then fall back to the declared
        # content type so a video track is never filed as audio.
        is_video = bool(width and height)
        if not is_video:
            adaptation = elem.getparent()
            mime = ""
            for node in (elem, adaptation):
                if node is not None and node.attrib.get('mimeType'):
                    mime = node.attrib['mimeType']
                    break
            content_type = elem.attrib.get('contentType', "") or ""
            codecs = str(elem.attrib.get('codecs', "") or "").lower()
            is_video = (mime.startswith("video") or content_type == "video"
                        or codecs.startswith(("avc", "hev", "hvc", "vp0", "vp8", "vp9", "av01", "av1")))

        if is_video:
            video_list.append(entry)
        else:
            audio_list.append(entry)

    return video_list, audio_list


def get_track_kid(element):
    """The default_KID for a Representation, falling back to its AdaptationSet.

    Crunchyroll namespaces the attribute, and the key can sit either directly on
    the AdaptationSet/Representation or on a cenc:ContentProtection child, so
    match on the local name.

    Two traps this avoids:
      - Only *direct* children are inspected. Walking the whole AdaptationSet
        subtree with iter() reaches sibling Representations, so a clear
        rendition would silently inherit a protected sibling's key ID and then
        be handed a key it does not need.
      - lxml exposes comments and processing instructions as nodes whose .tag
        is a callable, not a string, so .tag.endswith() raises AttributeError.
        A perfectly valid comment inside an MPD must not abort the parse.
    """
    scopes = [element]
    parent = element.getparent()
    if parent is not None and isinstance(parent.tag, str):
        scopes.append(parent)

    for scope in scopes:
        # The attribute may sit directly on the AdaptationSet/Representation.
        for attr, value in scope.attrib.items():
            if attr.split("}")[-1].lower() == "default_kid":
                kid = re.sub(r"[^0-9a-f]", "", value.lower())
                if len(kid) == 32:
                    return kid
        # ...or on a ContentProtection declared directly by this scope.
        for node in scope:
            if not isinstance(node.tag, str):
                continue  # comment / processing instruction
            if node.tag.split("}")[-1] != "ContentProtection":
                continue
            for attr, value in node.attrib.items():
                if attr.split("}")[-1].lower() == "default_kid":
                    kid = re.sub(r"[^0-9a-f]", "", value.lower())
                    if len(kid) == 32:
                        return kid
    return None

def parse_mpd_logic(content):
    try:
        if isinstance(content, str):
            content = content.encode('utf-8')

        root = etree.fromstring(content)
        namespaces = {'mpd': 'urn:mpeg:dash:schema:mpd:2011', 'cenc': 'urn:mpeg:cenc:2013'}

        videos = []
        for adaptation_set in root.findall('.//mpd:AdaptationSet[@contentType="video"]', namespaces):
            for representation in adaptation_set.findall('mpd:Representation', namespaces):
                videos.append({
                    'resolution': f"{representation.get('width')}x{representation.get('height')}",
                    'codec': representation.get('codecs'),
                    'mimetype': representation.get('mimeType')
                })

        audios = []
        for adaptation_set in root.findall('.//mpd:AdaptationSet[@contentType="audio"]', namespaces):
            for representation in adaptation_set.findall('mpd:Representation', namespaces):
                audios.append({
                    'audioSamplingRate': representation.get('audioSamplingRate'),
                    'codec': representation.get('codecs'),
                    'mimetype': representation.get('mimeType')
                })

        pssh_list = []
        widevine_pssh_list = []
        for content_protection in root.findall('.//mpd:ContentProtection', namespaces):
            pssh_element = content_protection.find('cenc:pssh', namespaces)
            if pssh_element is not None and pssh_element.text:
                scheme = content_protection.get('schemeIdUri', '').lower()
                pssh_text = pssh_element.text.strip()
                pssh_list.append(pssh_text)
                if 'edef8ba9-79d6-4ace-a3c8-27dcd51d21ed' in scheme:
                    widevine_pssh_list.append(pssh_text)

        return {"main_content": content.decode('utf-8'), "pssh": widevine_pssh_list or pssh_list}

    except etree.XMLSyntaxError as e:
        raise ValueError(f"Invalid MPD content: {e}")
    except Exception as e:
        raise RuntimeError(f"Unexpected error: {e}")
    
def parse_iso8601_duration(value):
    """Convert an ISO-8601 duration such as PT1H2M3.5S into seconds."""
    if not value:
        return 0.0

    match = re.fullmatch(
        r'P(?:(\d+(?:\.\d+)?)Y)?(?:(\d+(?:\.\d+)?)M)?(?:(\d+(?:\.\d+)?)D)?'
        r'(?:T(?:(\d+(?:\.\d+)?)H)?(?:(\d+(?:\.\d+)?)M)?(?:(\d+(?:\.\d+)?)S)?)?',
        value.strip()
    )
    if not match:
        return 0.0
    years, months, days, hours, minutes, seconds = (float(g or 0) for g in match.groups())
    return (
        years * 31536000 + months * 2592000 + days * 86400
        + hours * 3600 + minutes * 60 + seconds
    )


def get_mpd_base_url(elem):
    """Resolve the effective BaseURL for an element per DASH inheritance rules.

    The spec defines the effective BaseURL by resolving each level's BaseURL
    against its parent, outermost first: MPD, then Period, AdaptationSet and
    Representation. Walking up and returning the first hit found drops the outer
    components and silently yields relative URLs.
    """
    namespace = {'ns': 'urn:mpeg:dash:schema:mpd:2011'}
    chain = []
    current = elem
    while current is not None:
        base_url_elem = current.find('ns:BaseURL', namespace)
        if base_url_elem is not None and base_url_elem.text and base_url_elem.text.strip():
            chain.append(base_url_elem.text.strip())
        current = current.getparent()
    if not chain:
        return None

    resolved = ""
    for text in reversed(chain):          # outermost (MPD) level first
        if not resolved:
            resolved = text
            continue
        if re.match(r'^[A-Za-z][A-Za-z0-9+.\-]*:', text):
            # An absolute BaseURL replaces everything accumulated so far.
            resolved = text
            continue
        if not resolved.endswith('/'):
            # A BaseURL without a trailing slash names a file, so the child is
            # resolved against its directory.
            resolved += '/'
        resolved = urljoin(resolved, text)
    return resolved


def find_inherited(elem, tag, namespace):
    """Find a descendant-or-self `tag`, walking up to Period and MPD level.

    DASH allows SegmentTemplate, SegmentList and SegmentBase to be declared on
    the MPD, Period or AdaptationSet and inherited by each Representation, so a
    lookup that only inspects the Representation and its parent resolves nothing.
    """
    if elem is None:
        return None
    tag_q = f'{{{namespace["dash"]}}}{tag}'
    current = elem
    while current is not None and current.tag != tag_q:
        found = current.find(f'dash:{tag}', namespace)
        if found is not None:
            return found
        current = current.getparent()
    return None


def get_mpd_total_ticks(tree, period, segment_template):
    """Total presentation length of a period, in the segment template timescale."""
    timescale = int(segment_template.get('timescale', '1') or 1)
    seconds = 0.0
    if period is not None:
        seconds = parse_iso8601_duration(period.get('duration'))
    if not seconds and period is not None:
        start = period.get('start')
        if start:
            seconds = max(
                0.0,
                parse_iso8601_duration(tree.get('mediaPresentationDuration'))
                - parse_iso8601_duration(start),
            )
    if not seconds:
        seconds = parse_iso8601_duration(tree.get('mediaPresentationDuration'))
    return int(seconds * timescale)


def get_segment_link_list(mpd_content, representation_id, url="", period_id=None,
                          document_url=None):
    """Resolve the downloadable segment URLs for one DASH representation.

    Crunchyroll does not always ship the same addressing mode, so all of the
    common ones are handled: SegmentTimeline, fixed-duration SegmentTemplate,
    explicit SegmentList, and single-file SegmentBase. The result holds "init"
    (None when the stream has no separate initialization segment), "segments"
    (media segments only) and "all" (init first, then segments). An empty dict
    means the representation could not be resolved.
    """
    if isinstance(mpd_content, str):
        content = mpd_content.encode('utf-8')
    else:
        content = mpd_content

    try:
        tree = etree.fromstring(content)
    except etree.XMLSyntaxError as e:
        print(f"An error occurred: invalid MPD content: {e}")
        return {}

    ns = {'dash': 'urn:mpeg:dash:schema:mpd:2011'}

    try:
        # Ids are only unique within a Period. When several Periods reuse one,
        # resolving by id alone silently picks the first and downloads the wrong
        # rendition, so prefer a Period the caller identified.
        matches = tree.findall(f'.//dash:Representation[@id="{representation_id}"]', ns)
        if not matches:
            return {}
        representation = matches[0]
        if len(matches) > 1 and period_id:
            for candidate in matches:
                node = candidate
                while node is not None:
                    if node.tag == f'{{{ns["dash"]}}}Period' and node.get('id') == period_id:
                        representation = candidate
                        break
                    node = node.getparent()
                else:
                    continue
                break
        elif len(matches) > 1:
            print(f"[WARN] Representation id '{representation_id}' appears in "
                  f"{len(matches)} periods; using the first. Pass period_id to disambiguate.")

        adaptation_set = representation.getparent()
        period = representation
        while period is not None and period.tag != f'{{{ns["dash"]}}}Period':
            period = period.getparent()

        def find_first(tag):
            return find_inherited(representation, tag, ns)

        def merged_inherited(tag):
            """Element of `tag` with attributes merged across DASH inheritance.

            A SegmentTemplate may declare media/init on the AdaptationSet and
            only timeline/startNumber on the Representation. find_inherited()
            returns the nearest declaration, which silently dropped the parent's
            media and init and resolved to nothing, so merge attribute by
            attribute with the nearest declaration winning.
            """
            tag_q = f'{{{ns["dash"]}}}{tag}'
            levels, current = [], representation
            while current is not None:
                # A declaration may be the node itself (rare) or one of its children.
                declared = current if current.tag == tag_q else current.find(f'dash:{tag}', ns)
                if declared is not None:
                    levels.insert(0, declared)
                if current.tag == f'{{{ns["dash"]}}}MPD':
                    break
                current = current.getparent()
            if not levels:
                return None
            merged = etree.Element(tag_q)
            timeline = None
            for level in levels:
                for name, value in level.attrib.items():
                    merged.set(name, value)
                found_timeline = level.find('dash:SegmentTimeline', ns)
                if found_timeline is not None:
                    timeline = found_timeline
            merged.set('media', levels[-1].get('media', merged.get('media', '')))
            if timeline is not None:
                merged.append(timeline)
            return merged if (merged.get('media') or merged.get('initialization')) else None

        base = (url or "").strip()
        if not base:
            base = get_mpd_base_url(representation) or ""

        def absolute(path):
            resolved = urljoin(base, path) if base else path
            if document_url and not resolved.startswith(("http://", "https://")):
                resolved = urljoin(document_url, resolved)
            return resolved

        bandwidth = representation.get('bandwidth', '')

        def resolve_dash_template(template, number=None, time_val=None):
            pattern = r'\$(RepresentationID|Number|Bandwidth|Time)(%[0-9]*[di])?\$'
            def repl(m):
                key, fmt = m.group(1), m.group(2)
                if key == 'RepresentationID':
                    val = representation_id
                elif key == 'Bandwidth':
                    val = bandwidth
                elif key == 'Number':
                    if number is None:
                        return m.group(0)
                    val = number
                elif key == 'Time':
                    if time_val is None:
                        return m.group(0)
                    val = time_val
                else:
                    return m.group(0)
                return fmt % int(val) if fmt else str(val)
            return re.sub(pattern, repl, template)

        # Single-file segmented asset: the base URL already is the full stream.
        if find_first('SegmentBase') is not None:
            if not base:
                return {}
            return {"init": None, "segments": [base], "all": [base]}

        # Explicit segment list.
        segment_list = find_first('SegmentList')
        if segment_list is not None:
            initialization = segment_list.find('dash:Initialization', ns)
            init_url = None
            if initialization is not None and initialization.get('sourceURL'):
                init_url = absolute(initialization.get('sourceURL'))
            segments = [
                absolute(segment.get('media'))
                for segment in segment_list.findall('dash:SegmentURL', ns)
                if segment.get('media')
            ]
            if not segments:
                return {}
            return {
                "init": init_url,
                "segments": segments,
                "all": ([init_url] if init_url else []) + segments,
            }

        segment_template = merged_inherited('SegmentTemplate')
        if segment_template is None:
            segment_template = find_first('SegmentTemplate')
        if segment_template is None:
            return {}

        media_template = segment_template.get('media')
        if not media_template:
            return {}

        init_template = segment_template.get('initialization')
        init_url = absolute(resolve_dash_template(init_template)) if init_template else None
        segment_timeline = segment_template.find('dash:SegmentTimeline', ns)
        start_number = int(segment_template.get('startNumber', '1') or 1)
        time_offset = int(segment_template.get('presentationTimeOffset', '0') or 0)

        segments = []
        if segment_timeline is not None:
            total_ticks = get_mpd_total_ticks(tree, period, segment_template)
            current_time = 0
            timeline_entries = segment_timeline.findall('dash:S', ns)
            for entry_index, segment in enumerate(timeline_entries):
                t_attr = segment.get('t')
                if t_attr is not None:
                    current_time = int(t_attr)
                d_attr = segment.get('d')
                r_attr = segment.get('r')
                if not d_attr:
                    continue
                duration = int(d_attr)

                if r_attr is not None:
                    repeat_count = int(r_attr)
                    if repeat_count < 0:
                        # r="-1" means "repeat until the end of the Period". It has
                        # to be derived from the period length; treating it as
                        # r+1 yields zero repeats and truncates the episode.
                        # r="-1" repeats up to the *next* S entry's start
                        # time; the Period length is only the fallback when
                        # this is the last entry. Bounding by the Period here
                        # generated every segment up to the end of the show.
                        bound = None
                        for later in timeline_entries[entry_index + 1:]:
                            later_t = later.get('t')
                            if later_t is not None:
                                bound = int(later_t)
                                break
                        if bound is None:
                            bound = total_ticks
                        if duration <= 0 or bound <= current_time:
                            repeat_count = 0
                        else:
                            remaining = bound - current_time
                            repeat_count = -(-remaining // duration)
                    else:
                        repeat_count += 1
                else:
                    repeat_count = 1

                for _ in range(repeat_count):
                    segments.append(absolute(resolve_dash_template(
                        media_template,
                        number=len(segments) + start_number,
                        time_val=current_time
                    )))
                    current_time += duration
        elif segment_template.get('duration'):
            segment_duration = int(segment_template.get('duration'))
            total_ticks = get_mpd_total_ticks(tree, period, segment_template)
            if segment_duration > 0:
                for index in range(-(-total_ticks // segment_duration)):
                    segments.append(absolute(resolve_dash_template(
                        media_template,
                        number=index + start_number,
                        time_val=time_offset + index * segment_duration
                    )))
        else:
            return {}

        if not segments:
            return {}

        return {
            "init": init_url,
            "segments": segments,
            "all": ([init_url] if init_url else []) + segments,
        }
    except Exception as e:
        print(f"An error occurred: {e}")
        return {}


def get_episode_display_number(episode, fallback):
    metadata = episode.get("episode_metadata") or {}
    return (
        episode.get("episode_number")
        or metadata.get("episode_number")
        or metadata.get("episode")
        or fallback
    )


def get_episode_title(episode, fallback):
    return episode.get("title") or f"Episode {get_episode_display_number(episode, fallback)}"


def get_episode_season_title(episode):
    metadata = episode.get("episode_metadata") or {}
    return (
        episode.get("season_title")
        or metadata.get("season_title")
        or episode.get("_season_title")
        or ""
    )


def parse_episode_selection(selection, total):
    selection = (selection or "").strip().lower()
    if not selection:
        raise ValueError("empty episode selection")
    if selection in ("all", "*"):
        return list(range(total))

    if re.fullmatch(r"\d+", selection):
        count = int(selection)
        if count < 1 or count > total:
            raise ValueError(f"number must be between 1 and {total}")
        return list(range(count))

    selected = []
    seen = set()
    for part in selection.split(","):
        part = part.strip()
        if not part:
            continue
        range_match = re.fullmatch(r"(\d+)\s*-\s*(\d+)", part)
        if range_match:
            start = int(range_match.group(1))
            end = int(range_match.group(2))
            if start > end:
                raise ValueError("episode ranges must go from low to high")
            numbers = range(start, end + 1)
        elif re.fullmatch(r"\d+", part):
            numbers = [int(part)]
        else:
            raise ValueError("use numbers, commas, ranges, or all")

        for number in numbers:
            if number < 1 or number > total:
                raise ValueError(f"episode {number} is outside 1-{total}")
            index = number - 1
            if index not in seen:
                selected.append(index)
                seen.add(index)

    if not selected:
        raise ValueError("empty episode selection")
    return selected


def _write_secret_json(path, data):
    """Atomically write a credential file that is never briefly world-readable.

    Opening with mode 0o600 from the start avoids the window in which a token
    sits on disk with default permissions, and writing to a temporary file before
    os.replace() means a crash or a concurrent writer can never leave a torn,
    permanently-unreadable cache behind.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = None
    tmp_path = None
    try:
        fd, tmp_name = tempfile.mkstemp(
            prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
        )
        tmp_path = Path(tmp_name)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            fd = None
            json.dump(data, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
        tmp_path = None
        with contextlib.suppress(Exception):
            os.chmod(path, 0o600)
        return True
    except Exception:
        return False
    finally:
        if fd is not None:
            with contextlib.suppress(Exception):
                os.close(fd)
        if tmp_path is not None:
            with contextlib.suppress(Exception):
                os.remove(tmp_path)


class CrunchyrollAuth(CrunchyrollBase):
    def __init__(self):
        super().__init__()
        self.playback_endpoint = None
        self.playback_user_agent = None
        self.last_auth_error = None
        self.last_auth_context = None
        self.last_token_payload = {}
        # Result of the (now defunct) community auth-data lookup, cached so the
        # request is made at most once per instance.
        self._crd_auth_cache = None

    def _set_auth_headers(self, authorization_header, user_agent, extra_headers=None):
        headers = {
            "Accept": "application/json",
            "Accept-Charset": "UTF-8",
            "Connection": "Keep-Alive",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "ETP-Anonymous-ID": str(uuid.uuid4()),
            "User-Agent": user_agent,
            "X-Datadog-Sampling-Priority": "0",
        }
        if authorization_header:
            headers["Authorization"] = authorization_header
        if extra_headers:
            headers.update(extra_headers)
        self.set_headers(headers, replace=True)

    def _set_last_auth_error(self, context, response=None, message=None):
        self.last_auth_context = context
        if message:
            self.last_auth_error = message
            return
        if response is None:
            self.last_auth_error = None
            return
        try:
            payload = response.json()
        except Exception:
            self.last_auth_error = response.text[:500]
            return
        parts = []
        for key in ("error", "error_description", "message", "code"):
            value = payload.get(key)
            if value and value not in parts:
                parts.append(value)
        for item in payload.get("context") or []:
            if not isinstance(item, dict):
                continue
            value = item.get("code") or item.get("message")
            if value and value not in parts:
                parts.append(value)
        self.last_auth_error = "; ".join(parts) or json.dumps(payload)[:500]

    def _token_cache_dir(self):
        configured_dir = _config_value(
            "crunchyroll_token_cache_dir",
            "CRUNCHYROLL_TOKEN_CACHE_DIR",
            "token_cache_dir",
            "TOKEN_CACHE_DIR",
        )
        cache_dir = Path(configured_dir).expanduser() if configured_dir else Path(__file__).resolve().parent / ".crunchyroll_tokens"
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir

    def _token_cache_path(self, profile):
        name = re.sub(r"[^a-zA-Z0-9_.-]+", "_", profile["name"])
        return self._token_cache_dir() / f"{name}.json"

    def _etp_rt_cache_path(self):
        return self._token_cache_dir() / "etp_rt.json"

    def _read_etp_rt_cache(self):
        path = self._etp_rt_cache_path()
        if not path.is_file():
            return {}
        try:
            with path.open("r", encoding="utf-8") as token_file:
                payload = json.load(token_file)
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _normalize_account(value):
        return str(value or "").strip().lower()

    def _cache_matches_account(self, payload, email):
        """Only reuse a cached token for the account it was issued to."""
        if not email:
            return True
        cached = self._normalize_account((payload or {}).get("account"))
        if not cached:
            return False
        return cached == self._normalize_account(email)

    def _write_etp_rt_cache(self, payload, etp_rt, device_id, account=None):
        if not payload:
            return
        token_payload = dict(payload)
        token_payload["device_id"] = device_id
        token_payload["etp_rt"] = etp_rt
        # Default to the account currently logging in so every writer stamps it,
        # including the etp_rt/refresh paths that have no account argument.
        account = account or getattr(self, "last_login_account", None)
        if account:
            token_payload["account"] = self._normalize_account(account)
        if token_payload.get("expires_in"):
            token_payload["expires_at"] = int(time.time()) + int(token_payload["expires_in"])
        try:
            path = self._etp_rt_cache_path()
        except Exception:
            return
        _write_secret_json(path, token_payload)

    def _configured_etp_rt(self):
        return str(_config_value("etp_rt_token", "CRUNCHYROLL_ETP_RT", "ETP_RT") or "").strip()

    def _crd_token_paths(self, profile):
        configured_dir = _config_value("crd_token_dir", "CRD_TOKEN_DIR", "crd_config_dir", "CRD_CONFIG_DIR")
        token_dirs = []
        if configured_dir:
            token_dirs.append(Path(configured_dir).expanduser())
        token_dirs.extend([
            Path.cwd() / "config",
            Path(__file__).resolve().parent / "config",
            Path("/tmp/crd_release/config"),
            Path.home() / "test" / "Crunchy-Downloader" / "config",
            Path.home() / "test" / "multi-downloader-nx" / "config",
            Path.home() / ".config" / "Crunchy-Downloader" / "config",
            Path.home() / ".config" / "Crunchy-Downloader",
        ])

        if profile["endpoint"] == "tv/android_tv":
            names = ("cr_token_tv.json", "cr_token.json", "cr_token.yml")
        elif profile["endpoint"].startswith("android/"):
            names = ("cr_token_android.json", "cr_token.json", "cr_token.yml")
        else:
            names = ("cr_token.json", "cr_token.yml")

        seen = set()
        paths = []
        for directory in token_dirs:
            for name in names:
                path = directory / name
                key = str(path)
                if key not in seen:
                    seen.add(key)
                    paths.append(path)
        return paths

    def _read_crd_token(self, profile):
        for token_path in self._crd_token_paths(profile):
            if not token_path.is_file():
                continue
            try:
                with token_path.open("r", encoding="utf-8") as token_file:
                    if token_path.suffix.lower() in (".yml", ".yaml"):
                        import yaml
                        payload = yaml.safe_load(token_file) or {}
                    else:
                        payload = json.load(token_file)
                if not isinstance(payload, dict) or not payload.get("refresh_token"):
                    continue
                if payload.get("expires") and not payload.get("expires_at"):
                    with contextlib.suppress(Exception):
                        payload["expires_at"] = _datetime_to_timestamp(payload["expires"])
                cr_debug(f"loaded CRD token file for {profile['name']}: {token_path}")
                return payload
            except Exception as error:
                cr_debug(f"failed to read CRD token file {token_path}: {error}")
        return {}

    def _read_cached_token(self, profile):
        try:
            cache_path = self._token_cache_path(profile)
            if not cache_path.is_file():
                return self._read_crd_token(profile)
            with cache_path.open("r", encoding="utf-8") as token_file:
                payload = json.load(token_file)
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}

    def _write_cached_token(self, profile, payload, device_id, account=None):
        if not isinstance(payload, dict):
            return
        token_payload = dict(payload)
        token_payload["device_id"] = device_id
        if account:
            token_payload["account"] = self._normalize_account(account)
        if token_payload.get("expires_in"):
            token_payload["expires_at"] = int(time.time()) + int(token_payload["expires_in"])
        try:
            cache_path = self._token_cache_path(profile)
        except Exception:
            return
        _write_secret_json(cache_path, token_payload)

    @staticmethod
    def _has_valid_access_token(payload):
        if not payload.get("access_token"):
            return False
        expires_at = payload.get("expires_at")
        if not expires_at:
            return False
        return int(expires_at) > int(time.time()) + 60

    def _payload_from_response(self, auth_response, context):
        if auth_response.status_code != 200:
            self._set_last_auth_error(context, response=auth_response)
            return {}
        try:
            auth_response_payload = auth_response.json()
        except Exception:
            self._set_last_auth_error(context, message=f"non-json response: {auth_response.text[:500]}")
            return {}

        access_token = auth_response_payload.get("access_token")
        if not access_token:
            self._set_last_auth_error(context, message="access token not received")
            return {}
        self._set_last_auth_error(context)
        return auth_response_payload

    @staticmethod
    def _client_credentials_from_profile(profile):
        basic_token = profile.get("basic_token")
        if not basic_token:
            return None, None
        decoded = base64.b64decode(basic_token).decode("utf-8")
        client_id, client_secret = decoded.split(":", 1)
        return client_id, client_secret

    def _post_token_payload(self, data, authorization_header, user_agent, context, extra_headers=None):
        self._set_auth_headers(authorization_header, user_agent, extra_headers=extra_headers)
        auth_response = self.request("post", f"{CR_API_BASE}/auth/v1/token", data=data)
        cr_debug(f"auth {context}: status={auth_response.status_code}")
        return self._payload_from_response(auth_response, context)

    def _post_profile_token_payload(self, profile, data, context):
        post_data = dict(data)
        authorization = profile.get("authorization")
        extra_headers = None
        if profile.get("client_form"):
            client_id, client_secret = self._client_credentials_from_profile(profile)
            post_data["client_id"] = client_id
            post_data["client_secret"] = client_secret
            authorization = None
            if post_data.get("grant_type") in ("password", "client_id"):
                extra_headers = {"Request-Type": "SignIn"}
        return self._post_token_payload(
            post_data,
            authorization,
            profile["user_agent"],
            context,
            extra_headers=extra_headers,
        )

    def _fetch_crd_auth_json(self):
        """Fetch the community auth data once per instance.

        The upstream Crunchy-DL/Crunchy-Downloader project is gone (the Pages
        site and the repository both answer 404), so this previously burned two
        round-trips on every single authenticate() call only to fall back to the
        built-in profiles. The outcome, including failure, is cached so the cost
        is paid at most once.
        """
        if self._crd_auth_cache is not None:
            return self._crd_auth_cache

        urls = []
        configured_url = _config_value("crd_auth_data_url", "CRD_AUTH_DATA_URL")
        if configured_url:
            urls.append(configured_url)
        urls.extend(CRD_AUTH_DATA_URLS)

        if _config_value("disable_crd_auth_updates", "DISABLE_CRD_AUTH_UPDATES"):
            self._crd_auth_cache = []
            return self._crd_auth_cache

        for url in urls:
            try:
                response = self.request("get", url, headers={"User-Agent": "C# App"})
                cr_debug(f"CRD auth data {url}: status={response.status_code}")
                if response.status_code != 200:
                    continue
                payload = response.json()
                if isinstance(payload, list):
                    self._crd_auth_cache = payload
                    return self._crd_auth_cache
            except Exception as error:
                cr_debug(f"CRD auth data {url}: {error}")

        cr_debug("CRD auth data unavailable; using built-in auth profiles")
        self._crd_auth_cache = []
        return self._crd_auth_cache

    def _profiles_with_crd_updates(self):
        profiles = [dict(profile) for profile in CR_AUTH_PROFILES]
        gh_auth = self._fetch_crd_auth_json()
        if not gh_auth:
            return profiles

        for item in gh_auth:
            if not isinstance(item, dict):
                continue
            item_type = str(item.get("Type") or item.get("type") or "").lower()
            authorization = item.get("Authorization") or item.get("authorization")
            version = item.get("VersionName") or item.get("versionName") or item.get("version_name")
            if not authorization or not version:
                continue
            for profile in profiles:
                if item_type == "tv" and profile["endpoint"] == "tv/android_tv":
                    if _version_tuple(version) > _version_tuple(profile["user_agent"]):
                        profile["authorization"] = authorization
                        profile["user_agent"] = f"ANDROIDTV/{version} Android/16"
                        cr_debug(f"using CRD tv auth version {version}")
                if item_type == "mobile" and profile["endpoint"] == "android/phone":
                    if _version_tuple(version) > _version_tuple(profile["user_agent"]):
                        profile["authorization"] = authorization
                        profile["user_agent"] = f"Crunchyroll/{version} Android/16 okhttp/4.12.0"
                        cr_debug(f"using CRD mobile auth version {version}")
        return profiles

    def _refresh_cached_token(self, profile, cached_payload):
        refresh_token = cached_payload.get("refresh_token")
        if not refresh_token:
            return {}
        device_id = cached_payload.get("device_id") or str(uuid.uuid4())
        data = {
            "refresh_token": refresh_token,
            "scope": "offline_access",
            "device_id": device_id,
            "grant_type": "refresh_token",
            "device_type": profile["device_type"],
            "device_name": profile["device_name"],
        }
        payload = self._post_profile_token_payload(profile, data, f"{profile['name']} refresh")
        if payload:
            self._write_cached_token(profile, payload, device_id)
        return payload

    def _password_login(self, profile, email, password):
        device_id = str(uuid.uuid4())
        data = {
            "username": email,
            "password": password,
            "grant_type": "password",
            "scope": "offline_access",
            "device_id": device_id,
            "device_type": profile["device_type"],
            "device_name": profile["device_name"],
        }
        payload = self._post_profile_token_payload(profile, data, f"{profile['name']} password")
        if payload:
            self._write_cached_token(profile, payload, device_id, account=email)
        return payload

    @staticmethod
    def _client_id_from_basic(authorization):
        token = authorization.removeprefix("Basic ").strip()
        decoded = base64.b64decode(token).decode("utf-8")
        return decoded.split(":", 1)[0]

    @staticmethod
    def _generate_code_verifier(length=64):
        allowed = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
        return "".join(random.choice(allowed) for _ in range(length))

    @staticmethod
    def _extract_oauth_code(body):
        text = (body or "").replace("\\u0026", "&").replace('\\"', '"')
        for pattern in (
            r"(?:[?&]|\\u0026)code=([A-Za-z0-9\-_]+)",
            r"code=([A-Za-z0-9\-_]+)",
            r'"code"\s*:\s*"([A-Za-z0-9\-_]+)"',
        ):
            match = re.search(pattern, text)
            if match:
                return match.group(1)
        return ""

    def _sso_password_login(self, email, password):
        payload = json.dumps({"email": email, "password": password, "eventSettings": {}})
        headers = {
            "Content-Type": "text/plain; charset=UTF-8",
            "User-Agent": CR_OAUTH_USER_AGENT,
        }
        try:
            response = _http_request(
                "post",
                CR_SSO_LOGIN_URL,
                data=payload,
                headers=headers,
                timeout=60,
            )
        except Exception as exc:
            self._set_last_auth_error("sso_login", message=str(exc))
            return None

        cr_debug(f"auth sso_login: status={response.status_code}")
        if response.status_code != 200:
            self._set_last_auth_error("sso_login", response=response)
            return None

        etp_rt = response.cookies.get("etp_rt")
        if not etp_rt:
            self._set_last_auth_error("sso_login", message="etp_rt cookie not received")
            return None
        return str(etp_rt)

    def _oauth_code_login(self, etp_rt):
        client_id = self._client_id_from_basic(CR_OAUTH_CLIENT_AUTH)
        code_verifier = self._generate_code_verifier()
        auth_device_id = str(uuid.uuid4())
        query = {
            "client_id": client_id,
            "redirect_uri": "sso.crunchyroll://auth",
            "response_type": "code",
            "scope": "offline_access",
            "state": '{"flow":"SIGN_IN","flowRoot":"ONBOARDING"}',
            "code_challenge": code_verifier,
            "code_challenge_method": "plain",
        }
        authorize_url = f"{CR_SSO_AUTHORIZE_URL}?{urlencode(query)}"
        cookies = {
            "client_id": client_id,
            "device_id": auth_device_id,
            "etp_rt": etp_rt,
            "c_locale": "en-US",
        }
        try:
            response = _http_request(
                "get",
                authorize_url,
                headers={"User-Agent": CR_OAUTH_USER_AGENT},
                cookies=cookies,
                timeout=60,
                allow_redirects=True,
            )
        except Exception as exc:
            self._set_last_auth_error("sso_authorize", message=str(exc))
            return {}

        auth_code = self._extract_oauth_code(response.text or "")
        if not auth_code and "code=" in (response.url or ""):
            auth_code = self._extract_oauth_code(response.url or "")
        if not auth_code:
            self._set_last_auth_error("sso_authorize", message="authorization code not found")
            return {}

        device_id = str(uuid.uuid4())
        data = {
            "code": auth_code,
            "code_verifier": code_verifier,
            "grant_type": "authorization_code",
            "scope": "offline_access",
            "device_id": device_id,
            "device_type": "ANDROIDTV",
            "device_name": "emu64xa",
        }
        headers = {
            "Authorization": CR_OAUTH_CLIENT_AUTH,
            "User-Agent": CR_OAUTH_USER_AGENT,
            "Content-Type": "application/x-www-form-urlencoded",
            "Request-Type": "SignIn",
        }
        token_cookies = {"etp_rt": etp_rt, "c_locale": "en-US"}
        try:
            token_response = _http_request(
                "post",
                f"{CR_API_BASE}/auth/v1/token",
                data=data,
                headers=headers,
                cookies=token_cookies,
                timeout=60,
            )
        except Exception as exc:
            self._set_last_auth_error("sso_authorization_code", message=str(exc))
            return {}

        cr_debug(f"auth sso_authorization_code: status={token_response.status_code}")
        payload = self._payload_from_response(token_response, "sso_authorization_code")
        if payload:
            payload["device_id"] = device_id
            payload["etp_rt"] = etp_rt
            self.playback_endpoint = "tv/android_tv"
            self.playback_user_agent = CR_OAUTH_USER_AGENT
        return payload

    def get_etp_rt_token(self, etp_rt=None, force_refresh=False):
        cached = self._read_etp_rt_cache()
        if not force_refresh and self._has_valid_access_token(cached):
            self.playback_endpoint = "web/chrome"
            self.playback_user_agent = CR_ETP_USER_AGENT
            self.last_token_payload = cached
            return cached["access_token"]

        refresh_token = (
            etp_rt
            or self._configured_etp_rt()
            or cached.get("etp_rt")
            or cached.get("refresh_token")
            or ""
        ).strip()
        if not refresh_token:
            return None

        device_id = cached.get("device_id") or "4242c96b-e0fa-4d85-a217-7ad92d64a282"
        headers = {
            "Authorization": CR_ETP_AUTHORIZATION,
            "User-Agent": CR_ETP_USER_AGENT,
            "Content-Type": "application/x-www-form-urlencoded",
        }
        cookies = {"etp_rt": refresh_token, "c_locale": "en-US"}
        data = {
            "grant_type": "etp_rt_cookie",
            "device_id": device_id,
            "device_type": CR_ETP_DEVICE_TYPE,
        }
        response = self.request(
            "post",
            CR_ETP_TOKEN_URL,
            data=data,
            headers=headers,
            cookies=cookies,
        )
        cr_debug(f"auth etp_rt_cookie: status={response.status_code}")
        payload = self._payload_from_response(response, "etp_rt_cookie")
        if not payload:
            return None

        new_etp_rt = refresh_token
        if hasattr(response, "cookies"):
            cookie_etp_rt = response.cookies.get("etp_rt")
            if cookie_etp_rt:
                new_etp_rt = str(cookie_etp_rt)

        self.playback_endpoint = "web/chrome"
        self.playback_user_agent = CR_ETP_USER_AGENT
        self.last_token_payload = payload
        self._write_etp_rt_cache(payload, new_etp_rt, device_id)
        return payload.get("access_token")

    def _password_login_via_sso(self, email, password):
        etp_rt = self._sso_password_login(email, password)
        if not etp_rt:
            return None

        token = self.get_etp_rt_token(etp_rt=etp_rt, force_refresh=True)
        if token:
            return token

        payload = self._oauth_code_login(etp_rt)
        if not payload:
            return None

        self.last_token_payload = payload
        self._write_etp_rt_cache(payload, etp_rt,
                                 str(payload.get("device_id") or uuid.uuid4()),
                                 account=self.last_login_account)
        return payload.get("access_token")

    def get_password_token(self, email, password, force_refresh=False):
        if email:
            self.last_login_account = self._normalize_account(email)
        if not force_refresh:
            cached = self._read_etp_rt_cache()
            # A cache written for another account must never satisfy this login.
            if self._has_valid_access_token(cached) and self._cache_matches_account(cached, email):
                self.playback_endpoint = "web/chrome"
                self.playback_user_agent = CR_ETP_USER_AGENT
                self.last_token_payload = cached
                return cached["access_token"]

        sso_token = self._password_login_via_sso(email, password)
        if sso_token:
            return sso_token

        account_error = self.last_auth_error
        account_context = self.last_auth_context
        auth_profiles = self._profiles_with_crd_updates()
        for profile in auth_profiles:
            cached_payload = self._read_cached_token(profile)
            if (not force_refresh and self._has_valid_access_token(cached_payload)
                    and self._cache_matches_account(cached_payload, email)):
                self.playback_endpoint = profile["endpoint"]
                self.playback_user_agent = profile["user_agent"]
                self.last_token_payload = cached_payload
                return cached_payload["access_token"]
            refreshed_payload = self._refresh_cached_token(profile, cached_payload)
            if refreshed_payload:
                self.playback_endpoint = profile["endpoint"]
                self.playback_user_agent = profile["user_agent"]
                self.last_token_payload = refreshed_payload
                return refreshed_payload["access_token"]
            payload = self._password_login(profile, email, password)
            if payload:
                self.playback_endpoint = profile["endpoint"]
                self.playback_user_agent = profile["user_agent"]
                self.last_token_payload = payload
                return payload["access_token"]
            account_error = self.last_auth_error or account_error
            account_context = self.last_auth_context or account_context

        if account_error:
            self.last_auth_error = account_error
            self.last_auth_context = account_context
        return None

    def authenticate(self, email="", password="", etp_rt=None, allow_guest_fallback=False, force_refresh=False):
        token = self.get_etp_rt_token(etp_rt=etp_rt or self._configured_etp_rt() or None, force_refresh=force_refresh)
        if token:
            return token
        if email and password:
            token = self.get_password_token(email, password, force_refresh=force_refresh)
            if token:
                return token
        if allow_guest_fallback:
            return self.get_guest_token()
        return None

    def get_guest_token(self):
        self.playback_endpoint = "web/firefox"
        self.playback_user_agent = CR_WEB_USER_AGENT
        data = {
            "grant_type": "client_id",
            "scope": "offline_access",
        }
        payload = self._post_token_payload(data, CR_WEB_AUTHORIZATION, CR_WEB_USER_AGENT, "guest")
        if payload:
            self.last_token_payload = payload
        return payload.get("access_token")

    def get_user_token(self, email, password, allow_guest_fallback=True, force_refresh=False):
        self.playback_endpoint = None
        return self.authenticate(
            email,
            password,
            etp_rt=self._configured_etp_rt() or None,
            allow_guest_fallback=allow_guest_fallback,
            force_refresh=force_refresh,
        )

def get_filter_complex():
    target_font = config_value("fontfile")
    if not os.path.isabs(target_font):
        app_font = os.path.join(os.path.dirname(os.path.abspath(__file__)), config_value("fontfile"))
        if os.path.isfile(app_font):
            target_font = app_font
    if os.name == "nt":
        target_font = target_font.replace("\\", "/").replace(":", "\\:")

    return (
        f"[0:v]drawtext=text='{config_value('Watermark_Name')}':"
        f"fontfile={target_font}:"
        f"fontcolor={config_value('fontcolor')}@{config_value('opaque')}:" 
        f"fontsize={config_value('fontsize')}:"
        f"x={config_value('x_axis')}:"
        f"y={config_value('y_axis')}[v]"
    )


class EncodingConfig:
    def __init__(
        self,
        mode="lossy",
        video_codec="libx265",
        audio_codec="copy",
        extra_video_args=None,
        extra_audio_args=None,
        use_watermark=False,
        crf=20,
        preset="medium",
        pix_fmt="yuv420p10le",
        output_format="mkv",
    ):
        self.mode = mode
        self.video_codec = video_codec
        self.audio_codec = audio_codec
        self.extra_video_args = list(extra_video_args or [])
        self.extra_audio_args = list(extra_audio_args or [])
        self.use_watermark = use_watermark
        self.crf = crf
        self.preset = preset
        self.pix_fmt = pix_fmt
        self.output_format = output_format

    def get_ffmpeg_args_list(self):
        """Return list of FFmpeg arguments for encoding and muxing."""
        args = ["-c:v", self.video_codec]
        args.extend(self.extra_video_args)
        args.extend(["-c:a", self.audio_codec])
        args.extend(self.extra_audio_args)
        args.extend(["-c:s", "copy"])
        return args

    def get_ffmpeg_args_str(self):
        """Return FFmpeg argument string for CLI command concatenation."""
        return " ".join(self.get_ffmpeg_args_list())

    def summary(self):
        """Return human-readable summary of encoding configuration."""
        wm_text = "ON" if self.use_watermark else "OFF"
        if self.mode == "lossless":
            wm_note = " (auto-disabled for lossless stream copy)" if not self.use_watermark else ""
            return f"Mode: LOSSLESS (remux/stream copy) | Video: copy | Audio: copy | Watermark: {wm_text}{wm_note}"
        elif self.mode == "lossy":
            # "lossless stream copy" is only true when audio is actually copied;
            # a real encoder re-encodes, so claiming otherwise misleads.
            codec = str(self.audio_codec or "copy").lower()
            audio_note = ("lossless stream copy" if codec == "copy"
                          else f"re-encoded to {self.audio_codec}")
            return (
                f"Mode: LOSSY (H.265 10-bit) | Video: {self.video_codec} (CRF {self.crf}, preset {self.preset}, {self.pix_fmt}) "
                f"| Audio: {self.audio_codec} ({audio_note}) | Watermark: {wm_text}"
            )
        else:
            return f"Mode: CUSTOM | Video: {self.video_codec} | Audio: {self.audio_codec} | Watermark: {wm_text}"


def resolve_encoding_config(
    mode=None,
    use_watermark=None,
    original_quality=None,
    encoding_code=None,
    audio_codec=None,
    crf=None,
    preset=None,
    pix_fmt=None,
    output_format=None,
):
    """
    Resolve video/audio encoding settings based on user-configured mode.

    Modes:
      - 'lossy' / 'lossyy' / 'h265': H.265 (HEVC) 10-bit video encoding (libx265, yuv420p10le,
        CRF 20, preset medium) for 40-60% smaller file size with visually lossless quality,
        combined with direct stream copy audio (zero audio quality loss). Watermarking supported.
      - 'lossless' / 'losslessy' / 'original': Direct stream copy (remux) for both video and audio.
        Bit-for-bit identical to source, ultra-fast. Watermarking is disabled to prevent re-encoding.
      - 'custom': User-defined video and audio codecs and parameters.
    """
    import config

    # An explicitly requested mode (--lossy/--lossless/--mode=) must win over the
    # legacy original_quality switch; otherwise `--lossy` silently did nothing
    # whenever original_quality was enabled in config.
    mode_explicit = mode is not None
    if mode is None:
        mode = getattr(config, "encoding_mode", "lossy")
    if original_quality is None:
        original_quality = _as_bool(getattr(config, "original_quality", False))
    if use_watermark is None:
        use_watermark = _as_bool(getattr(config, "use_watermark", False))
    if encoding_code is None:
        encoding_code = getattr(config, "encoding_code", "libx265")
    if audio_codec is None:
        audio_codec = getattr(config, "audio_codec", "copy")
    if crf is None:
        crf = getattr(config, "crf", 20)
    if preset is None:
        preset = getattr(config, "preset", "medium")
    if pix_fmt is None:
        pix_fmt = getattr(config, "pix_fmt", "yuv420p10le")
    if output_format is None:
        output_format = getattr(config, "output_format", "mkv")

# Determine normalized mode
    if original_quality and not mode_explicit:
        norm_mode = "lossless"
    else:
        norm_mode = str(mode).strip().lower() if mode else "lossy"
        if norm_mode in ("lossless", "losslessy", "original", "remux", "copy"):
            norm_mode = "lossless"
        elif norm_mode in ("lossy", "lossyy", "h265", "h265_10bit", "hevc", "compressed"):
            norm_mode = "lossy"
        elif norm_mode in ("custom", "manual"):
            norm_mode = "custom"
        else:
            norm_mode = "lossy"

    effective_watermark = bool(use_watermark)
    extra_video_args = []
    extra_audio_args = []

    if norm_mode == "lossless":
        video_codec = "copy"
        audio_codec = "copy"
        if effective_watermark:
            print("[INFO] Lossless mode selected: direct stream copy is used, watermarking disabled to prevent re-encoding.")
            effective_watermark = False

    elif norm_mode == "lossy":
        video_codec = "libx265"
        # Preserve original audio without re-encoding to avoid generation loss
        audio_codec = audio_codec or "copy"
        crf_val = str(crf if crf is not None else 20)
        preset_val = str(preset or "medium")
        pix_fmt_val = str(pix_fmt or "yuv420p10le")
        extra_video_args = ["-pix_fmt", pix_fmt_val, "-crf", crf_val, "-preset", preset_val]
        if str(output_format).lower() == "mp4":
            extra_video_args.extend(["-tag:v", "hvc1"])

    else:  # custom
        video_codec = str(encoding_code or "libx265")
        audio_codec = str(audio_codec or "copy")
        if video_codec == "copy":
            if effective_watermark:
                print("[INFO] Video codec is 'copy': watermarking disabled to prevent re-encoding.")
                effective_watermark = False
        elif video_codec == "libx265":
            crf_val = str(crf if crf is not None else 20)
            preset_val = str(preset or "medium")
            pix_fmt_val = str(pix_fmt or "yuv420p10le")
            extra_video_args = ["-pix_fmt", pix_fmt_val, "-crf", crf_val, "-preset", preset_val]
            if str(output_format).lower() == "mp4":
                extra_video_args.extend(["-tag:v", "hvc1"])
        elif video_codec == "libx264":
            crf_val = str(crf if crf is not None else 23)
            preset_val = str(preset or "medium")
            extra_video_args = ["-crf", crf_val, "-preset", preset_val]

    return EncodingConfig(
        mode=norm_mode,
        video_codec=video_codec,
        audio_codec=audio_codec,
        extra_video_args=extra_video_args,
        extra_audio_args=extra_audio_args,
        use_watermark=effective_watermark,
        crf=crf,
        preset=preset,
        pix_fmt=pix_fmt,
        output_format=output_format,
    )

class Crunchyroll(CrunchyrollBase):
    def __init__(self, token, playback_endpoint=None, playback_user_agent=None,
                 auth_instance=None, email=None, password=None):
        super().__init__()
        self.token = token
        self.last_playback_error = None
        self.playback_endpoint = playback_endpoint
        self.playback_user_agent = playback_user_agent
        # Store auth context for automatic token refresh
        self._auth = auth_instance
        self._email = email
        self._password = password
        self._token_acquired_at = time.time()
        # Crunchyroll access tokens typically expire in 300s (5 min);
        # refresh proactively 60s before expiry to avoid mid-request failures
        self._token_ttl = 240
        # Minimum delay before retrying a refresh that just failed.
        self._refresh_backoff = 60
        # Which account the current token cache belongs to. Written into cache
        # payloads so a token issued to one account is never reused for another.
        self.last_login_account = None
        # URL the MPD was fetched from; resolves relative segment addresses.
        self.mpd_document_url = None
        playback_endpoints = list(CR_PLAYBACK_ENDPOINTS)
        if playback_endpoint:
            playback_endpoints = [playback_endpoint] + [
                endpoint for endpoint in playback_endpoints
                if endpoint != playback_endpoint
            ]
        self.playback_endpoints = tuple(playback_endpoints)
        self._apply_token_headers(token)

    def _apply_token_headers(self, token):
        self.set_headers({
            "authorization": f"Bearer {token}",
            "accept": "application/json",
            "connection": "Keep-Alive",
            "etp-anonymous-id": str(uuid.uuid4()),
            "user-agent": CR_WEB_USER_AGENT,
            "x-datadog-sampling-priority": "0",
        }, replace=True)

    def _ensure_valid_token(self):
        """Refresh the access token if it is expired or about to expire."""
        if not self._auth:
            return
        elapsed = time.time() - self._token_acquired_at
        if elapsed < self._token_ttl:
            return
        cr_debug(f"access token is {int(elapsed)}s old, refreshing...")
        try:
            new_token = self._auth.authenticate(
                self._email or "",
                self._password or "",
                etp_rt=self._auth._configured_etp_rt() or None,
                allow_guest_fallback=_as_bool(config_value("allow_guest_fallback", True)),
                force_refresh=True,
            )
            if new_token and new_token != self.token:
                self.token = new_token
                self._token_acquired_at = time.time()
                self.playback_endpoint = self._auth.playback_endpoint
                self.playback_user_agent = self._auth.playback_user_agent
                self._apply_token_headers(new_token)
                cr_debug("access token refreshed successfully")
            elif new_token:
                # Same token returned (cache hit), just reset the timer
                self._token_acquired_at = time.time()
                cr_debug("access token still valid per auth cache")
            else:
                cr_debug(f"token refresh failed: {self._auth.last_auth_error}")
                self._backoff_after_failed_refresh()
        except Exception as error:
            cr_debug(f"token refresh error: {error}")
            self._backoff_after_failed_refresh()

    def _backoff_after_failed_refresh(self):
        """Stop a failed refresh from re-authenticating on every single call.

        A single authenticate() cycle can submit several password logins, so
        retrying it per API call risks account lockout. Advance the timer so the
        next attempt waits out the backoff window instead of firing immediately.
        """
        now = time.time()
        if now - self._token_acquired_at < self._refresh_backoff:
            return
        self._token_acquired_at = now

    def _playback_user_agent(self, endpoint):
        if endpoint == self.playback_endpoint and self.playback_user_agent:
            return self.playback_user_agent
        if endpoint == "tv/android_tv":
            return "Crunchyroll/ANDROIDTV/3.61.0_22341 (Android 12; en-US; SHIELD Android TV Build/SR1A.211012.001)"
        if endpoint.startswith("web/"):
            return CR_WEB_USER_AGENT
        return Miscellaneous().randomize_user_agent()

    def _get_json(self, url, params=None):
        self._ensure_valid_token()
        response = self.request("get", url, params=params)
        if response.status_code != 200:
            print(f"Crunchyroll request failed ({response.status_code}): {url}")
            print("Response:", response.text[:500])
            return {}
        try:
            return response.json()
        except Exception:
            print(f"Crunchyroll returned non-JSON response: {url}")
            print("Response:", response.text[:500])
            return {}

    def _search_json(self, query, result_type, limit, locale):
        return self._get_json(
            f"{CR_API_BASE}/content/v2/discover/search",
            params={
                "q": query,
                "n": str(limit),
                "locale": locale,
                "type": result_type,
            },
        )

    @staticmethod
    def _access_from_metadata(metadata):
        if not isinstance(metadata, dict):
            return "unknown"
        is_premium = metadata.get("is_premium_only")
        if is_premium is None:
            versions = metadata.get("versions") or []
            version_values = [version.get("is_premium_only") for version in versions if isinstance(version, dict)]
            if version_values:
                is_premium = all(version_values)
        if is_premium is None:
            status = str(metadata.get("availability_status", "")).lower()
            if "premium" in status:
                is_premium = True
            elif status:
                is_premium = False
        if is_premium is True:
            return "premium"
        if is_premium is False:
            return "free"
        return "unknown"

    def _series_access(self, series_id):
        episodes_info, _ = self.get_content_info(f"https://www.crunchyroll.com/series/{series_id}")
        episodes = episodes_info.get("data") or []
        if not episodes:
            return "unknown"
        return self._access_from_metadata(episodes[0].get("episode_metadata") or episodes[0])

    def _normalize_search_item(self, item, result_type):
        if not isinstance(item, dict):
            return None
        item_id = item.get("id")
        title = item.get("title") or item.get("promo_title") or item_id
        if not item_id or not title:
            return None

        slug = item.get("slug_title") or item.get("slug") or ""
        if result_type == "episode":
            metadata = item.get("episode_metadata") or {}
            series_title = metadata.get("series_title")
            episode_number = metadata.get("episode_number") or metadata.get("episode")
            if series_title:
                title = f"{series_title} E{episode_number} - {title}" if episode_number else f"{series_title} - {title}"
            access = self._access_from_metadata(metadata)
            url = f"https://www.crunchyroll.com/watch/{item_id}/{slug}".rstrip("/")
        else:
            access = self._series_access(item_id)
            url = f"https://www.crunchyroll.com/series/{item_id}/{slug}".rstrip("/")

        return {
            "id": item_id,
            "title": title,
            "type": result_type,
            "url": url,
            "access": access,
        }

    @staticmethod
    def _iter_search_items(payload):
        for group in payload.get("data") or []:
            for item in group.get("items") or []:
                yield item

    def search(self, query, limit=5, locale="en-US"):
        query = (query or "").strip()
        if not query:
            return []

        results = []
        seen = set()
        for result_type in ("series", "episode"):
            payload = self._search_json(query, result_type, limit, locale)
            for item in self._iter_search_items(payload):
                normalized = self._normalize_search_item(item, result_type)
                if not normalized or normalized["id"] in seen:
                    continue
                seen.add(normalized["id"])
                results.append(normalized)
                if len(results) >= limit:
                    return results
        return results

    @staticmethod
    def _first_value(data, *keys):
        if not isinstance(data, dict):
            return None
        for key in keys:
            value = data.get(key)
            if value not in (None, ""):
                return value
        return None

    @classmethod
    def _locale_value(cls, value):
        if isinstance(value, dict):
            return cls._first_value(value, "cr_locale", "locale", "code", "name", "language")
        return value

    @classmethod
    def _normalize_tracks(cls, tracks):
        normalized = {}
        if not isinstance(tracks, dict):
            return normalized
        for lang, data in tracks.items():
            if not isinstance(data, dict):
                continue
            url = cls._first_value(data, "url", "Url")
            if not url:
                continue
            track_lang = cls._locale_value(cls._first_value(data, "language", "locale", "Locale")) or lang
            normalized[track_lang] = {
                "url": url,
                "format": cls._first_value(data, "format", "Format") or "vtt",
                "language": track_lang,
            }
        return normalized

    @classmethod
    def _normalize_versions(cls, versions):
        normalized = []
        if not isinstance(versions, list):
            return normalized
        for version in versions:
            if not isinstance(version, dict):
                continue
            guid = cls._first_value(version, "guid", "Guid", "media_guid", "mediaGuid")
            audio_locale = cls._locale_value(cls._first_value(version, "audio_locale", "audioLocale", "AudioLocale"))
            if not guid or not audio_locale:
                continue
            normalized_version = dict(version)
            normalized_version["guid"] = guid
            normalized_version["audio_locale"] = audio_locale
            normalized.append(normalized_version)
        return normalized

    @classmethod
    def _normalize_playback_info(cls, data):
        if not isinstance(data, dict):
            return {}
        normalized = dict(data)
        normalized["url"] = cls._first_value(data, "url", "Url")
        normalized["token"] = cls._first_value(data, "token", "Token")
        normalized["audio_locale"] = cls._locale_value(cls._first_value(data, "audio_locale", "audioLocale", "AudioLocale"))
        normalized["versions"] = cls._normalize_versions(cls._first_value(data, "versions", "Versions") or [])
        normalized["subtitles"] = cls._normalize_tracks(cls._first_value(data, "subtitles", "Subtitles") or {})
        normalized["captions"] = cls._normalize_tracks(
            cls._first_value(data, "captions", "Captions", "closed_captions", "closedCaptions") or {}
        )
        return normalized

    def deauth_video(self, content_id, video_token):
        if not content_id or not video_token:
            return
        with contextlib.suppress(Exception):
            self.request("patch", f"{CR_PLAYBACK_TOKEN_BASE}/{content_id}/{video_token}/inactive", json={})

    def _retry_after_active_stream_cleanup(self, response, content_id=None):
        """Release a stale playback token for the requested title, then retry.

        Crunchyroll refuses a second concurrent stream and lists the ones already
        running in `activeStreams`. That list belongs to the whole account, so it
        can include a phone or TV playing something else entirely. Only streams
        whose contentId matches what we asked for are released; deactivating the
        rest would interrupt the user's other devices. Entries with no contentId
        are left alone, since under-releasing only costs one retry.
        """
        try:
            payload = response.json()
        except Exception:
            return False
        active_streams = payload.get("activeStreams") or payload.get("active_streams") or []
        if not active_streams:
            return False

        released = set()
        for active_stream in active_streams:
            if not isinstance(active_stream, dict):
                continue
            stream_content_id = self._first_value(active_stream, "contentId", "content_id")
            if content_id and stream_content_id and stream_content_id != content_id:
                cr_debug(f"leaving unrelated active stream {stream_content_id} untouched")
                continue
            if stream_content_id is None:
                continue
            token = self._first_value(active_stream, "token", "Token")
            if not token:
                continue
            key = (stream_content_id, token)
            if key in released:
                continue
            released.add(key)
            self.deauth_video(stream_content_id, token)
        return bool(released)

    def get_account_info(self):
        """Retrieve current user account information"""
        return self._get_json(f"{CR_API_BASE}/accounts/v1/me/profile")

    def get_content_info(self, url):
        """Retrieve series metadata"""
        series_id = re.search(r'series/([^/]+)', url).group(1)
        query = {"preferred_audio_language": "en-US", "locale": "en-US"}
        series_info = self._get_json(f"{CR_API_BASE}/content/v2/cms/series/{series_id}", params=query)
        seasons_info = self._get_json(f"{CR_API_BASE}/content/v2/cms/series/{series_id}/seasons", params=query)

        seasons = seasons_info.get("data") or []
        if not seasons:
            return {}, series_info

        all_episodes = []
        season_summaries = []
        for season in seasons:
            season_id = find_guid_by_locale(season, "en-US") or season.get("id")
            if not season_id:
                continue
            episodes_info = self._get_json(f"{CR_API_BASE}/content/v2/cms/seasons/{season_id}/episodes", params=query)
            episodes = episodes_info.get("data") or []
            season_title = season.get("title") or f"Season {season.get('season_number', len(season_summaries) + 1)}"
            season_summaries.append({
                "id": season_id,
                "title": season_title,
                "season_number": season.get("season_number"),
                "number_of_episodes": season.get("number_of_episodes") or len(episodes),
                "loaded_episodes": len(episodes),
            })
            for episode in episodes:
                episode["_season_id"] = season_id
                episode["_season_title"] = season_title
                all_episodes.append(episode)

        return {
            "data": all_episodes,
            "total": len(all_episodes),
            "seasons": season_summaries,
            "meta": {
                "season_total": len(season_summaries),
                "versions_considered": True,
            },
        }, series_info

    def get_video_info(self, content_id):
        self._ensure_valid_token()
        last_response = None
        self.last_playback_error = None
        for endpoint in self.playback_endpoints:
            playback_url = f"{CR_PLAYBACK_BASE}/{content_id}/{endpoint}/play"
            self.set_headers({
                "authorization": f"Bearer {self.token}",
                "accept": "application/json",
                "user-agent": self._playback_user_agent(endpoint),
            })
            response = self.request("get", playback_url)
            cr_debug(f"playback {endpoint}: status={response.status_code}")
            if response.status_code == 200:
                normalized = self._normalize_playback_info(response.json())
                if normalized.get("url"):
                    return normalized
                last_response = response
            last_response = response
            if self._retry_after_active_stream_cleanup(response, content_id):
                cr_debug(f"playback {endpoint}: cleared active stream, retrying")
                response = self.request("get", playback_url)
                cr_debug(f"playback {endpoint} retry: status={response.status_code}")
                if response.status_code == 200:
                    normalized = self._normalize_playback_info(response.json())
                    if normalized.get("url"):
                        return normalized
                last_response = response

        if last_response is not None:
            try:
                payload = last_response.json()
                self.last_playback_error = payload.get("error") or payload.get("message")
            except Exception:
                self.last_playback_error = last_response.text[:500]
            if self.last_playback_error:
                print(f"Playback unavailable: {self.last_playback_error}")
            else:
                print("Error: Failed to get playback data")
        return {}

    def get_single_info(self, content_id):
        return self._get_json(
            f"{CR_API_BASE}/content/v2/cms/objects/{content_id}",
            params={"ratings": "true", "locale": "en-US"},
        )

    def get_pssh(self, info):
        mpd_url = info.get("url")
        if not mpd_url:
            raise ValueError("Playback response did not include an MPD URL")
        response = self.request("get", mpd_url)
        if response.status_code != 200:
            raise ValueError(f"Failed to fetch MPD: {response.status_code} {response.text[:200]}")
        mpd_content = response.text
        # Retained so relative BaseURL/SegmentTemplate values can be resolved
        # against the manifest they were declared in; without it they stayed
        # relative and could not be downloaded.
        self.mpd_document_url = mpd_url
        mpd_license = parse_mpd_logic(mpd_content)
        pssh_values = [value for value in mpd_license["pssh"] if value]
        if not pssh_values:
            raise ValueError("No Widevine PSSH found in MPD")
        pssh = pssh_values[0]
        token = info.get("token", "")
        return pssh, mpd_content, token

def find_guid_by_locale(data, locale):
    """Find the GUID for the specified locale, fallback to en-US if not found"""
    en_us_guid = None
    for version in data.get("versions", []):
        audio_locale = version.get("audio_locale") or version.get("audioLocale")
        guid = version.get("guid") or version.get("media_guid") or version.get("mediaGuid")
        if audio_locale == locale:
            return guid
        if audio_locale == "en-US":
            en_us_guid = guid
    return en_us_guid
