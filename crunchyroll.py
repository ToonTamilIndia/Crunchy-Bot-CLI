import time
import tls_client
import uuid
import random
import re
import json
from lxml import etree
import base64
from urllib.parse import urljoin
import os
import subprocess
import contextlib
from pathlib import Path
from tqdm import tqdm
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from config import *
import shutil

CR_API_BASE = "https://beta-api.crunchyroll.com"
CR_PLAYBACK_BASE = "https://cr-play-service.prd.crunchyrollsvc.com/v3"
CR_PLAYBACK_TOKEN_BASE = "https://cr-play-service.prd.crunchyrollsvc.com/v1/token"
CR_LICENSE_URL = "https://cr-license-proxy.prd.crunchyrollsvc.com/v1/license/widevine"
CR_VILOS_BUNDLE_URL = "https://static.crunchyroll.com/vilos-v2/web/vilos/js/bundle.js"
CR_WEB_AUTHORIZATION = "Basic Y3Jfd2ViOg=="
CR_WEB_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:137.0) "
    "Gecko/20100101 Firefox/137.0"
)
CR_DEBUG = bool(globals().get("debug", False))
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


def set_cr_debug(enabled):
    global CR_DEBUG
    CR_DEBUG = bool(enabled)


def cr_debug(message):
    if CR_DEBUG:
        print(f"[DEBUG] {message}")


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

class CrunchyrollBase:
    def __init__(self):
        self.session = tls_client.Session("okhttp4_android_13", random_tls_extension_order=True)

    def set_headers(self, headers, replace=False):
        if replace:
            self.session.headers.clear()
        self.session.headers.update(headers)

    def request(self, method, url, **kwargs):
        if use_proxy:
            kwargs.setdefault("proxy", proxy)
        return getattr(self.session, method)(url, **kwargs)


def _config_value(*names):
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

        device = load_widevine_device()
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
                print("Error: Failed to get keys")
                print("Response:", response.text)
                return

            cdm.parse_license(session_id, base64.b64decode(response.json()["license"]))
            keys = [{"type": key.type, "kid_hex": key.kid.hex, "key_hex": key.key.hex()} for key in cdm.get_keys(session_id)]
            return {"key": keys}
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

def download_segment(segment_links, name, format, max_threads=20, headers=None, user_agent=None):
    base_temp_dir = os.path.join("Temp", name)
    output_filename = name + '.' + format
    os.makedirs(base_temp_dir, exist_ok=True)

    total = len(segment_links)
    configured_threads = globals().get("download_threads")
    if isinstance(configured_threads, int) and configured_threads > 0:
        max_threads = configured_threads
    max_threads = max(1, min(max_threads, total))
    buffers = [None] * total
    failed_segments = []

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

    def build_curl_cmd(url, temp_path, max_time="30"):
        cmd = [
            "curl", "-sS", "-L", "--fail",
            "--connect-timeout", "10",
            "--max-time", max_time,
            "--retry", "2",
            "--retry-all-errors",
            "--retry-delay", "1",
            "--retry-max-time", "60",
        ]
        for key, value in normalized_headers.items():
            cmd.extend(["-H", f"{key}: {value}"])
        cmd.extend([url.strip(), "-o", temp_path])
        if use_proxy:
            cmd.insert(-2, "--proxy")
            cmd.insert(-2, proxy)
        return cmd

    def download_single(index, url):
        temp_path = os.path.join(base_temp_dir, f"segment_{index}.ts")
        for retry in range(max_retries):
            try:
                cmd = build_curl_cmd(url, temp_path)
                result = subprocess.run(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                if result.returncode == 0 and os.path.exists(temp_path):
                    if os.path.getsize(temp_path) > 0:
                        with open(temp_path, 'rb') as f:
                            content = f.read()
                        return index, content
                else:
                    err_msg = result.stderr.decode('utf-8', errors='ignore')
                    print(f"\n[DEBUG] Segment {index} download failed with returncode {result.returncode}. Error: {err_msg}. URL: {url.strip()}")
            except Exception as e:
                print(f"\n[DEBUG] Segment {index} download exception: {e}")
                pass
            backoff = retry_delay * (2 ** retry)
            time.sleep(backoff + random.uniform(0.0, 0.5))
            print(f"[WARN] Segment {index} failed retrying ({retry + 1}/{max_retries}).")
        with contextlib.suppress(Exception):
            os.remove(temp_path)
        return index, None
         
    with ThreadPoolExecutor(max_workers=max_threads) as executor:
        future_to_index = {
            executor.submit(download_single, i, url): i
            for i, url in enumerate(segment_links)
        }

        for future in as_completed(future_to_index):
            index, content = future.result()
            if content:
                buffers[index] = content
            else:
                failed_segments.append((index, segment_links[index]))
            progress_bar.update(1)

    progress_bar.close()

    
    if failed_segments:
        print(f"[INFO] Retrying {len(failed_segments)} failed segments one last time...")
        for index, url in failed_segments[:]:
            temp_path = os.path.join(base_temp_dir, f"segment_{index}.ts")
            try:
                cmd = build_curl_cmd(url, temp_path, max_time="60")
                result = subprocess.run(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                if result.returncode == 0 and os.path.exists(temp_path):
                    if os.path.getsize(temp_path) > 0:
                        with open(temp_path, 'rb') as f:
                            content = f.read()
                        buffers[index] = content
                        failed_segments.remove((index, url))
            except Exception:
                pass
            time.sleep(retry_delay)

   
    if failed_segments:
        with open("error.txt", "w", encoding="utf-8") as error_file:
            for index, url in failed_segments:
                error_file.write(f"{index}: {url.strip()}\n")
                print(f"[WARN] Segment {index} failed permanently after retries.")
        raise RuntimeError("Download failed: one or more segments could not be retrieved.")

   
    os.makedirs("Downloads", exist_ok=True)
    output_path = os.path.join("Downloads", output_filename)
    with open(output_path, 'wb') as out_file:
        for data in buffers:
            if data:
                out_file.write(data)

    shutil.rmtree(base_temp_dir, ignore_errors=True)

    print(f"[INFO] Downloaded and saved as: {output_path}")

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

    def find_base_url(elem):
        current = elem
        while current is not None:
            base_url_elem = current.find("ns:BaseURL", namespace)
            if base_url_elem is not None and base_url_elem.text:
                return base_url_elem.text.strip()
            current = current.getparent()
        return None

    for elem in representations:
        rep_id = elem.attrib.get('id', '')
        bandwidth = int(elem.attrib.get('bandwidth', 0))
        codecs = elem.attrib.get('codecs', '')

        width = elem.attrib.get('width')
        height = elem.attrib.get('height')
        width = int(width) if width else None
        height = int(height) if height else None

        base_url = find_base_url(elem)

        if width and height:
            video_list.append({
                "name": rep_id,
                "bandwidth": bandwidth,
                "width": width,
                "height": height,
                "codecs": codecs,
                "base_url": base_url
            })
        else:
            audio_list.append({
                "name": rep_id,
                "bandwidth": bandwidth,
                "codecs": codecs,
                "base_url": base_url
            })

    return video_list, audio_list

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
    
def get_segment_link_list(mpd_content, representation_id, url):
        if isinstance(mpd_content, str):
            content = mpd_content.encode('utf-8')
        else:
            content = mpd_content

        try:
            tree = etree.fromstring(content)
            
            ns = {'dash': 'urn:mpeg:dash:schema:mpd:2011'}
    
            
            representation = tree.find(f'.//dash:Representation[@id="{representation_id}"]', ns)
            if representation is None:
              return {}

            adaptation_set = representation.getparent()

            segment_template = representation.find('dash:SegmentTemplate', ns)
            if segment_template is None and adaptation_set is not None:
                segment_template = adaptation_set.find('dash:SegmentTemplate', ns)
            if segment_template is None:
              return {}
    
            segment_timeline = segment_template.find('dash:SegmentTimeline', ns)
            if segment_timeline is None:
              return {}
    
            media_template = segment_template.get('media')
            init_template = segment_template.get('initialization')
            if not media_template or not init_template:
                return {}
            
            
            bandwidth = representation.get('bandwidth', '')
            
            def resolve_dash_template(template, representation_id="", bandwidth="", number=None, time_val=None):
                pattern = r'\$(RepresentationID|Number|Bandwidth|Time)(%[0-9]*d)?\$'
                def repl(m):
                    i, f = m.group(1), m.group(2)
                    if i == 'RepresentationID':
                        val = representation_id
                    elif i == 'Bandwidth':
                        val = bandwidth
                    elif i == 'Number':
                        if number is None:
                            return m.group(0)
                        val = number
                    elif i == 'Time':
                        if time_val is None:
                            return m.group(0)
                        val = time_val
                    else:
                        return m.group(0)
                    return f % int(val) if f else str(val)
                return re.sub(pattern, repl, template)

            init_file = resolve_dash_template(init_template, representation_id=representation_id, bandwidth=bandwidth)
            
            segment_list = []
            segment_all = []
            segment_all.append(urljoin(url, init_file))
            current_time = 0
            for segment in segment_timeline.findall('dash:S', ns):
                t_attr = segment.get('t')
                if t_attr is not None:
                    current_time = int(t_attr)
                d_attr = segment.get('d')
                r_attr = segment.get('r')
                if not d_attr:
                    continue
                duration = int(d_attr)
                
                repeat_count = 1
                if r_attr is not None:
                    repeat_count = int(r_attr) + 1
    
                for _ in range(repeat_count):
                    segment_file = resolve_dash_template(
                        media_template,
                        representation_id=representation_id,
                        bandwidth=bandwidth,
                        number=len(segment_list) + 1,
                        time_val=current_time
                    )
                    segment_list.append(urljoin(url, segment_file))
                    segment_all.append(urljoin(url, segment_file))
                    current_time += duration
    
    
            init_url = urljoin(url, init_file)
    
    
            return {"init": init_url, "segments": segment_list, "all": segment_all}
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


class CrunchyrollAuth(CrunchyrollBase):
    def __init__(self):
        super().__init__()
        self.playback_endpoint = None
        self.playback_user_agent = None
        self.last_auth_error = None
        self.last_auth_context = None

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

    def _write_cached_token(self, profile, payload, device_id):
        if not isinstance(payload, dict):
            return
        token_payload = dict(payload)
        token_payload["device_id"] = device_id
        if token_payload.get("expires_in"):
            token_payload["expires_at"] = int(time.time()) + int(token_payload["expires_in"])
        try:
            cache_path = self._token_cache_path(profile)
            with cache_path.open("w", encoding="utf-8") as token_file:
                json.dump(token_payload, token_file, indent=2)
            with contextlib.suppress(Exception):
                cache_path.chmod(0o600)
        except Exception:
            return

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
        urls = []
        configured_url = _config_value("crd_auth_data_url", "CRD_AUTH_DATA_URL")
        if configured_url:
            urls.append(configured_url)
        urls.extend(CRD_AUTH_DATA_URLS)
        for url in urls:
            try:
                response = self.request("get", url, headers={"User-Agent": "C# App"})
                cr_debug(f"CRD auth data {url}: status={response.status_code}")
                if response.status_code != 200:
                    continue
                payload = response.json()
                if isinstance(payload, list):
                    return payload
            except Exception as error:
                cr_debug(f"CRD auth data {url}: {error}")
        return []

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
            self._write_cached_token(profile, payload, device_id)
        return payload

    def get_guest_token(self):
        self.playback_endpoint = "web/firefox"
        self.playback_user_agent = CR_WEB_USER_AGENT
        data = {
            "grant_type": "client_id",
            "scope": "offline_access",
        }
        payload = self._post_token_payload(data, CR_WEB_AUTHORIZATION, CR_WEB_USER_AGENT, "guest")
        return payload.get("access_token")

    def get_user_token(self, email, password, allow_guest_fallback=True):
        self.playback_endpoint = None
        account_error = None
        account_context = None
        auth_profiles = self._profiles_with_crd_updates()

        for profile in auth_profiles:
            cached_payload = self._read_cached_token(profile)
            if self._has_valid_access_token(cached_payload):
                self.playback_endpoint = profile["endpoint"]
                self.playback_user_agent = profile["user_agent"]
                cr_debug(f"using cached access token for {profile['name']}")
                return cached_payload["access_token"]
            refreshed_payload = self._refresh_cached_token(profile, cached_payload)
            if refreshed_payload:
                self.playback_endpoint = profile["endpoint"]
                self.playback_user_agent = profile["user_agent"]
                return refreshed_payload["access_token"]
            account_error = self.last_auth_error or account_error
            account_context = self.last_auth_context or account_context

        for profile in auth_profiles:
            payload = self._password_login(profile, email, password)
            if payload:
                self.playback_endpoint = profile["endpoint"]
                self.playback_user_agent = profile["user_agent"]
                return payload["access_token"]
            account_error = self.last_auth_error or account_error
            account_context = self.last_auth_context or account_context

        if not allow_guest_fallback:
            return None

        guest_token = self.get_guest_token()
        if guest_token and account_error:
            self.last_auth_error = account_error
            self.last_auth_context = account_context
        return guest_token

def get_filter_complex():
    
    return (
        f"[0:v]drawtext=text='{Watermark_Name}':"
        f"fontfile={fontfile}:"
        f"fontcolor={fontcolor}@{opaque}:" 
        f"fontsize={fontsize}:"
        f"x={x_axis}:"
        f"y={y_axis}[v]"
    )

class Crunchyroll(CrunchyrollBase):
    def __init__(self, token, playback_endpoint=None, playback_user_agent=None):
        super().__init__()
        self.token = token
        self.last_playback_error = None
        self.playback_endpoint = playback_endpoint
        self.playback_user_agent = playback_user_agent
        playback_endpoints = list(CR_PLAYBACK_ENDPOINTS)
        if playback_endpoint:
            playback_endpoints = [playback_endpoint] + [
                endpoint for endpoint in playback_endpoints
                if endpoint != playback_endpoint
            ]
        self.playback_endpoints = tuple(playback_endpoints)
        self.set_headers({
            "authorization": f"Bearer {token}",
            "accept": "application/json",
            "connection": "Keep-Alive",
            "etp-anonymous-id": str(uuid.uuid4()),
            "user-agent": CR_WEB_USER_AGENT,
            "x-datadog-sampling-priority": "0",
        }, replace=True)

    def _playback_user_agent(self, endpoint):
        if endpoint == self.playback_endpoint and self.playback_user_agent:
            return self.playback_user_agent
        if endpoint == "tv/android_tv":
            return "Crunchyroll/ANDROIDTV/3.61.0_22341 (Android 12; en-US; SHIELD Android TV Build/SR1A.211012.001)"
        if endpoint.startswith("web/"):
            return CR_WEB_USER_AGENT
        return Miscellaneous().randomize_user_agent()

    def _get_json(self, url, params=None):
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

    def _retry_after_active_stream_cleanup(self, response):
        try:
            payload = response.json()
        except Exception:
            return False
        active_streams = payload.get("activeStreams") or payload.get("active_streams") or []
        if not active_streams:
            return False
        for active_stream in active_streams:
            content_id = self._first_value(active_stream, "contentId", "content_id")
            token = self._first_value(active_stream, "token", "Token")
            self.deauth_video(content_id, token)
        return True

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
            if self._retry_after_active_stream_cleanup(response):
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
