
import re
import os
import shutil
import sys
import requests
from platform_tools import (
    display_command, quote_argument, resolve_executable, run_command, split_command,
)
from crunchyroll import (
    Crunchyroll, CrunchyrollAuth, CrunchyrollLicense,
    parse_mpd_content, get_segment_link_list, download_segment,
    get_filter_complex, convert_vtt_to_srt_custom, convert_ass_to_srt_custom,
    get_episode_display_number, get_episode_season_title,
    get_episode_title, parse_episode_selection, set_cr_debug, resolve_debug_settings,
    get_download_path, get_encrypted_media_path, get_temp_path,
    resolve_encoding_config, EncodingConfig, config_value, track_key,
    extract_content_key, LicenseError,
    resolve_batch_subtitles, resolve_batch_audios, resolve_video_quality,
    dedup_preserving_order, resolve_keep_ass_subtitles, subtitle_needs_srt,
)


def _force_utf8_console():
    """Series and episode titles routinely contain non-ASCII text.

    On a legacy Windows console Python binds stdout to the ANSI code page
    (cp1252/cp437), so printing such a title raises UnicodeEncodeError before any
    download starts. Reconfigure the streams to UTF-8 where that is supported.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass


_force_utf8_console()


HELP_TEXT = """Usage: python cli.py [--debug[=LEVEL] | --no-debug] [--lossy | --lossless | --mode=<mode>] [--keep-ass | --to-srt]

Interactive Crunchyroll downloader.

Options:
  --debug       Show safe auth/playback endpoint status details.
  --debug=LEVEL Set the log level explicitly (DEBUG, INFO, WARNING, ERROR).
  --no-debug    Force debug off, overriding debug=True in config.py.
  --lossy       Encode video in H.265 10-bit for small file size (default).
  --lossless    Direct stream copy (remux) for bit-for-bit source quality.
  --mode=<mode> Explicit encoding mode: lossy, lossless, custom.
  --keep-ass    Embed Crunchyroll's styled .ass subtitle in the MKV unchanged (default).
  --to-srt      Convert .ass subtitles to SRT instead of embedding them.

Inputs:
  URL or title search: one piece
  Search result: 1
  Episodes: 10        first 10 episodes
            1,2,3,5   exact list numbers
            1-10      range of list numbers
            all       every listed episode
"""

if any(arg in ("-h", "--help") for arg in sys.argv[1:]):
    print(HELP_TEXT)
    raise SystemExit(0)

CLI_DEBUG, DEBUG_LEVEL = resolve_debug_settings()
set_cr_debug(CLI_DEBUG)

cli_mode = None
cli_keep_ass = None
for arg in sys.argv[1:]:
    if arg in ("--lossy", "--lossyy", "--h265"):
        cli_mode = "lossy"
    elif arg in ("--lossless", "--losslessy", "--original"):
        cli_mode = "lossless"
    elif arg.startswith("--mode="):
        cli_mode = arg.split("=", 1)[1]
    elif arg in ("--keep-ass", "--keep-ass-subtitles"):
        cli_keep_ass = True
    elif arg in ("--to-srt", "--convert-ass"):
        cli_keep_ass = False

encoding_config = resolve_encoding_config(mode=cli_mode)
keep_ass = resolve_keep_ass_subtitles(cli_keep_ass)

print("Hello Welcome to Crunchyroll Downloader")
print(f"[{encoding_config.summary()}]")


hard_subtitle = None


def download_file(url, destination):
    response = requests.get(url, timeout=60)
    response.raise_for_status()
    with open(destination, "wb") as output:
        output.write(response.content)


def subtitle_stem(title, subtitle, extension):
    """Filename for a subtitle/caption track.

    Naming on title+language alone made an en-US caption and an en-US subtitle
    resolve to the same scratch file, so the second overwrote the first. The
    track kind is part of the name now.
    """
    kind = subtitle.get("type") if isinstance(subtitle, dict) else "subtitle"
    language = subtitle.get("language", "und") if isinstance(subtitle, dict) else "und"
    return f"{title}_{kind}_{language}.{extension}"


def decrypt_file(source, destination, key, cancel_event=None):
    tool = resolve_executable("mp4decrypt")
    command = [tool, source, destination, "--show-progress", "--key", key]
    result = run_command(command, cancel_event=cancel_event)
    if result.returncode != 0:
        raise RuntimeError(f"mp4decrypt failed ({result.returncode}): {display_command(command)}")


def run_ffmpeg(command, cancel_event=None):
    if isinstance(command, str):
        command = split_command(command)
    print("ffmpeg command:", display_command(command))
    result = run_command(command, cancel_event=cancel_event)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg failed with exit code {result.returncode}")


def format_episode_row(index, episode):
    episode_no = get_episode_display_number(episode, index)
    title = get_episode_title(episode, index)
    season_title = get_episode_season_title(episode)
    if season_title:
        return f"{index:>4}. E{episode_no} - {title} [{season_title}]"
    return f"{index:>4}. E{episode_no} - {title}"


def print_series_episode_list(series_title, seasons, episodes):
    print(f"Series: {series_title}")
    print(f"Seasons: {len(seasons)}")
    print(f"Total episodes listed: {len(episodes)}")
    if seasons:
        print("Season summary:")
        for index, season in enumerate(seasons, start=1):
            count = season.get("loaded_episodes") or season.get("number_of_episodes") or 0
            print(f"  {index}. {season.get('title', 'Unknown Season')} - {count} episodes")
    print("Episode list:")
    for index, episode in enumerate(episodes, start=1):
        print(format_episode_row(index, episode))


if CLI_DEBUG:
    import logging
    logging.basicConfig(
        level=DEBUG_LEVEL,
        format="[LOG %(levelname)s] %(message)s",
    )
auth = CrunchyrollAuth()
if config_value("use_account") and config_value("Email") and config_value("Password"):
    vid_token = auth.get_user_token(config_value("Email"), config_value("Password"), allow_guest_fallback=False)
    if not vid_token:
        print(f"Crunchyroll account login failed: {auth.last_auth_error or 'unknown error'}")
        print("Premium videos require a working account token. Set use_account = False for guest/free mode.")
        exit()
else:
    vid_token = auth.get_guest_token()
if not vid_token:
    print("Failed to authenticate with Crunchyroll")
    exit()
crunchyroll = Crunchyroll(
    vid_token,
    playback_endpoint=auth.playback_endpoint,
    playback_user_agent=auth.playback_user_agent,
    auth_instance=auth,
    email=config_value("Email") if config_value("use_account") else None,
    password=config_value("Password") if config_value("use_account") else None,
)
video_url = input("Enter the Crunchyroll video URL or search title: ").strip()

if "crunchyroll.com" not in video_url:
    search_results = crunchyroll.search(video_url, limit=5)
    if not search_results:
        print("No Crunchyroll search results found.")
        exit()

    print("Select a search result:")
    for index, result in enumerate(search_results, start=1):
        print(f"{index}. ({result['access']}) [{result['type']}] {result['title']}")

    try:
        search_choice = int(input("Enter result number: ")) - 1
    except ValueError:
        print("Invalid search result")
        exit()

    if search_choice < 0 or search_choice >= len(search_results):
        print("Invalid search result")
        exit()

    video_url = search_results[search_choice]["url"]
    print(f"Selected: {search_results[search_choice]['title']}")


if "watch" in video_url:
    match = re.search(r'"?https?://www\.crunchyroll\.com/(?:watch)/([^/"]+)', video_url)
    if not match:
        print("Invalid URL")
        exit()
    id =  match.group(1)
    video_info = crunchyroll.get_video_info(id)

    if not video_info:
        reason = crunchyroll.last_playback_error or "video not found"
        print(f"Video not accessible: {reason}")
        exit()
    pssh, mpd__content, token = crunchyroll.get_pssh(video_info)
    video_list, audio_list = parse_mpd_content(mpd__content)
    print("Select the video quality:")
    for i, video in enumerate(video_list):
        print(f"{i + 1}. {video['height']}p, bandwidth: {video['bandwidth']}")
    try:
        video_quality = int(input("Enter the video quality: ")) - 1
    except ValueError:
        print("Invalid input. Please enter a number.")
        exit()
    if video_quality < 0 or video_quality >= len(video_list):
        print("Invalid video quality")
        exit()
    video = video_list[video_quality]
    print("Select the desired audio track:")
    for index, version in enumerate(video_info['versions']):
        print(f"{index + 1}) {config_value('locale_map').get(version['audio_locale'],version['audio_locale'])}")    

    print("Note: \n1) The audio quality is automatically set to high quality.\n2) To select multiple audios, enter the numbers separated by commas (e.g., 1, 2, 3).")
    audio_list_input = input("Enter the desired audio(s): ")
    try:
        audio_list = [int(choice.strip()) - 1 for choice in audio_list_input.split(',')]
    except ValueError:
        print("Invalid input. Please enter numbers only.")
        exit()
    if any(choice < 0 or choice >= len(video_info['versions']) for choice in audio_list):
        print("Invalid choice(s). Please try again.")
        exit()

    selected_audios = [
                {'audio_locale': config_value("locale_map").get(video_info['versions'][choice]['audio_locale'], video_info['versions'][choice]['audio_locale']), 'guid': video_info['versions'][choice]['guid']}
                for choice in audio_list
            ]
    license_handler = CrunchyrollLicense()
    try:
        key = extract_content_key(
            license_handler.get_license(pssh, token, id, crunchyroll.token),
            f"episode {id}",
            video.get("kid"),
        )
    except LicenseError as exc:
        print(f"[ERROR] {exc}")
        exit()

    # Only fully resolved audio records (key + segments) reach downstream
    # stages; a license failure used to leave the entry in place and the later
    # download step then raised KeyError on the missing 'segment'.
    resolved_audios = []
    for audio in selected_audios:
        info = crunchyroll.get_video_info(audio['guid'])
        pssh, mpd_content, token = crunchyroll.get_pssh(info)
        video_list, audio_list = parse_mpd_content(mpd_content)
        highest_audio = max(audio_list, key=lambda x: x['bandwidth'], default=None)
        try:
            audio['key'] = extract_content_key(
                license_handler.get_license(pssh, token, audio['guid'], crunchyroll.token),
                audio.get('audio_locale', audio['guid']),
                (highest_audio or {}).get('kid'),
            )
        except LicenseError as exc:
            print(f"[WARN] Skipping audio track: {exc}")
            continue
        if highest_audio:
            audseg = get_segment_link_list(mpd_content, highest_audio['name'], highest_audio['base_url'], document_url=crunchyroll.mpd_document_url)
            if not audseg or 'all' not in audseg:
                print(f"[WARN] No audio segments for {audio.get('audio_locale')}; skipping.")
                continue
            audio['segment'] = audseg
        else:
            print("No audio found")
            continue
        resolved_audios.append(audio)

    selected_audios = [a for a in resolved_audios if a.get('key') and a.get('segment')]


    if ('captions' in video_info and video_info['captions']) or ('subtitles' in video_info and video_info['subtitles']):
        available_tracks = []
        track_info_list = []    


        if 'captions' in video_info and video_info['captions']:
            for lang, data in video_info['captions'].items():
                label = f"[CAPTION] {config_value('locale_map').get(lang, lang)}"
                available_tracks.append(label)
                track_info_list.append({
                    'type': 'caption',
                    'language': lang,
                    'url': data['url'],
                    'format': data['format']
                })  


        if 'subtitles' in video_info and video_info['subtitles']:
            for lang, data in video_info['subtitles'].items():
                if lang == "none" or 'url' not in data:
                    continue
                label = f"[SUBTITLE] {config_value('locale_map').get(lang, lang)}"
                available_tracks.append(label)
                track_info_list.append({
                    'type': 'subtitle',
                    'language': lang,
                    'url': data['url'],
                    'format': data['format']
                })  


        print("Available subtitle/caption tracks:")
        for i, label in enumerate(available_tracks, start=1):
            print(f"{i}. {label}")  

        subtitle_list_input = input("Enter the desired track number(s) (comma-separated for multiple): ")   

        try:
            subtitle_indices = [int(choice.strip()) - 1 for choice in subtitle_list_input.split(',')]
            if any(i < 0 or i >= len(track_info_list) for i in subtitle_indices):
                print("Invalid choice(s). Please try again.")
                exit()  

            selected_subtitles = []
            for i in subtitle_indices:
                entry = track_info_list[i]
                lang_display = config_value("locale_map").get(entry['language'], entry['language']) 
                selected_subtitles.append({
                    'language': lang_display,
                    'url': entry['url'],
                    'format': entry['format'],
                    'type': entry['type']
                })  


        except ValueError:
            print("Invalid input. Please enter numbers only.")
            exit()  

    else:
        print("No subtitles available for this video.")         
        selected_subtitles = False  


    vidseg = get_segment_link_list(mpd__content, video['name'], video['base_url'], document_url=crunchyroll.mpd_document_url)
    if not vidseg or "all" not in vidseg:
        print("Failed to resolve video segments for this episode.")
        exit()
    anime = re.sub(r"\s*\([^)]*\)", "", crunchyroll.get_single_info(id)["data"][0]["episode_metadata"]["season_title"])
    Title = anime + "." + "S" + str(crunchyroll.get_single_info(id)["data"][0]["episode_metadata"]["season_number"]).zfill(2) + "E" +  str(crunchyroll.get_single_info(id)["data"][0]["episode_metadata"]["episode_number"]).zfill(2) + "-" + crunchyroll.get_single_info(id)["data"][0]["title"]
    if config_value("use_custom_title"):
        Title = config_value("Custom_Title").format(Title=anime, Episode=crunchyroll.get_single_info(id)["data"][0]["episode_metadata"]["episode_number"], Season=crunchyroll.get_single_info(id)["data"][0]["episode_metadata"]["season_number"],EpTitle=crunchyroll.get_single_info(id)["data"][0]["title"])
    Title = re.sub(r'[<>:\"\'/\\|?*]', '', Title)   

    print("Downloading video file...")  

    segment_headers = {"User-Agent": crunchyroll.playback_user_agent}
    temp_title_dir = get_temp_path(Title, create_parent=True)
    dec_video_path = get_temp_path(Title, f"{Title}.mp4", create_parent=True)
    download_segment(vidseg["all"],"enc_"+Title,"mp4", headers=segment_headers)  

    print("Video downloaded successfully")  

    print("Downloading audio file...")  

    for audio in selected_audios:
        download_segment(audio['segment']["all"], f"enc_{Title}_{audio['audio_locale']}", "m4a", headers=segment_headers)
        print(f"Audio {audio['audio_locale']} downloaded successfully") 


    if selected_subtitles:
        print("Downloading subtitle file...")
        for subtitle in selected_subtitles:
            subtitle_path = get_temp_path(Title, subtitle_stem(Title, subtitle, subtitle['format']), create_parent=True)
            download_file(subtitle['url'], subtitle_path)
        for subtitle in selected_subtitles:
            if subtitle_needs_srt(subtitle['format'], keep_ass, config_value('output_format')):
                source_path = get_temp_path(Title, subtitle_stem(Title, subtitle, subtitle['format']))
                converted_path = get_temp_path(Title, subtitle_stem(Title, subtitle, 'srt'), create_parent=True)
                if subtitle['format'].lower() == 'ass':
                    convert_ass_to_srt_custom(source_path, converted_path)
                else:
                    convert_vtt_to_srt_custom(source_path, converted_path)
                os.remove(source_path)
                subtitle['format'] = "srt"


    print("Decrypting video file...")
    enc_video_path = get_encrypted_media_path(f"enc_{Title}", "mp4")
    decrypt_file(enc_video_path, dec_video_path, key)

    print("Decrypting audio file...")
    for audio in selected_audios:
        audio_locale = audio["audio_locale"]
        input_path = get_encrypted_media_path(f"enc_{Title}_{audio_locale}", "m4a")
        output_path = get_temp_path(Title, f"{Title}_{audio_locale}.m4a", create_parent=True)
        decrypt_file(input_path, output_path, audio['key'])
        print(f"Audio {audio_locale} decrypted successfully")
    print("All files decrypted successfully")
    print("Deleting Encoded files...")
    shutil.rmtree(get_temp_path(f"enc_{Title}"), ignore_errors=True)
    for audio in selected_audios:
            shutil.rmtree(get_temp_path(f"enc_{Title}_{audio['audio_locale']}"), ignore_errors=True)
    print("temp  files deleted successfully")
    print("Merging video and audio files...")   


    ffmpeg_command = f"{quote_argument(resolve_executable('ffmpeg', config_value('ffmpeg_path')))} -nostdin -y -i {quote_argument(dec_video_path)}"

    for audio in selected_audios:
        audio_file = get_temp_path(Title, f"{Title}_{audio['audio_locale']}.m4a")
        ffmpeg_command += f" -i {quote_argument(audio_file)}"

    if selected_subtitles:
        for subtitle in selected_subtitles:
            subtitle_file = get_temp_path(Title, subtitle_stem(Title, subtitle, subtitle['format']))
            ffmpeg_command += f" -i {quote_argument(subtitle_file)}"


    if encoding_config.use_watermark:
        filter_complex = get_filter_complex()
        ffmpeg_command += f' -filter_complex "{filter_complex}"'
        ffmpeg_command += ' -map "[v]"'
    else:
        ffmpeg_command += " -map 0:v?"  

    for i in range(1, len(selected_audios) + 1):
        ffmpeg_command += f" -map {i}:a?"
    if selected_subtitles:
        for i in range(len(selected_audios) ,len(selected_audios) + len(selected_subtitles)):
            ffmpeg_command += f" -map {i+1}:s?" 

    output_name = f"{Title}.{video['height']}p.["
    for i, audio in enumerate(selected_audios, start=1):
        lang = audio['audio_locale']
        lang_code = config_value("LANGUAGE_NAME_TO_ISO639_2B").get(lang,lang)
        if encoding_config.use_watermark:
           ffmpeg_command += f' -metadata:s:a:{i-1} language={lang_code} -metadata:s:a:{i-1} title="{config_value("Watermark_Name")} - [{lang}]"'
        else:
           ffmpeg_command += f' -metadata:s:a:{i-1} language={lang_code} -metadata:s:a:{i-1} title="[{lang}]"'
        if i == 1:
           output_name += f"{lang}"
        else:
            output_name += f"+{lang}"   

    audio_label = "AAC" if encoding_config.audio_codec.lower() == "copy" else encoding_config.audio_codec.upper()
    if selected_subtitles:
        output_name += f" ({audio_label}) ] [" if encoding_config.use_watermark else f" ["
        for i, subtitle in enumerate(selected_subtitles, start=0):
            lang = subtitle['language']
            lang_code = config_value("LANGUAGE_NAME_TO_ISO639_2B").get(lang,lang)
            if encoding_config.use_watermark:
               ffmpeg_command += f' -metadata:s:s:{i} language={lang_code} -metadata:s:s:{i} title="{config_value("Watermark_Name")} - [{lang}] [{subtitle["type"]}]"'
            else:
                ffmpeg_command += f' -metadata:s:s:{i} language={lang_code} -metadata:s:s:{i} title="[{lang}] [{subtitle["type"]}]"'
            if i == 0:
               output_name += f"{lang} ({subtitle['format']})"
            else:
               output_name += f"+ {lang} ({subtitle['format']})"
    else:
        output_name += f" ({audio_label})]" if encoding_config.use_watermark else f" ]" 

    output_name += f"].{config_value('Watermark_Name')}.{config_value('output_format')}" if encoding_config.use_watermark else f"].{config_value('output_format')}" 
    output_file = get_download_path(output_name, create_parent=True)

    ffmpeg_command += f" {encoding_config.get_ffmpeg_args_str()} {quote_argument(output_file)}"

    run_ffmpeg(ffmpeg_command)
    print("Video and audio files merged successfully")
    print("Deleting temporary files...")
    print("Temporary files deleted successfully")
    shutil.rmtree(temp_title_dir, ignore_errors=True)

else:
    aka = 1
    crunchyroll = Crunchyroll(
        vid_token,
        playback_endpoint=auth.playback_endpoint,
        playback_user_agent=auth.playback_user_agent,
        auth_instance=auth,
        email=config_value("Email") if config_value("use_account") else None,
        password=config_value("Password") if config_value("use_account") else None,
    )
    match = re.search(r'"?https?://www\.crunchyroll\.com/(?:series)/([^/"]+)', video_url)
    if not match:
        print("Invalid URL")
        exit()
    print("Batch mode is enabled.")
    data, series_info = crunchyroll.get_content_info(url=video_url)
    if not data or not data.get("data"):
        print("Series not found")
        exit()
    series_payload = series_info.get("data")
    if isinstance(series_payload, list) and series_payload:
        series_title = series_payload[0].get("title", "Unknown Series")
    elif isinstance(series_payload, dict):
        series_title = series_payload.get("title", "Unknown Series")
    else:
        series_title = "Unknown Series"
    Episode_List = [
        {
            'Episode_no': get_episode_display_number(episode, idx + 1),
            'guid': episode['id'],
            'title': get_episode_title(episode, idx + 1),
            'season_title': get_episode_season_title(episode),
            'raw': episode,
        }
        for idx, episode in enumerate(data['data'])
    ]
    print_series_episode_list(series_title, data.get("seasons") or [], data["data"])
    episode_input = input(
        "Select episodes to download (10 = first 10, 1,2,3,5, 1-10, or all): "
    )
    try:
        selected_episode_indices = parse_episode_selection(episode_input, len(Episode_List))
    except ValueError as error:
        print(f"Invalid episode selection: {error}")
        exit()
    selected_audio_locales = []
    selected_subtitle_tracks = []
    video_quality = 0
    video_height = None
    subtitle_indices = []
    for download_index, episode_index in enumerate(selected_episode_indices, start=1):
        episode_entry = Episode_List[episode_index]
        print(
            f"Downloading {download_index}/{len(selected_episode_indices)}: "
            f"E{episode_entry['Episode_no']} - {episode_entry['title']}"
        )
        id = episode_entry['guid']

        video_info = crunchyroll.get_video_info(id)
        if not video_info:
            reason = crunchyroll.last_playback_error or "premium account access may be required"
            print(f"Episode not accessible with the current token ({reason}). Skipping.")
            continue
        pssh, mpd__content, token = crunchyroll.get_pssh(video_info)
        video_list, audio_list = parse_mpd_content(mpd__content)
        if aka == 1:
            print("Select the video quality:")
            for i, video in enumerate(video_list):
                print(f"{i + 1}. {video['height']}p, bandwidth: {video['bandwidth']}")
            try:
                video_quality = int(input("Enter the video quality: ")) - 1
            except ValueError:
                print("Invalid input. Please enter a number.")
                exit()
            if video_quality < 0 or video_quality >= len(video_list):
                print("Invalid video quality")
                exit()
            video_height = video_list[video_quality]['height']
        chosen_available = 0 <= video_quality < len(video_list)
        video = resolve_video_quality(video_list, video_quality, video_height)
        if video is None:
            print("Failed to resolve video renditions for this episode. Skipping.")
            continue
        if not chosen_available:
            print(f"[WARN] Selected quality is unavailable; using {video['height']}p.")
        if aka == 1:
            print("Select the desired audio track:")
            for index, version in enumerate(video_info['versions']):
                print(f"{index + 1}) {config_value('locale_map').get(version['audio_locale'],version['audio_locale'])}")        

            print("Note: \n1) The audio quality is automatically set to high quality.\n2) To select multiple audios, enter the numbers separated by commas (e.g., 1, 2, 3).")
            audio_list_input = input("Enter the desired audio(s): ")
            try:
                audio_list = [int(audio_choice.strip()) - 1 for audio_choice in audio_list_input.split(',')]
            except ValueError:
                print("Invalid input. Please enter numbers only.")
                exit()
            if any(audio_choice < 0 or audio_choice >= len(video_info['versions']) for audio_choice in audio_list):
                print("Invalid choice(s). Please try again.")
                exit()    

            selected_audio_locales = dedup_preserving_order(
                [video_info['versions'][choice]['audio_locale'] for choice in audio_list]
            )
        selected_audios, missing_locales = resolve_batch_audios(
            selected_audio_locales, video_info['versions'], config_value("locale_map")
        )
        for missing in missing_locales:
            print(f"[WARN] Audio locale {missing} is not available in this episode; skipping it.")
        if not selected_audios:
            print("No requested audio track is available for this episode. Skipping.")
            continue

        license_handler = CrunchyrollLicense()
        try:
            key = extract_content_key(
                license_handler.get_license(pssh, token, id, crunchyroll.token),
                f"episode {download_index}/{len(selected_episode_indices)}",
                video.get("kid"),
            )
        except LicenseError as exc:
            print(f"[WARN] Skipping episode {download_index}/{len(selected_episode_indices)}: {exc}")
            continue

        for audio in selected_audios:
            info = crunchyroll.get_video_info(audio['guid'])
            pssh, mpd_content, token = crunchyroll.get_pssh(info)
            video_list, audio_list = parse_mpd_content(mpd_content)
            highest_audio = max(audio_list, key=lambda x: x['bandwidth'], default=None)
            try:
                audio['key'] = extract_content_key(
                    license_handler.get_license(pssh, token, audio['guid'], crunchyroll.token),
                    audio.get('audio_locale', audio['guid']),
                    (highest_audio or {}).get('kid'),
                )
            except LicenseError as exc:
                print(f"[WARN] Skipping audio track: {exc}")
                continue
            if highest_audio:
                audseg = get_segment_link_list(mpd_content, highest_audio['name'], highest_audio['base_url'], document_url=crunchyroll.mpd_document_url)
                if not audseg or 'all' not in audseg:
                    print(f"[WARN] No audio segments for {audio.get('audio_locale')}; skipping.")
                    continue
                audio['segment'] = audseg
            else:
                print("No audio found")
                continue

        # Batch keeps only resolved tracks; an unresolved entry would raise
        # KeyError further down when the download step reads ['segment'].
        selected_audios = [a for a in selected_audios if a.get('key') and a.get('segment')]

        if ('captions' in video_info and video_info['captions']) or ('subtitles' in video_info and video_info['subtitles']):
            available_tracks = []
            track_info_list = []        
    

            if 'captions' in video_info and video_info['captions']:
                for lang, data in video_info['captions'].items():
                    label = f"[CAPTION] {config_value('locale_map').get(lang, lang)}"
                    available_tracks.append(label)
                    track_info_list.append({
                        'type': 'caption',
                        'language': lang,
                        'url': data['url'],
                        'format': data['format']
                    })      
    

            if 'subtitles' in video_info and video_info['subtitles']:
                for lang, data in video_info['subtitles'].items():
                    if lang == "none" or 'url' not in data:
                        continue
                    label = f"[SUBTITLE] {config_value('locale_map').get(lang, lang)}"
                    available_tracks.append(label)
                    track_info_list.append({
                        'type': 'subtitle',
                        'language': lang,
                        'url': data['url'],
                        'format': data['format']
                    })      
    
            # Prompt after collecting BOTH kinds. It used to sit inside the
            # subtitles branch, so an episode offering captions but no
            # subtitles never asked and silently downloaded nothing.
            if aka == 1 and available_tracks:
                print("Available subtitle/caption tracks:")
                for i, label in enumerate(available_tracks, start=1):
                    print(f"{i}. {label}")

                subtitle_list_input = input("Enter the desired track number(s) (comma-separated for multiple): ")

                try:
                    subtitle_indices = [int(c.strip()) - 1 for c in subtitle_list_input.split(',')]
                    if any(i < 0 or i >= len(track_info_list) for i in subtitle_indices):
                        print("Invalid choice(s). Please try again.")
                        exit()
                except ValueError:
                    print("Invalid input. Please enter numbers only.")
                    exit()

                # Track lists differ between episodes, so remember the chosen
                # identity rather than raw indices and re-resolve per episode.
                # Matching on (type, language) keeps an en-US subtitle from
                # replaying as an en-US caption.
                selected_subtitle_tracks = dedup_preserving_order(
                    [track_key(track_info_list[i]) for i in subtitle_indices]
                )
                # Preferences are captured now, not at end of episode: an early
                # skip used to leave aka at 1 and re-prompt for the next episode.
                aka = 0

            if available_tracks:
                selected_subtitles = resolve_batch_subtitles(
                    selected_subtitle_tracks, track_info_list, config_value("locale_map")
                ) or False
    
    

        vidseg = get_segment_link_list(mpd__content, video['name'], video['base_url'], document_url=crunchyroll.mpd_document_url)
        if not vidseg or "all" not in vidseg:
            print("Failed to resolve video segments for this episode.")
            exit()
        anime = re.sub(r"\s*\([^)]*\)", "", crunchyroll.get_single_info(id)["data"][0]["episode_metadata"]["season_title"])
        Title = anime + "." + "S" + str(crunchyroll.get_single_info(id)["data"][0]["episode_metadata"]["season_number"]).zfill(2) + "E" +  str(crunchyroll.get_single_info(id)["data"][0]["episode_metadata"]["episode_number"]).zfill(2) + "-" + crunchyroll.get_single_info(id)["data"][0]["title"]
        if config_value("use_custom_title"):
            Title = config_value("Custom_Title").format(Title=anime, Episode=crunchyroll.get_single_info(id)["data"][0]["episode_metadata"]["episode_number"], Season=crunchyroll.get_single_info(id)["data"][0]["episode_metadata"]["season_number"],EpTitle=crunchyroll.get_single_info(id)["data"][0]["title"])
        Title = re.sub(r'[<>:\"\'/\\|?*]', '', Title)       

        print("Downloading video file...")      

        segment_headers = {"User-Agent": crunchyroll.playback_user_agent}
        temp_title_dir = get_temp_path(Title, create_parent=True)
        dec_video_path = get_temp_path(Title, f"{Title}.mp4", create_parent=True)
        download_segment(vidseg["all"],"enc_"+Title,"mp4", headers=segment_headers)      

        print("Video downloaded successfully")      

        print("Downloading audio file...")      

        for audio in selected_audios:
            download_segment(audio['segment']["all"], f"enc_{Title}_{audio['audio_locale']}", "m4a", headers=segment_headers)
            print(f"Audio {audio['audio_locale']} downloaded successfully")     
    

        if selected_subtitles:
            print("Downloading subtitle file...")
            for subtitle in selected_subtitles:
                subtitle_path = get_temp_path(Title, subtitle_stem(Title, subtitle, subtitle['format']), create_parent=True)
                download_file(subtitle['url'], subtitle_path)
            for subtitle in selected_subtitles:
                if subtitle_needs_srt(subtitle['format'], keep_ass, config_value('output_format')):
                    source_path = get_temp_path(Title, subtitle_stem(Title, subtitle, subtitle['format']))
                    converted_path = get_temp_path(Title, subtitle_stem(Title, subtitle, 'srt'), create_parent=True)
                    if subtitle['format'].lower() == 'ass':
                        convert_ass_to_srt_custom(source_path, converted_path)
                    else:
                        convert_vtt_to_srt_custom(source_path, converted_path)
                    os.remove(source_path)
                    subtitle['format'] = "srt"    
    
    
    

        print("Decrypting video file...")
        enc_video_path = get_encrypted_media_path(f"enc_{Title}", "mp4")
        decrypt_file(enc_video_path, dec_video_path, key)

        print("Decrypting audio file...")
        for audio in selected_audios:
            audio_locale = audio["audio_locale"]
            input_path = get_encrypted_media_path(f"enc_{Title}_{audio_locale}", "m4a")
            output_path = get_temp_path(Title, f"{Title}_{audio_locale}.m4a", create_parent=True)
            decrypt_file(input_path, output_path, audio['key'])
            print(f"Audio {audio_locale} decrypted successfully")
        print("All files decrypted successfully")
        print("Deleting Encoded files...")
        shutil.rmtree(get_temp_path(f"enc_{Title}"), ignore_errors=True)
        for audio in selected_audios:
                shutil.rmtree(get_temp_path(f"enc_{Title}_{audio['audio_locale']}"), ignore_errors=True)
        print("temp  files deleted successfully")
        print("Merging video and audio files...")       


        ffmpeg_command = f"{quote_argument(resolve_executable('ffmpeg', config_value('ffmpeg_path')))} -nostdin -y -i {quote_argument(dec_video_path)}"

        for audio in selected_audios:
            audio_file = get_temp_path(Title, f"{Title}_{audio['audio_locale']}.m4a")
            ffmpeg_command += f" -i {quote_argument(audio_file)}"

        if selected_subtitles:
            for subtitle in selected_subtitles:
                subtitle_file = get_temp_path(Title, subtitle_stem(Title, subtitle, subtitle['format']))
                ffmpeg_command += f" -i {quote_argument(subtitle_file)}"
    
    

        if encoding_config.use_watermark:
            filter_complex = get_filter_complex()
            ffmpeg_command += f' -filter_complex "{filter_complex}"'
            ffmpeg_command += ' -map "[v]"'
        else:
            ffmpeg_command += " -map 0:v?"      

        for i in range(1, len(selected_audios) + 1):
            ffmpeg_command += f" -map {i}:a?"
        if selected_subtitles:
            for i in range(len(selected_audios) ,len(selected_audios) + len(selected_subtitles)):
                ffmpeg_command += f" -map {i+1}:s?"  
        anime = re.sub(r'[<>:\"\'/\\|?*]', '', anime)    
        output_name = f"{Title}.{video['height']}p.["
        for i, audio in enumerate(selected_audios, start=1):
            lang = audio['audio_locale']
            lang_code = config_value("LANGUAGE_NAME_TO_ISO639_2B").get(lang, lang) if lang else "und" 
            if encoding_config.use_watermark:
               ffmpeg_command += f' -metadata:s:a:{i-1} language={lang_code} -metadata:s:a:{i-1} title="{config_value("Watermark_Name")} - [{lang}]"'
            else:
               ffmpeg_command += f' -metadata:s:a:{i-1} language={lang_code} -metadata:s:a:{i-1} title="[{lang}]"'
            if i == 1:
               output_name += f"{lang}"
            else:
                output_name += f"+{lang}"       

        audio_label = "AAC" if encoding_config.audio_codec.lower() == "copy" else encoding_config.audio_codec.upper()
        if selected_subtitles:
            output_name += f" ({audio_label}) ] [" if encoding_config.use_watermark else f" ["
            for i, subtitle in enumerate(selected_subtitles, start=0):
                lang = subtitle['language']
                lang_code = config_value("LANGUAGE_NAME_TO_ISO639_2B").get(lang, lang) if lang else "und"      
                if encoding_config.use_watermark:
                   ffmpeg_command += f' -metadata:s:s:{i} language={lang_code} -metadata:s:s:{i} title="{config_value("Watermark_Name")} - [{lang}] [{subtitle["type"]}]"'
                else:
                    ffmpeg_command += f' -metadata:s:s:{i} language={lang_code} -metadata:s:s:{i} title="[{lang}] [{subtitle["type"]}]"'
                if i == 0:
                   output_name += f"{lang} ({subtitle['format']})"
                else:
                   output_name += f"+ {lang} ({subtitle['format']})"
        else:
            output_name += f" ({audio_label})]" if encoding_config.use_watermark else f" ]"     

        output_name += f"].{config_value('Watermark_Name')}.{config_value('output_format')}" if encoding_config.use_watermark else f"].{config_value('output_format')}"     
        output_file = get_download_path(anime, output_name, create_parent=True)

        ffmpeg_command += f" {encoding_config.get_ffmpeg_args_str()} {quote_argument(output_file)}"

        run_ffmpeg(ffmpeg_command)
        print("Video and audio files merged successfully")
        print("Deleting temporary files...")
        print("Temporary files deleted successfully")
        shutil.rmtree(temp_title_dir, ignore_errors=True)
        if aka == 1:
           aka = 0

                
