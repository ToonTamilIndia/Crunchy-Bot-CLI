import re
import os
import traceback
import threading
from functools import wraps
from contextlib import suppress
import time
import math
from hachoir.metadata import extractMetadata
from hachoir.parser import createParser
import subprocess
import uuid

from platform_tools import (
    display_command, resolve_executable, run_command, split_command, OperationCancelled,
)

from crunchyroll import (
    Crunchyroll, CrunchyrollAuth, CrunchyrollLicense,
    LicenseError, extract_content_key,
    parse_mpd_content, get_segment_link_list, download_segment,
    get_filter_complex, convert_vtt_to_srt_custom, convert_ass_to_srt_custom,
    get_episode_display_number, get_episode_title,
    parse_episode_selection, get_download_path,
    get_encrypted_media_path, get_temp_path,
    resolve_encoding_config, EncodingConfig,
    resolve_keep_ass_subtitles, subtitle_needs_srt,
)

from pyrogram import Client, filters, enums
from pyrogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery
)
from pyrogram.errors import MessageNotModified, QueryIdInvalid

def config_value(name, default=None):
    """Read a setting live from config, falling back to the import snapshot."""
    try:
        import config as _config
        if hasattr(_config, name):
            return getattr(_config, name)
    except Exception:
        pass
    return globals().get(name, default)


def as_bool(value, default=False):
    """Coerce a config value to a bool.

    `use_watermark = "False"` is a truthy string, which would silently switch
    the watermark on, so spell the string values out explicitly.
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


def as_int(value, default):
    """Coerce a config value to int, tolerating a quoted number."""
    if value is None or value == "":
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


try:
    auth = CrunchyrollAuth()
    encoding_config = resolve_encoding_config()
    print(f"[Telegram Bot] {encoding_config.summary()}")
except Exception as e:
    print(f"ERROR : {e}")
    exit(1)


app = Client("crunchyroll_bot", api_id=config_value("API_ID"), api_hash=config_value("API_HASH"), bot_token=config_value("BOT_TOKEN"))

class tgUploader:
    def __init__(self, app, msg):
        self.app = app
        self.msg = msg

    def upload_file(self, file_path):
        """Upload and report the outcome.

        Returns (ok, detail). A failed upload previously returned None and the
        caller announced "Upload complete" regardless.
        """
        thumb = None
        try:
            file_name = os.path.basename(file_path)
            duration = get_duration(file_path)
            width, height = get_dimensions(file_path)
            thumb = get_thumbnail(file_path, "", duration / 2)
            caption = '''<code>{}</code>'''.format(file_name)
            progress_args_text = "<code>[+]</code> <b>{}</b>\n<code>{}</code>".format("Uploading", file_name)
            send_kwargs = {
                "video": file_path,
                "chat_id": self.msg.chat.id,
                "caption": caption,
                "progress": progress_for_pyrogram,
                "progress_args": (
                    progress_args_text,
                    self.msg,
                    time.time()
                ),
                "duration": duration,
                "width": width,
                "height": height,
            }
            if thumb:
                send_kwargs["thumb"] = thumb
            self.app.send_video(**send_kwargs)
            return True, "Upload complete"
        except Exception as e:
            print(e)
            with suppress(Exception):
                self.msg.edit(f"`{e}`")
            return False, str(e)
        finally:
            if thumb:
                with suppress(Exception):
                    os.remove(thumb)

def get_dimensions(filepath):
    """Real width/height of the produced file.

    Telegram was told 1280x720 unconditionally, which misrepresents every
    other rendition. Falls back to 0 (omit) when it cannot be determined.
    """
    try:
        parser = createParser(filepath)
        if not parser:
            return 0, 0
        metadata = extractMetadata(parser)
        width = int(metadata.get("width") or 0) if metadata else 0
        height = int(metadata.get("height") or 0) if metadata else 0
        return width, height
    except Exception:
        return 0, 0


def get_duration(filepath):
    try:
        parser = createParser(filepath)
        if not parser:
            return 0
        metadata = extractMetadata(parser)
        if metadata and metadata.has("duration"):
            return metadata.get('duration').seconds
    except Exception as e:
        print(f"Error reading duration: {e}")
    return 0

def get_thumbnail(in_filename, path, ttl):
    out_filename = os.path.join(path, f"{time.time()}.jpg")

    try:
        command = [
            "ffmpeg",
            "-ss", str(ttl),
            "-i", in_filename,
            "-frames:v", "1",
            "-q:v", "2",
            "-y",
            out_filename
        ]

        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        if result.returncode == 0:
            return out_filename
        else:
            print(f"FFmpeg error:\n{result.stderr}")
            return None

    except Exception as e:
        print(f"Error generating thumbnail: {e}")
        return None


def progress_for_pyrogram(
    current,
    total,
    ud_type,
    message,
    start
):
    now = time.time()
    diff = max(now - start, 0.001)
    if total <= 0:
        return

    if round(diff % 10.00) == 0 or current == total:
        percentage = current * 100 / total
        speed = current / diff
        time_to_completion = get_readable_time(round((total - current) / speed)) if speed else "0s"

        progress = "[{0}{1}]".format(
            ''.join(["█" for _ in range(math.floor(percentage / 5))]),
            ''.join(["░" for _ in range(20 - math.floor(percentage / 5))])
        )

        tmp = (
            f"{progress} `{round(percentage, 2)}%`\n"
            f"`{humanbytes(current)} of {humanbytes(total)}`\n"
            f"**Speed:** `{humanbytes(speed)}/s`\n"
            f"**ETA:** `{time_to_completion}`"
        )

        try:
            message.edit(
                text=f"{ud_type}\n\n{tmp}"
            )
        except Exception as e:
            print(f"Error updating progress: {e}")


def humanbytes(size):
    """Convert bytes to a human-readable format."""
    if not size:
        return "0B"
    power = 2 ** 10
    n = 0
    labels = {0: 'B', 1: 'KB', 2: 'MB', 3: 'GB', 4: 'TB'}
    while size >= power and n < len(labels) - 1:
        size /= power
        n += 1
    return f"{size:.2f} {labels[n]}"


def get_readable_time(seconds: int) -> str:
    result = ''
    (days, remainder) = divmod(seconds, 86400)
    days = int(days)
    if days != 0:
        result += f'{days}d'
    (hours, remainder) = divmod(remainder, 3600)
    hours = int(hours)
    if hours != 0:
        result += f'{hours}h'
    (minutes, seconds) = divmod(remainder, 60)
    minutes = int(minutes)
    if minutes != 0:
        result += f'{minutes}m'
    seconds = int(seconds)
    result += f'{seconds}s'
    return result


def check_user_tier(tier="regular"):
    def decorator(func):
        @wraps(func)
        def wrapper(client, update):
            user_id = update.from_user.id
            allowed = False
            if tier == "sudo" and user_id in config_value("sudo_users"):
                allowed = True
            elif tier == "premium" and (user_id in config_value("sudo_users") or user_id in config_value("premium_users")):
                allowed = True
            elif tier == "regular":
                allowed = True

            if allowed:
                return func(client, update)
            else:
                if isinstance(update, CallbackQuery):
                    update.answer("You don't have permission for this action.", show_alert=True)
                elif isinstance(update, Message):
                    update.reply_text("You don't have permission for this command.")
        return wrapper
    return decorator

# Pyrogram dispatches handlers from a thread pool, so `user_states` and
# `active_downloads` are read and written concurrently. Every access goes
# through these helpers under one lock so that check-then-set sequences such as
# "is this still the confirm_download step?" cannot interleave.
_state_lock = threading.RLock()

# Jobs the user asked to cancel. Keyed by an immutable job id rather than by
# user id: a user id is reusable, so cancelling A and then starting B used to
# clear A's flag, because begin_active_download() discarded the user id and a
# straggling worker then read "not cancelled" and kept downloading.
cancelled_jobs = set()

# Events a media stage polls so a cancel reaches curl/ffmpeg instead of only
# being observed at the next episode boundary.
cancel_events = {}


def session_nonce(state):
    return (state or {}).get("nonce") or ""


def cb(action, state=None):
    """Stamp a callback with the session nonce so stale buttons are rejected."""
    nonce = session_nonce(state if state is not None else None)
    return f"{action}|{nonce}" if nonce else action


def split_callback(data):
    """Return (action, nonce) for a stamped callback."""
    if isinstance(data, str) and "|" in data:
        action, _, nonce = data.rpartition("|")
        return action, nonce
    return data, None


def get_active_download(user_id):
    with _state_lock:
        return bool(config_value("active_downloads").get(user_id))


def begin_active_download(user_id, expected_step):
    """Atomically move a session from `expected_step` into `downloading`.

    Returns False when another thread already claimed it, so a double-tapped
    "Start" button cannot launch the same job twice. The slot records the owning
    session object so a stale worker can tell later whose lock it holds.
    """
    with _state_lock:
        state = config_value("user_states").get(user_id)
        if not state or state.get("step") != expected_step:
            return False
        if config_value("active_downloads").get(user_id):
            return False
        state["step"] = "downloading"
        # A fresh job id per run; it is never reused, so a new job cannot clear
        # an older job's cancellation.
        state["job_id"] = uuid.uuid4().hex
        state["cancel_event"] = threading.Event()
        cancel_events[state["job_id"]] = state["cancel_event"]
        config_value("active_downloads")[user_id] = state
        return True


def finish_active_download(user_id, expected_state):
    """Release only the resources this worker actually owns.

    After /cancel the user can start a new session that reclaims the same
    `active_downloads` slot. Comparing identity means a straggling worker from
    the cancelled run leaves the new session's state and guard untouched.
    """
    with _state_lock:
        if expected_state is not None:
            current = config_value("user_states").get(user_id)
            if current is expected_state:
                config_value("user_states").pop(user_id, None)
            if config_value("active_downloads").get(user_id) is expected_state:
                config_value("active_downloads").pop(user_id, None)
        else:
            config_value("user_states").pop(user_id, None)
            config_value("active_downloads").pop(user_id, None)
        job_id = (expected_state or {}).get("job_id")
        event = (expected_state or {}).get("cancel_event")
        if job_id:
            cancelled_jobs.discard(job_id)          # job finished cleanly
        if event is not None:
            cancel_events.pop(job_id, None)


def request_cancel(user_id):
    """Flag the in-flight job as cancelled and drop the visible session.

    The flag is recorded against that job's id and its event is set so running
    curl/ffmpeg processes can be torn down, not just loop iterations.
    """
    with _state_lock:
        state = (config_value("user_states").get(user_id)
                 or config_value("active_downloads").get(user_id))
        job_id = (state or {}).get("job_id")
        if job_id:
            cancelled_jobs.add(job_id)
        if state:
            event = state.get("cancel_event")
            if event is not None:
                event.set()
        config_value("user_states").pop(user_id, None)
        config_value("active_downloads").pop(user_id, None)
        return state


def is_job_cancelled(job_id):
    """True when this exact job was cancelled (never any other job)."""
    if not job_id:
        return False
    with _state_lock:
        return job_id in cancelled_jobs


def job_cancel_event(job_id):
    with _state_lock:
        return cancel_events.get(job_id)


def check_active_download(func):
    @wraps(func)
    def wrapper(client, update):
        user_id = update.from_user.id
        if isinstance(update, CallbackQuery) and update.data == "cancel":
            return func(client, update)
        # Sudo users are not exempt here. This guard exists because two runs for
        # the same user_id race on identical temp/output paths and delete each
        # other's files; that is a correctness problem, not a permission one.
        if get_active_download(user_id):
            if isinstance(update, CallbackQuery):
                update.answer("Please wait for your previous download to complete.", show_alert=True)
            elif isinstance(update, Message):
                update.reply_text("Please wait for your previous download to complete.")
            return
        return func(client, update)
    return wrapper

def run_shell_command(command, cancel_event=None):
    """Run a media command, killing it promptly when the job is cancelled.

    Decryption and muxing are the slowest stages; without this a cancel was
    only noticed once ffmpeg or mp4decrypt had already finished.
    """
    if isinstance(command, str):
        command = split_command(command)
    try:
        result = run_command(command, cancel_event=cancel_event,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    except OperationCancelled as exc:
        return "", str(exc), -1
    return result.stdout, result.stderr, result.returncode

def edit_message(message: Message, text: str, keyboard: InlineKeyboardMarkup = None):
    with suppress(MessageNotModified, QueryIdInvalid):
        message.edit_text(text, reply_markup=keyboard, parse_mode=enums.ParseMode.MARKDOWN)


def is_sudo_user(user_id):
    return user_id in config_value("sudo_users")


def is_premium_user(user_id):
    return user_id in config_value("premium_users")


# pyrogram's filters.user() copies its argument into a set when the filter is
# built, so a decorator gated on the sudo list is frozen at import and never
# sees a user added later by /addsudo. These evaluate the live list on every
# incoming update instead.
is_sudo = filters.create(lambda _, __, message: is_sudo_user(message.from_user.id))
is_premium = filters.create(lambda _, __, message: is_premium_user(message.from_user.id))


def get_user_limits(user_id):
    if is_sudo_user(user_id):
        return float('inf'), float('inf')
    if is_premium_user(user_id):
        return float('inf'), float('inf')
    return (
        as_int(config_value("REGULAR_USER_AUDIO_LIMIT"), 2),
        as_int(config_value("REGULAR_USER_VIDEO_LIMIT_P"), 480),
    )


def update_is_authorized(message):
    """Evaluate the chat allowlist live, for a single incoming update.

    filters.chat() copies its argument when the filter is built, so building the
    allowlist at import froze it: restricting AUTHORIZED_USERS later still let
    any private user through. This mirrors the is_sudo pattern above and reads
    the current list on every update.
    """
    chat = getattr(message, "chat", None)
    if chat is None:
        return False
    authorized = config_value("AUTHORIZED_USERS") or []
    if as_bool(authorized):
        chat_id = getattr(chat, "id", None)
        username = getattr(chat, "username", None)
        return chat_id in authorized or username in authorized
    # Empty allowlist means "any private chat".
    return getattr(chat, "type", None) == enums.ChatType.PRIVATE


DOWNLOAD_ACCESS_FILTER = (
    filters.create(lambda _, __, message: update_is_authorized(message)) | is_sudo
)


def get_decryption_key(license_response, kid=None):
    """Resolve the content key for one track, delegating to the shared helper.

    A single license covers every rendition and returns several keys that are
    all typed CONTENT, so taking "the first CONTENT key" hands the video track
    a key that belongs to a different rendition and the result decodes as
    corrupt frames. `kid` is the track's default_KID from the MPD.

    Returns None instead of raising so the call sites keep their existing
    skip-this-episode behaviour.
    """
    try:
        return extract_content_key(license_response, kid=kid)
    except LicenseError:
        return None


@app.on_message(filters.command("start"))
def start_command(client, message: Message):
    message.reply_text(
        "Hello! Welcome to the Crunchyroll Downloader Bot.\n"
        "Send me a Crunchyroll video URL, series URL, or search title using /download.\n"
        "Example: `/download https://www.crunchyroll.com/watch/GXXXXXXX/episode-title`\n"
        "Search Example: `/download naruto`\n"
        "Use /help for more commands."
    )

@app.on_message(filters.command("help"))
def help_command(client, message: Message):
    help_text = """
**Crunchyroll Downloader Bot Help**

**/start**: Shows the welcome message.
**/help**: Shows this help message.
**/download <url> or /dl <url>**: Starts the download process for a Crunchyroll video or series URL.
    - Example (Episode): `/download https://www.crunchyroll.com/watch/GXXXXXXX/episode-title`
    - Example (Series): `/download https://www.crunchyroll.com/series/GXXXXXXX/series-title`
    - Example (Search): `/download naruto`
**/cancel**: Cancels the current selection process (if any).

**User Tiers & Limits:**
- **Regular Users:** Max 2 audio tracks, Max 480p video quality.
- **Premium/Sudo Users:** No limits on audio tracks or video quality.

**Admin Commands (Sudo Only):**
**/addpremium <user_id>**: Adds a user to the premium list.
**/rempremium <user_id>**: Removes a user from the premium list.
**/listpremium**: Lists premium users.
**/addsudo <user_id>**: Adds a user to the sudo list.
**/remsudo <user_id>**: Removes a user from the sudo list.
**/listsudo**: Lists sudo users.
    """
    message.reply_text(help_text, parse_mode=enums.ParseMode.MARKDOWN)

@app.on_message(filters.command("cancel"))
def cancel_command(client, message: Message):
    user_id = message.from_user.id
    state = request_cancel(user_id)
    if state:
        if state.get("message"):
            edit_message(state["message"], "Download process cancelled.")
        else:
            message.reply_text("Download process cancelled.")
    else:
        message.reply_text("No active download process to cancel.")

@app.on_message(filters.command("addpremium") & is_sudo)
def add_premium(client, message: Message):
    try:
        user_id_to_add = int(message.text.split(maxsplit=1)[1])
        if user_id_to_add not in config_value("premium_users"):
            config_value("premium_users").append(user_id_to_add)
            message.reply_text(f"User `{user_id_to_add}` added to premium users.")
        else:
            message.reply_text("User is already premium.")
    except (IndexError, ValueError):
        message.reply_text("Usage: `/addpremium <user_id>` (User ID must be an integer).")
    except Exception as e:
        message.reply_text(f"An error occurred: {e}")

@app.on_message(filters.command("rempremium") & is_sudo)
def rem_premium(client, message: Message):
    try:
        user_id_to_rem = int(message.text.split(maxsplit=1)[1])
        if user_id_to_rem in config_value("premium_users"):
            config_value("premium_users").remove(user_id_to_rem)
            message.reply_text(f"User `{user_id_to_rem}` removed from premium users.")
        else:
            message.reply_text("User is not in the premium list.")
    except (IndexError, ValueError):
        message.reply_text("Usage: `/rempremium <user_id>` (User ID must be an integer).")
    except Exception as e:
        message.reply_text(f"An error occurred: {e}")

@app.on_message(filters.command("listpremium") & is_sudo)
def list_premium(client, message: Message):
    if not config_value("premium_users"):
        message.reply_text("The premium user list is empty.")
    else:
        message.reply_text("Premium Users:\n" + "\n".join(f"- `{uid}`" for uid in config_value("premium_users")))

@app.on_message(filters.command("addsudo") & is_sudo)
def add_sudo(client, message: Message):
    try:
        user_id_to_add = int(message.text.split(maxsplit=1)[1])
        if user_id_to_add not in config_value("sudo_users"):
            config_value("sudo_users").append(user_id_to_add)
            message.reply_text(f"User `{user_id_to_add}` added to sudo users.")
        else:
            message.reply_text("User is already sudo.")
    except (IndexError, ValueError):
        message.reply_text("Usage: `/addsudo <user_id>` (User ID must be an integer).")
    except Exception as e:
        message.reply_text(f"An error occurred: {e}")

@app.on_message(filters.command("remsudo") & is_sudo)
def rem_sudo(client, message: Message):
    try:
        user_id_to_rem = int(message.text.split(maxsplit=1)[1])
        if user_id_to_rem == message.from_user.id:
            message.reply_text("You cannot remove yourself from the sudo list.")
            return
        if user_id_to_rem in config_value("sudo_users"):
            config_value("sudo_users").remove(user_id_to_rem)
            message.reply_text(f"User `{user_id_to_rem}` removed from sudo users.")
        else:
            message.reply_text("User is not in the sudo list.")
    except (IndexError, ValueError):
        message.reply_text("Usage: `/remsudo <user_id>` (User ID must be an integer).")
    except Exception as e:
        message.reply_text(f"An error occurred: {e}")

@app.on_message(filters.command("listsudo") & is_sudo)
def list_sudo(client, message: Message):
    if not config_value("sudo_users"):
        message.reply_text("The sudo user list is empty. This shouldn't happen!")
    else:
        message.reply_text("Sudo Users:\n" + "\n".join(f"- `{uid}`" for uid in config_value("sudo_users")))


def search_button_label(result):
    title = result.get("title", "Untitled")
    if len(title) > 42:
        title = title[:39].rstrip() + "..."
    return f"({result.get('access', 'unknown')}) [{result.get('type', '?')}] {title}"


def show_search_results(client, user_id, query_text, status_msg):
    edit_message(status_msg, f"Searching Crunchyroll for `{query_text}`...")
    search_results = crunchyroll.search(query_text, limit=5)
    if not search_results:
        edit_message(status_msg, "No Crunchyroll search results found.")
        if user_id in config_value("user_states"):
            del config_value("user_states")[user_id]
        return

    state = config_value("user_states")[user_id]
    state["step"] = "select_search"
    state["data"]["search_results"] = search_results

    buttons = [
        [InlineKeyboardButton(search_button_label(result), callback_data=cb(f"search_{index}", state))]
        for index, result in enumerate(search_results)
    ]
    buttons.append([InlineKeyboardButton("Cancel", callback_data=cb("cancel", state))])

    edit_message(
        status_msg,
        "Select a Crunchyroll result:",
        keyboard=InlineKeyboardMarkup(buttons)
    )


def process_download_url(client, user_id, video_url, status_msg):
    try:
        if "crunchyroll.com" in video_url and "/watch/" in video_url:
            match = re.search(r'"?https?://www\.crunchyroll\.com/(?:watch)/([^/?"\']+)', video_url)
            if not match:
                edit_message(status_msg, "Invalid episode URL format.")
                del config_value("user_states")[user_id]
                return
            content_id = match.group(1)

            edit_message(status_msg, "Fetching video information...")
            video_info = crunchyroll.get_video_info(content_id)
            if not video_info:
                reason = crunchyroll.last_playback_error or "video not found or not accessible"
                edit_message(status_msg, f"Video not accessible: {reason}")
                del config_value("user_states")[user_id]
                return

            config_value("user_states")[user_id]["data"]["video_info"] = video_info
            config_value("user_states")[user_id]["data"]["id"] = content_id
            config_value("user_states")[user_id]["is_series"] = False

            pssh, mpd_content, token = crunchyroll.get_pssh(video_info)
            if not mpd_content:
                edit_message(status_msg, "Could not fetch MPD content.")
                del config_value("user_states")[user_id]
                return

            config_value("user_states")[user_id]["data"]["pssh"] = pssh
            config_value("user_states")[user_id]["data"]["mpd_content"] = mpd_content
            config_value("user_states")[user_id]["data"]["drm_token"] = token

            video_list, _ = parse_mpd_content(mpd_content)
            if not video_list:
                edit_message(status_msg, "No video streams found in MPD.")
                del config_value("user_states")[user_id]
                return

            config_value("user_states")[user_id]["data"]["available_video_qualities"] = video_list
            ask_video_quality(client, user_id)

        elif "crunchyroll.com" in video_url and "/series/" in video_url:
            match = re.search(r'"?https?://www\.crunchyroll\.com/(?:series)/([^/?"\']+)', video_url)
            if not match:
                edit_message(status_msg, "Invalid series URL format.")
                del config_value("user_states")[user_id]
                return

            edit_message(status_msg, "Fetching series information...")
            series_data, series_info = crunchyroll.get_content_info(url=video_url)
            if not series_data or 'data' not in series_data or not series_data['data']:
                edit_message(status_msg, "Series not found or no episodes available.")
                del config_value("user_states")[user_id]
                return

            episodes = [
                {
                    'episode_no': get_episode_display_number(ep, idx + 1),
                    'guid': ep['id'],
                    'title': get_episode_title(ep, idx + 1),
                }
                for idx, ep in enumerate(series_data['data'])
            ]
            series_payload = series_info.get("data")
            if isinstance(series_payload, list) and series_payload:
                series_title = series_payload[0].get("title", "Unknown Series")
            elif isinstance(series_payload, dict):
                series_title = series_payload.get("title", "Unknown Series")
            else:
                series_title = "Unknown Series"
            preview_lines = [
                f"{idx}. E{episode['episode_no']} - {episode['title'][:45]}"
                for idx, episode in enumerate(episodes[:15], start=1)
            ]
            if len(episodes) > 15:
                preview_lines.append(f"... and {len(episodes) - 15} more")

            config_value("user_states")[user_id]["data"]["episodes"] = episodes
            config_value("user_states")[user_id]["data"]["series_title"] = series_title
            config_value("user_states")[user_id]["is_series"] = True
            config_value("user_states")[user_id]["data"]["total_episodes"] = len(episodes)

            config_value("user_states")[user_id]["step"] = "ask_episode_count"
            edit_message(
                status_msg,
                f"Found series '{series_title}' with {len(episodes)} episodes.\n"
                + "\n".join(preview_lines)
                + "\n\nSend episodes: `10`, `1,2,3,5`, `1-10`, or `all`.",
                keyboard=InlineKeyboardMarkup([[InlineKeyboardButton("Cancel", callback_data=cb("cancel", state))]])
            )

        else:
            show_search_results(client, user_id, video_url, status_msg)

    except Exception as e:
        print(f"Error during initial processing for user {user_id}: {e}")
        traceback.print_exc()
        edit_message(status_msg, f"An error occurred: {e}")
        if user_id in config_value("user_states"):
            del config_value("user_states")[user_id]


@app.on_message(filters.command(["download", "dl"]) & DOWNLOAD_ACCESS_FILTER)
@check_active_download
def download_command(client, message: Message):
    user_id = message.from_user.id
    global crunchyroll, license_handler, vid_token
    if config_value("use_account") and config_value("Email") and config_value("Password"):
        vid_token = auth.get_user_token(config_value("Email"), config_value("Password"), allow_guest_fallback=False)
        if not vid_token:
            message.reply_text(
                f"Crunchyroll account login failed: `{auth.last_auth_error or 'unknown error'}`\n"
                "Premium videos require a working account token. Set `use_account = False` for guest/free mode.",
                parse_mode=enums.ParseMode.MARKDOWN
            )
            return
    else:
        vid_token = auth.get_guest_token()
    if not vid_token:
        raise Exception("Failed to authenticate with Crunchyroll.")

    crunchyroll = Crunchyroll(
        vid_token,
        playback_endpoint=auth.playback_endpoint,
        playback_user_agent=auth.playback_user_agent,
        auth_instance=auth,
        email=config_value("Email") if config_value("use_account") else None,
        password=config_value("Password") if config_value("use_account") else None,
    )
    license_handler = CrunchyrollLicense()
    print("Crunchyroll token ready.")
    if len(message.command) < 2:
        message.reply_text(
            "Please provide a Crunchyroll URL or search title.\nExample: `/download one piece` or `/dl <url>`",
            parse_mode=enums.ParseMode.MARKDOWN
        )
        return

    video_url = " ".join(message.command[1:]).strip()

    with _state_lock:
        existing = config_value("user_states").get(user_id)
        if existing is not None and existing.get("step") != "downloading":
            # Replacing an in-flight selection would orphan the old status
            # message and leave its keyboard resolving against the new state.
            message.reply_text(
                "You already have a selection in progress. Use /cancel to discard it first."
            )
            return
        config_value("user_states")[user_id] = {
            "step": "initial",
            "url": video_url,
            "data": {},
            "message": message.reply_text("Processing URL..."),
            "is_series": False,
            # Identifies this session. Buttons carry it so a tap on an old
            # keyboard cannot advance whatever session is current now.
            "nonce": uuid.uuid4().hex[:12],
        }
        status_msg = config_value("user_states")[user_id]["message"]

    process_download_url(client, user_id, video_url, status_msg)


@app.on_message(filters.text & ~filters.command([
    "start", "help", "download", "dl", "cancel",
    "addpremium", "rempremium", "listpremium",
    "addsudo", "remsudo", "listsudo"
]) & filters.private)
def handle_text_reply(client, message: Message):
    user_id = message.from_user.id
    if user_id in config_value("user_states") and config_value("user_states")[user_id]["step"] == "ask_episode_count":
        state = config_value("user_states")[user_id]
        status_msg = state["message"]
        try:
            total_episodes = state["data"]["total_episodes"]
            episode_indices = parse_episode_selection(message.text.strip(), total_episodes)
            state["data"]["episodes"] = [
                state["data"]["episodes"][episode_index]
                for episode_index in episode_indices
            ]
            state["data"]["episodes_to_download_count"] = len(state["data"]["episodes"])

            edit_message(status_msg, "Fetching info for the first accessible selected episode...")

            video_info = None
            mpd_content = None
            for episode in state["data"]["episodes"]:
                video_info = crunchyroll.get_video_info(episode["guid"])
                if not video_info:
                    continue
                _, mpd_content, _ = crunchyroll.get_pssh(video_info)
                if mpd_content:
                    break

            if not video_info or not mpd_content:
                edit_message(
                    status_msg,
                    "Selected episodes are not accessible with the current token. Premium account access may be required."
                )
                del config_value("user_states")[user_id]
                return

            video_list, _ = parse_mpd_content(mpd_content)
            if not video_list:
                edit_message(status_msg, "No video streams found for the selected episodes.")
                del config_value("user_states")[user_id]
                return

            state["data"]["video_info"] = video_info
            state["data"]["available_video_qualities"] = video_list

            ask_video_quality(client, user_id)
        except ValueError:
            message.reply_text(
                f"Invalid input. Send `10`, `1,2,3,5`, `1-10`, or `all` within 1-{state['data']['total_episodes']}.",
                parse_mode=enums.ParseMode.MARKDOWN
            )
        except Exception as e:
            print(f"Error processing episode count for user {user_id}: {e}")
            traceback.print_exc()
            edit_message(status_msg, f"An error occurred: {e}")
            del config_value("user_states")[user_id]


def ask_video_quality(client, user_id):
    if user_id not in config_value("user_states"):
        return
    state = config_value("user_states")[user_id]
    status_msg = state["message"]

    video_list = state["data"]["available_video_qualities"]
    _, max_quality_p = get_user_limits(user_id)

    buttons = []
    for i, video in enumerate(video_list):
        height = int(video.get('height', 0))
        if height <= max_quality_p:
            label = f"{height}p ({int(video.get('bandwidth', 0)) // 1000} kbps)"
            buttons.append([InlineKeyboardButton(label, callback_data=cb(f"quality_{i}", state))])

    if not buttons:
        edit_message(status_msg, "No video qualities available within your limits.")
        del config_value("user_states")[user_id]
        return

    buttons.append([InlineKeyboardButton("Cancel", callback_data=cb("cancel", state))])
    keyboard = InlineKeyboardMarkup(buttons)
    state["step"] = "select_quality"
    edit_message(status_msg, "Select video quality:", keyboard=keyboard)


def ask_audio_language(client, user_id):
    if user_id not in config_value("user_states"):
        return
    state = config_value("user_states")[user_id]
    status_msg = state["message"]
    video_info = state["data"]["video_info"]

    if 'versions' not in video_info or not video_info['versions']:
        edit_message(status_msg, "No audio versions found for this video.")
        state["data"]["selected_audios"] = []
        ask_subtitles(client, user_id)
        return

    max_audios, _ = get_user_limits(user_id)
    state["data"]["selected_audios"] = []

    buttons = []
    audio_options = {}
    for index, version in enumerate(video_info['versions']):
        locale = version['audio_locale']
        guid = version['guid']
        lang_name = config_value("locale_map").get(locale, locale)
        audio_options[guid] = locale
        buttons.append([InlineKeyboardButton(lang_name, callback_data=cb(f"audio_{guid}", state))])

    state["data"]["available_audio_options"] = audio_options

    buttons.append([
        InlineKeyboardButton(f"Done (0/{max_audios if max_audios != float('inf') else '∞'})", callback_data=cb("audio_done", state)),
        InlineKeyboardButton("Cancel", callback_data="cancel")
    ])
    keyboard = InlineKeyboardMarkup(buttons)
    state["step"] = "select_audio"
    edit_message(
        status_msg,
        f"Select audio language(s) (Max: {'unlimited' if max_audios == float('inf') else max_audios}). Press 'Done' when finished.",
        keyboard=keyboard
    )


def ask_subtitles(client, user_id):
    if user_id not in config_value("user_states"):
        return
    state = config_value("user_states")[user_id]
    status_msg = state["message"]
    video_info = state["data"]["video_info"]
    available_tracks = []
    track_info_list = []

    def add_track(lang, data, track_type):
        if lang == "none" or 'url' not in data or not data['url']:
            return
        label_prefix = "[CC]" if track_type == 'caption' else "[SUB]"
        lang_display = config_value("locale_map").get(lang, lang)
        label = f"{label_prefix} {lang_display}"
        available_tracks.append(label)
        track_info_list.append({
            'type': track_type,
            'language': lang,
            'url': data['url'],
            'format': data.get('format', 'vtt'),
            'display_name': lang_display
        })

    if 'captions' in video_info and video_info['captions']:
        for lang, data in video_info['captions'].items():
            add_track(lang, data, 'caption')

    if 'subtitles' in video_info and video_info['subtitles']:
        for lang, data in video_info['subtitles'].items():
            add_track(lang, data, 'subtitle')

    if not track_info_list:
        edit_message(status_msg, "No subtitles/captions available. Proceeding to download.")
        state["data"]["selected_subtitles"] = []
        state["data"]["available_subtitle_options"] = []
        state["step"] = "confirm_download"
        confirm_download(client, user_id)
        return

    state["data"]["selected_subtitles"] = []
    state["data"]["available_subtitle_options"] = track_info_list

    buttons = []
    for i, track in enumerate(track_info_list):
        buttons.append([InlineKeyboardButton(available_tracks[i], callback_data=cb(f"sub_{i}", state))])

    buttons.append([
        InlineKeyboardButton("Done (0 selected)", callback_data=cb("sub_done", state)),
        InlineKeyboardButton("Cancel", callback_data="cancel")
    ])
    keyboard = InlineKeyboardMarkup(buttons)
    state["step"] = "select_subtitles"
    edit_message(
        status_msg,
        "Select subtitle/caption track(s). Press 'Done' when finished.",
        keyboard=keyboard
    )

def confirm_download(client, user_id):
    """Shows final selections and asks for confirmation."""
    if user_id not in config_value("user_states"):
        return
    state = config_value("user_states")[user_id]
    status_msg = state["message"]

    sel_quality = state["data"]["selected_video_quality"]
    sel_audios = state["data"]["selected_audios"]
    sel_subs = state["data"]["selected_subtitles"]

    summary = "**Download Summary:**\n\n"
    if state["is_series"]:
        summary += f"**Series:** {state['data']['series_title']}\n"
        summary += f"**Episodes:** {state['data']['episodes_to_download_count']}\n"
    else:
        content_id = state["data"]["id"]
        episode_info = crunchyroll.get_single_info(content_id)["data"][0]
        anime = re.sub(r"\s*\([^)]*\)", "", episode_info["episode_metadata"]["season_title"])
        season_num = str(episode_info["episode_metadata"]["season_number"]).zfill(2)
        episode_num = str(episode_info["episode_metadata"]["episode_number"]).zfill(2)
        ep_number = f"S{season_num}E{episode_num}"
        title = episode_info["title"]
        summary += f"**Anime:** {anime}\n"
        summary += f"**Episode Title:** {title}\n"
        summary += f"**Episode No:** {ep_number}\n"

    summary += f"**Quality:** {sel_quality['height']}p\n"
    summary += f"**Audio:** {', '.join([a['audio_locale'] for a in sel_audios]) if sel_audios else 'None'}\n"
    subs_text = ', '.join([f"{s['language']} ({s['format']})" for s in sel_subs]) if sel_subs else 'None'
    summary += f"Subtitles: {subs_text}\n"
    buttons = [
        [InlineKeyboardButton("Start Download", callback_data=cb("confirm_start", state))],
        [InlineKeyboardButton("Cancel", callback_data=cb("cancel", state))]
    ]
    keyboard = InlineKeyboardMarkup(buttons)
    state["step"] = "confirm_download"
    edit_message(status_msg, summary, keyboard=keyboard)


@app.on_callback_query()
@check_active_download
def handle_callback_query(client, query: CallbackQuery):
    user_id = query.from_user.id
    data = query.data

    if user_id not in config_value("user_states"):
        query.answer("Session expired or invalid state. Please start again with /download.", show_alert=True)
        with suppress(Exception):
            query.message.delete()
        return

    state = config_value("user_states")[user_id]
    status_msg = state["message"]
    step = state["step"]

    # A keyboard from a previous session carries that session's nonce. Without
    # this check a tap on an old "Start Download" advances the session that
    # happens to be current now, which is not what the user was looking at.
    action, nonce = split_callback(data)
    if nonce is not None and nonce != session_nonce(state):
        query.answer("This selection is from an earlier request. Please start again.",
                     show_alert=True)
        return

    try:
        if action == "cancel":
            query.answer("Cancelled")
            edit_message(status_msg, "Download process cancelled.")
            request_cancel(user_id)
            return

        if step == "select_search" and action.startswith("search_"):
            search_index = int(action.split("_")[1])
            search_results = state["data"].get("search_results", [])
            if search_index < 0 or search_index >= len(search_results):
                query.answer("Invalid search result.", show_alert=True)
                return
            selected = search_results[search_index]
            query.answer(f"Selected: {selected['title'][:50]}")
            state["url"] = selected["url"]
            state["data"] = {}
            state["is_series"] = False
            state["step"] = "initial"
            edit_message(status_msg, f"Selected `{selected['title']}`. Processing...")
            process_download_url(client, user_id, selected["url"], status_msg)
            return

        if step == "select_quality" and action.startswith("quality_"):
            quality_index = int(action.split("_")[1])
            qualities = state["data"].get("available_video_qualities", [])
            if quality_index < 0 or quality_index >= len(qualities):
                query.answer("That quality is no longer available.", show_alert=True)
                return
            selected_quality = qualities[quality_index]
            state["data"]["selected_video_quality"] = selected_quality
            query.answer(f"Selected: {selected_quality['height']}p")
            ask_audio_language(client, user_id)

        elif step == "select_audio":
            max_audios, _ = get_user_limits(user_id)

            if action == "audio_done":
                if not state["data"]["selected_audios"]:
                    query.answer("Proceeding without audio selection.")
                else:
                    query.answer("Audio selection complete.")
                ask_subtitles(client, user_id)
                return

            elif action.startswith("audio_"):
                guid = action.split("_")[1]
                locale_name = config_value("locale_map").get(state["data"]["available_audio_options"][guid], state["data"]["available_audio_options"][guid])

                already_selected = False
                for i, audio in enumerate(state["data"]["selected_audios"]):
                    if audio['guid'] == guid:
                        state["data"]["selected_audios"].pop(i)
                        already_selected = True
                        query.answer(f"Removed: {locale_name}")
                        break

                if not already_selected:
                    if len(state["data"]["selected_audios"]) < max_audios:
                        state["data"]["selected_audios"].append({'audio_locale': locale_name, 'guid': guid})
                        query.answer(f"Added: {locale_name}")
                    else:
                        query.answer(f"You can select max {max_audios} audio tracks.", show_alert=True)
                        return

                current_selection_count = len(state["data"]["selected_audios"])
                buttons = []
                selected_guids = {a['guid'] for a in state["data"]["selected_audios"]}

                for btn_guid, btn_locale in state["data"]["available_audio_options"].items():
                    btn_lang_name = config_value("locale_map").get(btn_locale, btn_locale)
                    prefix = "✅ " if btn_guid in selected_guids else ""
                    buttons.append([InlineKeyboardButton(f"{prefix}{btn_lang_name}", callback_data=cb(f"audio_{btn_guid}", state))])

                buttons.append([
                    InlineKeyboardButton(f"Done ({current_selection_count}/{max_audios if max_audios != float('inf') else '∞'})", callback_data=cb("audio_done", state)),
                    InlineKeyboardButton("Cancel", callback_data="cancel")
                ])
                query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(buttons))

        elif step == "select_subtitles":

            if action == "sub_done":
                query.answer("Subtitle selection complete.")
                confirm_download(client, user_id)
                return
            elif action.startswith("sub_"):
                sub_index = int(action.split("_")[1])
                subtitle_options = state["data"].get("available_subtitle_options", [])
                if sub_index < 0 or sub_index >= len(subtitle_options):
                    query.answer("That subtitle track is no longer available.", show_alert=True)
                    return
                track_info = subtitle_options[sub_index]

                already_selected = False
                for i, sub in enumerate(state["data"]["selected_subtitles"]):
                    if sub['url'] == track_info['url']:
                        state["data"]["selected_subtitles"].pop(i)
                        already_selected = True
                        query.answer(f"Removed: {track_info['display_name']}")
                        break

                if not already_selected:
                    state["data"]["selected_subtitles"].append({
                        'language': track_info['display_name'],
                        'url': track_info['url'],
                        'format': track_info['format'],
                        'type': track_info['type'],
                        'original_locale': track_info['language']
                    })
                    query.answer(f"Added: {track_info['display_name']}")

                current_selection_count = len(state["data"]["selected_subtitles"])
                buttons = []
                selected_urls = {s['url'] for s in state["data"]["selected_subtitles"]}
                type_labels = {
                    "subtitle": "SUB",
                    "caption": "CC",
                }

                for i, track in enumerate(state["data"]["available_subtitle_options"]):
                    type_tag = type_labels.get(track['type'], track['type'].upper())
                    label = f"[{type_tag}] {track['display_name']}"
                    prefix = "✅ " if track['url'] in selected_urls else ""
                    buttons.append([InlineKeyboardButton(f"{prefix}{label}", callback_data=cb(f"sub_{i}", state))])

                buttons.append([
                    InlineKeyboardButton(f"Done ({current_selection_count} selected)", callback_data=cb("sub_done", state)),
                    InlineKeyboardButton("Cancel", callback_data="cancel")
                ])
                query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(buttons))

        elif step == "confirm_download" and action == "confirm_start":
            # Claim the transition atomically: a double-tapped button must not
            # start the same job twice on two worker threads.
            if not begin_active_download(user_id, "confirm_download"):
                query.answer("This download has already started.", show_alert=True)
                return
            query.answer("Starting download...")
            process_download(client, user_id)

    except MessageNotModified:
        query.answer()
    except QueryIdInvalid:
        query.answer("Button expired or invalid.", show_alert=True)
    except Exception as e:
        print(f"Error in callback query handler for user {user_id}: {e}")
        traceback.print_exc()
        query.answer("An error occurred.", show_alert=True)
        # Keep the session so the user can retry from where they were instead of
        # silently losing every selection they had made. Only release the
        # concurrency guard, which the handler itself set.
        with suppress(Exception):
            config_value("active_downloads").pop(user_id, None)
        with suppress(Exception):
            status_msg.edit_text(f"An error occurred: {e}\n\nPlease try again.")


def process_download(client, user_id):
    state = config_value("user_states").get(user_id)
    if not state or state["step"] != "downloading":
        print(f"Error: Invalid state for download process (User: {user_id})")
        with suppress(Exception):
            config_value("active_downloads").pop(user_id, None)
        return

    # Capture the job identity once. Later checks compare this, so a cancel for
    # a newer job can never be mistaken for this one (or vice versa).
    job_id = state.get("job_id")
    cancel_event = state.get("cancel_event")
    # Media stages poll this so a cancel tears down curl/ffmpeg immediately
    # instead of only being noticed at the next episode boundary.
    status_msg = state["message"]
    is_series = state["is_series"]
    final_output_files = []
    try:
        if is_series:
            episodes_to_download = state["data"]["episodes"]
            series_anime_title = re.sub(r'[<>:\"\'/\\|?*]', '', state["data"]["series_title"])
            # Resolved properly under Downloads/ later; creating a relative
            # directory here would litter the process working directory and
            # fail outright if that directory is not writable.
            series_output_dir = series_anime_title
            total_episodes = len(episodes_to_download)

            edit_message(status_msg, f"Starting batch download for '{series_anime_title}' ({total_episodes} episodes)...")

            for i, episode_info in enumerate(episodes_to_download):
                if is_job_cancelled(job_id):
                    edit_message(status_msg, "Download cancelled by user.")
                    return
                ep_num_str = f"Episode {i+1}/{total_episodes}"
                ep_id = episode_info['guid']
                edit_message(status_msg, f"Processing {ep_num_str}: Fetching info...")

                video_info = crunchyroll.get_video_info(ep_id)
                if not video_info:
                    reason = crunchyroll.last_playback_error or "not accessible"
                    edit_message(status_msg, f"{ep_num_str}: {reason}. Skipping.")
                    continue

                pssh, mpd_content, token = crunchyroll.get_pssh(video_info)
                if not mpd_content:
                    edit_message(status_msg, f"{ep_num_str}: Failed to fetch MPD. Skipping.")
                    continue

                wanted_video_quality = state["data"]["selected_video_quality"]
                episode_video_list, _ = parse_mpd_content(mpd_content)
                selected_video_quality = next((video for video in episode_video_list if video['height'] == wanted_video_quality['height']), None)
                if not selected_video_quality:
                    edit_message(status_msg, f"{ep_num_str}: Selected video quality is not available. Skipping.")
                    continue

                # Resolve the track first so its default_KID can select the right key.
                video_key_str = get_decryption_key(
                    license_handler.get_license(pssh, token, ep_id, crunchyroll.token),
                    selected_video_quality.get('kid'),
                )
                if not video_key_str:
                    edit_message(status_msg, f"{ep_num_str}: Failed to get video license key. Skipping.")
                    continue

                vidseg = get_segment_link_list(mpd_content, selected_video_quality['name'], selected_video_quality['base_url'], document_url=crunchyroll.mpd_document_url)
                if not vidseg or "all" not in vidseg:
                    edit_message(status_msg, f"{ep_num_str}: Failed to get video segments. Skipping.")
                    continue

                episode_selected_audios_details = []
                for selected_audio in state["data"]["selected_audios"]:
                    target_guid = None

                    for version in video_info.get('versions', []):
                        if config_value("locale_map").get(version.get('audio_locale'), version.get('audio_locale')) == selected_audio['audio_locale']:
                            target_guid = version.get('guid')
                            break

                    if not target_guid:
                        print(f"Warning: Audio locale {selected_audio['audio_locale']} not found in episode {ep_id}. Skipping audio track.")
                        continue

                    audio_ver_info = crunchyroll.get_video_info(target_guid)
                    if not audio_ver_info:
                        continue

                    audio_pssh, audio_mpd, audio_token = crunchyroll.get_pssh(audio_ver_info)
                    if not audio_mpd:
                        continue

                    _, audio_mpd_audio_list = parse_mpd_content(audio_mpd)
                    highest_audio = max(audio_mpd_audio_list, key=lambda x: int(x.get('bandwidth', 0)), default=None)
                    if not highest_audio:
                        continue

                    audio_keys = get_decryption_key(
                        license_handler.get_license(audio_pssh, audio_token, target_guid, crunchyroll.token),
                        highest_audio.get('kid'),
                    )
                    if not audio_keys:
                        continue

                    audseg = get_segment_link_list(audio_mpd, highest_audio['name'], highest_audio['base_url'], document_url=crunchyroll.mpd_document_url)
                    if not audseg or "all" not in audseg:
                        continue

                    episode_selected_audios_details.append({
                        'audio_locale': selected_audio['audio_locale'],
                        'key': audio_keys,
                        'segment': audseg
                    })

                episode_selected_subtitles = []
                available_episode_subs = {}
                if 'subtitles' in video_info and video_info['subtitles']:
                    for lang, data in video_info['subtitles'].items():
                        if lang != 'none' and 'url' in data:
                            available_episode_subs[lang] = data
                if 'captions' in video_info and video_info['captions']:
                    for lang, data in video_info['captions'].items():
                        if 'url' in data:
                            available_episode_subs[f"{lang}_caption"] = data

                for sel_sub in state["data"]["selected_subtitles"]:
                    found_sub_data = None
                    original_locale = sel_sub.get('original_locale')
                    sub_type = sel_sub.get('type')

                    key_to_find = f"{original_locale}_caption" if sub_type == 'caption' else original_locale

                    if key_to_find in available_episode_subs:
                        found_sub_data = available_episode_subs[key_to_find]
                    elif original_locale in available_episode_subs:
                        found_sub_data = available_episode_subs[original_locale]

                    if found_sub_data and found_sub_data.get('url'):
                        episode_selected_subtitles.append({
                            'language': sel_sub['language'],
                            'url': found_sub_data['url'],
                            'format': found_sub_data.get('format', 'vtt'),
                            'type': sel_sub['type']
                        })
                    else:
                        print(f"Warning: Subtitle {sel_sub['language']} not found in episode {ep_id}. Skipping subtitle track.")

                ep_info = crunchyroll.get_single_info(ep_id)["data"][0]
                ep_meta = ep_info["episode_metadata"]
                season_num = str(ep_meta["season_number"]).zfill(2)
                ep_num = str(ep_meta.get("episode_number", i + 1)).zfill(2)
                ep_title_str = ep_info["title"]

                base_anime_title = series_anime_title
                if not base_anime_title and ep_meta.get("season_title"):
                    base_anime_title = re.sub(r"\s*\([^)]*\)", "", ep_meta["season_title"])

                title = f"{base_anime_title}.S{season_num}E{ep_num}-{ep_title_str}"
                if config_value("use_custom_title"):
                    try:
                        title = config_value("Custom_Title").format(
                            Title=base_anime_title,
                            Episode=ep_num,
                            Season=season_num,
                            EpTitle=ep_title_str
                        )
                    except AttributeError:
                        print("Warning: `Custom_Title` in config.py must be a format string.")
                    except KeyError as ke:
                        print(f"Warning: Missing key in Custom_Title format: {ke}")

                title = re.sub(r'[<>:\"\'/\\|?*]', '', title)

                temp_files = []
                final_ep_output = download_decrypt_merge_single(
                    client, user_id, status_msg,
                    title, vidseg, video_key_str,
                    episode_selected_audios_details,
                    episode_selected_subtitles,
                    selected_video_quality,
                    temp_files,
                    output_directory=series_output_dir,
                    progress_prefix=f"{ep_num_str}: ",
                    cancel_event=cancel_event,
                )

                if final_ep_output:
                    final_output_files.append(final_ep_output)
                    edit_message(status_msg, f"{ep_num_str}📤 **Uploading...**")
                    uploader = tgUploader(app, status_msg)
                    ok, detail = uploader.upload_file(final_ep_output)
                    if not ok:
                        print(f"{ep_num_str}: upload failed: {detail}")
                else:
                    edit_message(status_msg, f"{ep_num_str}: Failed to process episode.")

                edit_message(status_msg, f"{ep_num_str}: Cleaning up temporary files...")
                cleanup_files(temp_files)

            if final_output_files:
                edit_message(status_msg, f"Batch download complete for '{series_anime_title}'.\nDownloaded {len(final_output_files)} episodes.")
            else:
                edit_message(status_msg, f"Batch download finished for '{series_anime_title}', but no episodes were successfully processed.")

        else:
            video_info = state["data"]["video_info"]
            content_id = state["data"]["id"]
            pssh = state["data"]["pssh"]
            mpd_content = state["data"]["mpd_content"]
            token = state["data"]["drm_token"]
            selected_video_quality = state["data"]["selected_video_quality"]
            selected_audios = state["data"]["selected_audios"]
            selected_subtitles = state["data"]["selected_subtitles"]

            edit_message(status_msg, "Starting download...")

            # Re-resolve the track from the MPD so the KID is present even if the
            # stored selection predates it; fall back to the stored entry.
            _video_tracks, _ = parse_mpd_content(mpd_content)
            video_track = next((v for v in _video_tracks
                                if v.get('name') == selected_video_quality.get('name')),
                               selected_video_quality)
            video_key_str = get_decryption_key(
                license_handler.get_license(pssh, token, content_id, crunchyroll.token),
                video_track.get('kid'),
            )
            if not video_key_str:
                raise Exception("Failed to get video license key.")

            vidseg = get_segment_link_list(mpd_content, selected_video_quality['name'], selected_video_quality['base_url'], document_url=crunchyroll.mpd_document_url)
            if not vidseg or "all" not in vidseg:
                raise Exception("Failed to get video segments.")

            detailed_audios = []
            edit_message(status_msg, "Fetching audio details...")
            for audio in selected_audios:
                guid = audio['guid']
                locale_name = audio['audio_locale']
                info = crunchyroll.get_video_info(guid)
                if not info:
                    continue

                audio_pssh, audio_mpd, audio_token = crunchyroll.get_pssh(info)
                if not audio_mpd:
                    continue

                _, audio_mpd_audio_list = parse_mpd_content(audio_mpd)
                highest_audio = max(audio_mpd_audio_list, key=lambda x: int(x.get('bandwidth', 0)), default=None)
                if not highest_audio:
                    continue

                audio_keys = get_decryption_key(
                    license_handler.get_license(audio_pssh, audio_token, guid, crunchyroll.token),
                    highest_audio.get('kid'),
                )
                if not audio_keys:
                    print(f"Warning: Failed to get audio license key for {locale_name}. Skipping audio track.")
                    continue

                audseg = get_segment_link_list(audio_mpd, highest_audio['name'], highest_audio['base_url'], document_url=crunchyroll.mpd_document_url)
                if not audseg or "all" not in audseg:
                    continue

                detailed_audios.append({
                    'audio_locale': locale_name,
                    'key': audio_keys,
                    'segment': audseg
                })

            content_id = state["data"]["id"]
            ep_info = crunchyroll.get_single_info(content_id)["data"][0]
            ep_meta = ep_info["episode_metadata"]
            anime = re.sub(r"\s*\([^)]*\)", "", ep_meta["season_title"])
            season_num = str(ep_meta["season_number"]).zfill(2)
            ep_num = str(ep_meta.get("episode_number", 0)).zfill(2)
            ep_title_str = ep_info["title"]

            title = f"{anime}.S{season_num}E{ep_num}-{ep_title_str}"
            if config_value("use_custom_title"):
                try:
                    title = config_value("Custom_Title").format(Title=anime, Episode=ep_num, Season=season_num, EpTitle=ep_title_str)
                except AttributeError:
                    pass
                except KeyError:
                    pass
            title = re.sub(r'[<>:\"\'/\\|?*]', '', title)

            temp_files = []
            final_output_path = download_decrypt_merge_single(
                client, user_id, status_msg,
                title, vidseg, video_key_str,
                detailed_audios, selected_subtitles,
                selected_video_quality, temp_files,
                cancel_event=cancel_event,
            )

            if final_output_path:
                edit_message(status_msg, "📤 **Uploading...**")
                uploader = tgUploader(app, status_msg)
                ok, detail = uploader.upload_file(final_output_path)
                if ok:
                    edit_message(status_msg, f"Upload complete: `{os.path.basename(final_output_path)}`")
                else:
                    edit_message(status_msg, f"Upload failed: `{detail}`")
            else:
                edit_message(status_msg, "Download failed during processing.")

            print("Cleaning up temporary files...")
            cleanup_files(temp_files)

    except Exception as e:
        print(f"Error during download process for user {user_id}: {e}")
        traceback.print_exc()
        edit_message(status_msg, f"An error occurred during download: {e}")
        cleanup_files(temp_files if 'temp_files' in locals() else [])

    finally:
        # Only tear down the session this worker owns. After /cancel the user may
        # have started a new one; deleting that would strand them mid-flow.
        finish_active_download(user_id, state)


def download_decrypt_merge_single(
    client, user_id, status_msg, title, vidseg, video_key_str,
    detailed_audios, selected_subtitles, video_quality_info, temp_files,
    output_directory="", progress_prefix="", cancel_event=None
):

    if output_directory:
        final_output_dir = get_download_path(output_directory)
        os.makedirs(final_output_dir, exist_ok=True)
    else:
        final_output_dir = get_download_path()

    temp_job_dir = get_temp_path(output_directory or "_single", title)
    os.makedirs(temp_job_dir, exist_ok=True)

    base_filename = os.path.join(final_output_dir, title)
    dec_video_path = os.path.join(temp_job_dir, f"{title}.mp4")
    audio_files = []
    subtitle_files = []

    temp_files.append(temp_job_dir)
    temp_files.append(get_temp_path(f"enc_{title}"))
    try:
        edit_message(status_msg, f"{progress_prefix}Downloading video... \n\n `{dec_video_path}` \n\n P.S: It takes few minutes to download depending on the quality of the video selected.")
        segment_headers = {"User-Agent": auth.playback_user_agent}
        download_segment(vidseg["all"], f"enc_{title}", "mp4", headers=segment_headers,
                        cancel_event=cancel_event)
        edit_message(status_msg, f"{progress_prefix}Video download complete.")

        for i, audio in enumerate(detailed_audios):
            locale = audio['audio_locale']
            edit_message(status_msg, f"{progress_prefix}Downloading audio {i+1}/{len(detailed_audios)} ({locale})... \n\n `{title}_{locale}.m4a` \n\n P.S: It takes few minutes to download depending on the number of audio selected.")
            enc_audio_base = f"enc_{title}_{locale}"
            download_segment(audio['segment']["all"], enc_audio_base, "m4a", headers=segment_headers,
                            cancel_event=cancel_event)
            temp_files.append(get_temp_path(enc_audio_base))
            edit_message(status_msg, f"{progress_prefix}Audio '{locale}' download complete.")

        if selected_subtitles:
            edit_message(status_msg, f"{progress_prefix}Downloading subtitles...")
            for i, sub in enumerate(selected_subtitles):
                sub_lang = sub['language']
                sub_format = sub['format']
                sub_url = sub['url']
                sub_temp_path = os.path.join(temp_job_dir, f"{title}_{sub_lang}.{sub_format}")
                sub_final_path = os.path.join(temp_job_dir, f"{title}_{sub_lang}.srt")

                curl_cmd = [resolve_executable("curl", project_fallback=False), "-fsSL", "-o", sub_temp_path, sub_url]
                _, stderr, retcode = run_shell_command(curl_cmd, cancel_event=cancel_event)
                if retcode != 0:
                    print(f"Subtitle download failed for {sub_lang}: {stderr}")
                    continue

                temp_files.append(sub_temp_path)

                if subtitle_needs_srt(sub_format, resolve_keep_ass_subtitles(), config_value("output_format")):
                    try:
                        if sub_format.lower() == 'ass':
                            convert_ass_to_srt_custom(sub_temp_path, sub_final_path)
                        else:
                            convert_vtt_to_srt_custom(sub_temp_path, sub_final_path)
                        subtitle_files.append({'path': sub_final_path, 'lang': sub['language'], 'title_lang': sub_lang, 'type': '.srt'})
                        temp_files.append(sub_final_path)
                    except Exception as conv_e:
                        print(f"Subtitle to SRT conversion failed for {sub_lang}: {conv_e}")
                else:
                    subtitle_files.append({'path': sub_temp_path, 'lang': sub['language'], 'title_lang': sub_lang, 'type': sub['type']})

            edit_message(status_msg, f"{progress_prefix}Subtitle downloads complete.")

        edit_message(status_msg, f"{progress_prefix}Decrypting video...")
        enc_video_path = get_encrypted_media_path(f"enc_{title}", "mp4")
        decrypt_cmd = [resolve_executable("mp4decrypt"), enc_video_path, dec_video_path, "--show-progress", "--key", video_key_str]
        _, stderr, retcode = run_shell_command(decrypt_cmd, cancel_event=cancel_event)
        if retcode != 0:
            raise Exception(f"Video decryption failed: {stderr}")
        edit_message(status_msg, f"{progress_prefix}Video decryption complete.")

        for i, audio in enumerate(detailed_audios):
            locale = audio['audio_locale']
            edit_message(status_msg, f"{progress_prefix}Decrypting audio {i+1}/{len(detailed_audios)} ({locale})...")
            enc_audio_path = get_encrypted_media_path(f"enc_{title}_{locale}", "m4a")
            dec_audio_path = os.path.join(temp_job_dir, f"{title}_{locale}.m4a")
            decrypt_cmd = [resolve_executable("mp4decrypt"), enc_audio_path, dec_audio_path, "--show-progress", "--key", audio['key']]
            _, stderr, retcode = run_shell_command(decrypt_cmd, cancel_event=cancel_event)
            if retcode != 0:
                print(f"Warning: Audio decryption failed for {locale}: {stderr}. Skipping audio track.")
                continue

            audio_files.append({'path': dec_audio_path, 'lang': config_value("locale_map").get(locale), 'title_lang': locale})
            temp_files.append(dec_audio_path)
            edit_message(status_msg, f"{progress_prefix}Audio '{locale}' decryption complete.")

        edit_message(status_msg, f"{progress_prefix}Merging files...")

        ffmpeg_cmd_list = [
            resolve_executable("ffmpeg", config_value("ffmpeg_path")),
            "-nostdin",
            "-y",
            "-i", dec_video_path
        ]

        for audio in audio_files:
            ffmpeg_cmd_list.extend(["-i", audio['path']])

        for sub in subtitle_files:
            ffmpeg_cmd_list.extend(["-i", sub['path']])

        encoding_cfg = resolve_encoding_config()
        map_commands = []
        metadata_commands = []
        watermark_name = globals().get("Watermark_Name", "")
        if encoding_cfg.use_watermark:
            filter_complex = get_filter_complex()
            ffmpeg_cmd_list.extend(["-filter_complex", filter_complex])
            map_commands.extend(["-map", "[v]"])
        else:
            map_commands.extend(["-map", "0:v?"])

        output_audio_langs = []
        for i, audio in enumerate(audio_files):
            stream_index = i + 1
            map_commands.extend(["-map", f"{stream_index}:a?"])
            lang_code = config_value("LANGUAGE_NAME_TO_ISO639_2B").get(audio['title_lang'], audio['title_lang']) if audio['title_lang'] else "und"
            title_lang = audio['title_lang']
            output_audio_langs.append(title_lang)
            if encoding_cfg.use_watermark:
                metadata_commands.extend([
                    f"-metadata:s:a:{i}", f"language={lang_code}",
                    f"-metadata:s:a:{i}", f'title={watermark_name} - [{title_lang}]'
                ])
            else:
                metadata_commands.extend([
                    f"-metadata:s:a:{i}", f"language={lang_code}",
                    f"-metadata:s:a:{i}", f'title=[{title_lang}]'
                ])

        output_sub_langs = []
        for i, sub in enumerate(subtitle_files):
            stream_index = len(audio_files) + i + 1
            map_commands.extend(["-map", f"{stream_index}:s?"])
            lang_code = config_value("LANGUAGE_NAME_TO_ISO639_2B").get(sub['title_lang'], sub['title_lang']) if sub['title_lang'] else "und"
            title_lang = sub['title_lang']
            sub_type = sub['type']
            output_sub_langs.append(f"{title_lang} ({os.path.splitext(sub['path'])[1][1:]})")
            if encoding_cfg.use_watermark:
                metadata_commands.extend([
                    f"-metadata:s:s:{i}", f"language={lang_code}",
                    f"-metadata:s:s:{i}", f'title={watermark_name} - [{title_lang}] [{sub_type}]'
                ])
            else:
                metadata_commands.extend([
                    f"-metadata:s:s:{i}", f"language={lang_code}",
                    f"-metadata:s:s:{i}", f'title=[{title_lang}] [{sub_type}]'
                ])

        quality_str = f"{video_quality_info['height']}p"
        audio_str = "+".join(output_audio_langs) if output_audio_langs else "NoAudio"
        sub_str = "+".join(output_sub_langs) if output_sub_langs else "NoSubs"
        watermark_suffix = f".{watermark_name}" if encoding_cfg.use_watermark else ""

        output_filename = f"{base_filename}.{quality_str}.[{audio_str}].[{sub_str}]{watermark_suffix}.{config_value('output_format')}"

        ffmpeg_cmd_list.extend(map_commands)
        ffmpeg_cmd_list.extend(metadata_commands)
        ffmpeg_cmd_list.extend(encoding_cfg.get_ffmpeg_args_list())
        ffmpeg_cmd_list.append(output_filename)

        edit_message(status_msg, f"{progress_prefix}Merging files... \n\n `{output_filename}` \n\n P.S: It takes few minutes to merge depending on the number of audio and subtitle selected.")

        full_ffmpeg_command = display_command(ffmpeg_cmd_list)

        _, stderr, retcode = run_shell_command(ffmpeg_cmd_list)
        if retcode != 0:
            error_log_path = f"{base_filename}_ffmpeg_error.log"
            with open(error_log_path, "w") as f:
                f.write(f"Command: {full_ffmpeg_command}\n\n")
                f.write(stderr)
            raise Exception(f"FFmpeg merging failed. See {error_log_path} for details.")

        edit_message(status_msg, f"{progress_prefix}Merging complete.")
        return output_filename

    except Exception as e:
        print(f"Error in download_decrypt_merge_single for {title}: {e}")
        traceback.print_exc()
        edit_message(status_msg, f"{progress_prefix}Error during processing: {e}")
        return None


def cleanup_files(file_paths):
    """Clean up temporary files after download process."""
    for file_path in file_paths:
        if file_path and os.path.exists(file_path):
            try:
                if os.path.isdir(file_path):
                    for root, dirs, files in os.walk(file_path, topdown=False):
                        for file_name in files:
                            os.remove(os.path.join(root, file_name))
                        for dir_name in dirs:
                            os.rmdir(os.path.join(root, dir_name))
                    os.rmdir(file_path)
                    if config_value("debug"):
                        print(f"Deleted directory: {file_path}")
                else:
                    os.remove(file_path)
                    if config_value("debug"):
                        print(f"Deleted file: {file_path}")
            except OSError as e:
                print(f"Error deleting file {file_path}: {e}")
    temp_dir = get_temp_path()
    if os.path.exists(temp_dir) and not os.listdir(temp_dir):
        try:
            os.rmdir(temp_dir)
            if config_value("debug"):
                print(f"Removed empty Temp directory: {temp_dir}")
        except OSError as e:
            print(f"Could not remove empty Temp directory: {e}")


if __name__ == "__main__":
    print("Starting bot...")
    app.run()
    print("Bot stopped.")
