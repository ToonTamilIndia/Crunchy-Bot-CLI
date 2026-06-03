
import re
import os
import shlex
import sys
from crunchyroll import (
    Crunchyroll, CrunchyrollAuth, CrunchyrollLicense,
    parse_mpd_content, get_segment_link_list, download_segment,
    get_filter_complex, convert_vtt_to_srt_custom,
    get_episode_display_number, get_episode_season_title,
    get_episode_title, parse_episode_selection, set_cr_debug,
)
from config import *


HELP_TEXT = """Usage: python cli.py [--debug]

Interactive Crunchyroll downloader.

Options:
  --debug    Show safe auth/playback endpoint status details.

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

CLI_DEBUG = any(arg == "--debug" for arg in sys.argv[1:]) or bool(debug)
set_cr_debug(CLI_DEBUG)

print("Hello Welcome to Crunchyroll Downloader")


hard_subtitle = None


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
   logging.basicConfig(level=level)
auth = CrunchyrollAuth()
if use_account and Email and Password:
    vid_token = auth.get_user_token(Email, Password, allow_guest_fallback=False)
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
    video_quality = int(input("Enter the video quality: ")) - 1
    if video_quality < 0 or video_quality >= len(video_list):
        print("Invalid video quality")
        exit()
    video = video_list[video_quality]
    print("Select the desired audio track:")
    for index, version in enumerate(video_info['versions']):
        print(f"{index + 1}) {locale_map.get(version['audio_locale'],version['audio_locale'])}")    

    print("Note: \n1) The audio quality is automatically set to high quality.\n2) To select multiple audios, enter the numbers separated by commas (e.g., 1, 2, 3).")
    audio_list_input = input("Enter the desired audio(s): ")
    audio_list = [int(choice.strip()) - 1 for choice in audio_list_input.split(',')]
    if any(choice < 0 or choice >= len(video_info['versions']) for choice in audio_list):
        print("Invalid choice(s). Please try again.")
        exit()

    selected_audios = [
                {'audio_locale': locale_map.get(video_info['versions'][choice]['audio_locale'], video_info['versions'][choice]['audio_locale']), 'guid': video_info['versions'][choice]['guid']}
                for choice in audio_list
            ]
    license_key = CrunchyrollLicense().get_license(pssh, token, id, vid_token) ["key"]
    for i in license_key:
          key = "{}:{}".format(i["kid_hex"], i["key_hex"])  

    for audio in selected_audios:
        info = crunchyroll.get_video_info(audio['guid'])
        pssh, mpd_content, token = crunchyroll.get_pssh(info)
        license_key = CrunchyrollLicense().get_license(pssh, token, audio['guid'], vid_token) ["key"]
        for i in license_key:
            audio['key'] = "{}:{}".format(i["kid_hex"], i["key_hex"])
        video_list, audio_list = parse_mpd_content(mpd_content)
        highest_audio = max(audio_list, key=lambda x: x['bandwidth'], default=None)
        if highest_audio:
            audseg = get_segment_link_list(mpd_content, highest_audio['name'], highest_audio['base_url'])
            audio['segment'] = audseg
        else:
            print("No audio found")
            exit()  



    if ('captions' in video_info and video_info['captions']) or ('subtitles' in video_info and video_info['subtitles']):
        available_tracks = []
        track_info_list = []    


        if 'captions' in video_info and video_info['captions']:
            for lang, data in video_info['captions'].items():
                label = f"[CAPTION] {locale_map.get(lang, lang)}"
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
                label = f"[SUBTITLE] {locale_map.get(lang, lang)}"
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
                lang_display = locale_map.get(entry['language'], entry['language']) 
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



    vidseg = get_segment_link_list(mpd__content, video['name'], video['base_url'])
    anime = re.sub(r"\s*\([^)]*\)", "", crunchyroll.get_single_info(id)["data"][0]["episode_metadata"]["season_title"])
    Title = anime + "." + "S" + str(crunchyroll.get_single_info(id)["data"][0]["episode_metadata"]["season_number"]).zfill(2) + "E" +  str(crunchyroll.get_single_info(id)["data"][0]["episode_metadata"]["episode_number"]).zfill(2) + "-" + crunchyroll.get_single_info(id)["data"][0]["title"]
    if use_custom_title:
        Title = custom_title.format(Title=anime, Episode=crunchyroll.get_single_info(id)["data"][0]["episode_metadata"]["episode_number"], Season=crunchyroll.get_single_info(id)["data"][0]["episode_metadata"]["season_number"],EpTitle=crunchyroll.get_single_info(id)["data"][0]["title"])
    Title = re.sub(r'[<>:\"\'/\\|?*]', '', Title)   

    print("Downloading video file...")  

    segment_headers = {"User-Agent": crunchyroll.playback_user_agent}
    download_segment(vidseg["all"],"enc_"+Title,"mp4", headers=segment_headers)  

    print("Video downloaded successfully")  

    print("Downloading audio file...")  

    for audio in selected_audios:
        download_segment(audio['segment']["all"], f"enc_{Title}_{audio['audio_locale']}", "m4a", headers=segment_headers)
        print(f"Audio {audio['audio_locale']} downloaded successfully") 


    if selected_subtitles:
        print("Downloading subtitle file...")
        for subtitle in selected_subtitles:
            os.system(f"curl {shlex.quote(subtitle['url'])} -o {shlex.quote(f'{Title}_{subtitle['language']}.{subtitle['format']}')}")
        for subtitle in selected_subtitles:
            if subtitle['format'] == 'vtt':
                convert_vtt_to_srt_custom(f"{Title}_{subtitle['language']}.{subtitle['format']}",f"{Title}_{subtitle['language']}.srt")
                os.system(f"rm {shlex.quote(f'{Title}_{subtitle['language']}.{subtitle['format']}')}")  
                subtitle['format'] = "srt"




    print("Decrypting video file...")
    os.system(f"./mp4decrypt {shlex.quote(f'Downloads/enc_{Title}.mp4')} {shlex.quote(f'{Title}.mp4')} --show-progress --key {key}")    

    print("Decrypting audio file...")
    for audio in selected_audios:
        audio_locale = audio["audio_locale"]
        input_path = f"Downloads/enc_{Title}_{audio_locale}.m4a"
        output_path = f"{Title}_{audio_locale}.m4a"
        os.system(f"./mp4decrypt {shlex.quote(input_path)} {shlex.quote(output_path)} --show-progress --key {audio['key']}")
        print(f"Audio {audio_locale} decrypted successfully")
    print("All files decrypted successfully")
    print("Deleting Encoded files...")
    os.system(f"rm -rf {shlex.quote(f'Downloads/enc_{Title}.mp4')}")
    for audio in selected_audios:
            input_path = f"Downloads/enc_{Title}_{audio_locale}.m4a"
            os.system(f"rm -rf {input_path}")
    print("temp  files deleted successfully")
    print("Merging video and audio files...")   


    ffmpeg_command = f"{ffmpeg_path} -nostdin -y -i {shlex.quote(Title+'.mp4')}"    

    for audio in selected_audios:
        audio_file = f"{Title}_{audio['audio_locale']}.m4a"
        ffmpeg_command += f" -i {shlex.quote(audio_file)}"  

    if selected_subtitles:
        for subtitle in selected_subtitles:
            subtitle_file = f"{Title}_{subtitle['language']}.{subtitle['format']}"
            ffmpeg_command += f" -i {shlex.quote(subtitle_file)}"   


    filter_complex = get_filter_complex()
    if use_watermark:
        ffmpeg_command += f' -filter_complex "{filter_complex}"'
        ffmpeg_command += ' -map "[v]"'
    else:
        ffmpeg_command += " -map 0:v?"  

    for i in range(1, len(selected_audios) + 1):
        ffmpeg_command += f" -map {i}:a?"
    if selected_subtitles:
        for i in range(len(selected_audios) ,len(selected_audios) + len(selected_subtitles)):
            ffmpeg_command += f" -map {i+1}:s?" 

    output_file = f"{Title}.{video['height']}p.["
    for i, audio in enumerate(selected_audios, start=1):
        lang = audio['audio_locale']
        lang_code = LANGUAGE_NAME_TO_ISO639_2B.get(lang,lang)
        if use_watermark:
           ffmpeg_command += f' -metadata:s:a:{i-1} language={lang_code} -metadata:s:a:{i-1} title="{Watermark_Name} - [{lang}]"'
        else:
           ffmpeg_command += f' -metadata:s:a:{i-1} language={lang_code} -metadata:s:a:{i-1} title="[{lang}]"'
        if i == 1:
           output_file += f"{lang}"
        else:
            output_file += f"+{lang}"   

    if selected_subtitles:
        output_file += f" ({audio_codec}) ] [" if use_watermark else f" ["
        for i, subtitle in enumerate(selected_subtitles, start=0):
            lang = subtitle['language']
            lang_code = LANGUAGE_NAME_TO_ISO639_2B.get(lang,lang)
            if use_watermark:
               ffmpeg_command += f' -metadata:s:s:{i} language={lang_code} -metadata:s:s:{i} title="{Watermark_Name} - [{lang}] [{subtitle["type"]}]"'
            else:
                ffmpeg_command += f' -metadata:s:s:{i} language={lang_code} -metadata:s:s:{i} title="[{lang}] [{subtitle["type"]}]"'
            if i == 0:
               output_file += f"{lang} ({subtitle['format']})"
            else:
               output_file += f"+ {lang} ({subtitle['format']})"
    else:
        output_file += f" ({audio_codec})]" if use_watermark else f" ]" 

    output_file += f"].{Watermark_Name}.{output_format}" if use_watermark else f"].{output_format}" 

    ffmpeg_command += f" -c:v {encoding_code} -c:a {audio_codec} -c:s copy {shlex.quote(output_file)}"  

    print("ffmpeg command:", ffmpeg_command)
    os.system(ffmpeg_command)
    print("Video and audio files merged successfully")
    print("Deleting temporary files...")
    print("Temporary files deleted successfully")
    os.system(f"rm -rf '{Title}.mp4'")
    for audio in selected_audios:
        audio_file = f"{Title}_{audio['audio_locale']}.m4a"
        os.system(f"rm -rf '{audio_file}'")
        os.system(f"rm -rf 'enc_{audio_file}'")
    if selected_subtitles:
        for subtitle in selected_subtitles:
            subtitle_file = f"{Title}_{subtitle['language']}.{subtitle['format']}"
            os.system(f"rm -rf '{subtitle_file}'")  

else:
    aka = 1
    crunchyroll = Crunchyroll(
        vid_token,
        playback_endpoint=auth.playback_endpoint,
        playback_user_agent=auth.playback_user_agent,
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
    video_quality = 0
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
            video_quality = int(input("Enter the video quality: ")) - 1
            if video_quality < 0 or video_quality >= len(video_list):
                print("Invalid video quality")
                exit()
        video = video_list[video_quality]
        if aka == 1:
            print("Select the desired audio track:")
            for index, version in enumerate(video_info['versions']):
                print(f"{index + 1}) {locale_map.get(version['audio_locale'],version['audio_locale'])}")        

            print("Note: \n1) The audio quality is automatically set to high quality.\n2) To select multiple audios, enter the numbers separated by commas (e.g., 1, 2, 3).")
            audio_list_input = input("Enter the desired audio(s): ")
            audio_list = [int(audio_choice.strip()) - 1 for audio_choice in audio_list_input.split(',')]
            if any(audio_choice < 0 or audio_choice >= len(video_info['versions']) for audio_choice in audio_list):
                print("Invalid choice(s). Please try again.")
                exit()    

            selected_audio_locales = [video_info['versions'][audio_choice]['audio_locale'] for audio_choice in audio_list]
        selected_audios = []
        for locale in selected_audio_locales:
            matching_versions = [v for v in video_info['versions'] if v['audio_locale'] == locale]
            if not matching_versions:
                print(f"Audio locale {locale} not available in this episode.")
                exit()
            version = matching_versions[0]
            selected_audios.append({
                'audio_locale': locale_map.get(locale, locale),
                'guid': version['guid']
            })

        license_key = CrunchyrollLicense().get_license(pssh, token, id, vid_token) ["key"]
        for i in license_key:
              key = "{}:{}".format(i["kid_hex"], i["key_hex"])      

        for audio in selected_audios:
            info = crunchyroll.get_video_info(audio['guid'])
            pssh, mpd_content, token = crunchyroll.get_pssh(info)
            license_key = CrunchyrollLicense().get_license(pssh, token, audio['guid'], vid_token) ["key"]
            for i in license_key:
                audio['key'] = "{}:{}".format(i["kid_hex"], i["key_hex"])
            video_list, audio_list = parse_mpd_content(mpd_content)
            highest_audio = max(audio_list, key=lambda x: x['bandwidth'], default=None)
            if highest_audio:
                audseg = get_segment_link_list(mpd_content, highest_audio['name'], highest_audio['base_url'])
                audio['segment'] = audseg
            else:
                print("No audio found")
                exit()      
    
    

        if ('captions' in video_info and video_info['captions']) or ('subtitles' in video_info and video_info['subtitles']):
            available_tracks = []
            track_info_list = []        
    

            if 'captions' in video_info and video_info['captions']:
                for lang, data in video_info['captions'].items():
                    label = f"[CAPTION] {locale_map.get(lang, lang)}"
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
                    label = f"[SUBTITLE] {locale_map.get(lang, lang)}"
                    available_tracks.append(label)
                    track_info_list.append({
                        'type': 'subtitle',
                        'language': lang,
                        'url': data['url'],
                        'format': data['format']
                    })      
    
                if aka == 1:
                   print("Available subtitle/caption tracks:")
                   for i, label in enumerate(available_tracks, start=1):
                       print(f"{i}. {label}")      

                   subtitle_list_input = input("Enter the desired track number(s) (comma-separated for multiple): ")       

                   try:
                       subtitle_indices = [int(subtitle_choice.strip()) - 1 for subtitle_choice in subtitle_list_input.split(',')]
                       if any(i < 0 or i >= len(track_info_list) for i in subtitle_indices):
                           print("Invalid choice(s). Please try again.")
                           exit() 
                   except ValueError:
                          print("Invalid input. Please enter numbers only.")
                          exit()       

                selected_subtitles = []
                for i in subtitle_indices:
                    entry = track_info_list[i]
                    lang_display = locale_map.get(entry['language'], entry['language']) 
                    selected_subtitles.append({
                        'language': lang_display,
                        'url': entry['url'],
                        'format': entry['format'],
                        'type': entry['type']
                    })      
    

                

        else:
            print("No subtitles available for this video.")         
            selected_subtitles = False      
    
    

        vidseg = get_segment_link_list(mpd__content, video['name'], video['base_url'])
        anime = re.sub(r"\s*\([^)]*\)", "", crunchyroll.get_single_info(id)["data"][0]["episode_metadata"]["season_title"])
        Title = anime + "." + "S" + str(crunchyroll.get_single_info(id)["data"][0]["episode_metadata"]["season_number"]).zfill(2) + "E" +  str(crunchyroll.get_single_info(id)["data"][0]["episode_metadata"]["episode_number"]).zfill(2) + "-" + crunchyroll.get_single_info(id)["data"][0]["title"]
        if use_custom_title:
            Title = custom_title.format(Title=anime, Episode=crunchyroll.get_single_info(id)["data"][0]["episode_metadata"]["episode_number"], Season=crunchyroll.get_single_info(id)["data"][0]["episode_metadata"]["season_number"],EpTitle=crunchyroll.get_single_info(id)["data"][0]["title"])
        Title = re.sub(r'[<>:\"\'/\\|?*]', '', Title)       

        print("Downloading video file...")      

        segment_headers = {"User-Agent": crunchyroll.playback_user_agent}
        download_segment(vidseg["all"],"enc_"+Title,"mp4", headers=segment_headers)      

        print("Video downloaded successfully")      

        print("Downloading audio file...")      

        for audio in selected_audios:
            download_segment(audio['segment']["all"], f"enc_{Title}_{audio['audio_locale']}", "m4a", headers=segment_headers)
            print(f"Audio {audio['audio_locale']} downloaded successfully")     
    

        if selected_subtitles:
            print("Downloading subtitle file...")
            for subtitle in selected_subtitles:
                os.system(f"curl {shlex.quote(subtitle['url'])} -o {shlex.quote(f'{Title}_{subtitle['language']}.{subtitle['format']}')}")
            for subtitle in selected_subtitles:
                if subtitle['format'] == 'vtt':
                    convert_vtt_to_srt_custom(f"{Title}_{subtitle['language']}.{subtitle['format']}",f"{Title}_{subtitle['language']}.srt")
                    os.system(f"rm {shlex.quote(f'{Title}_{subtitle['language']}.{subtitle['format']}')}")  
                    subtitle['format'] = "srt"    
    
    
    

        print("Decrypting video file...")
        os.system(f"./mp4decrypt {shlex.quote(f'Downloads/enc_{Title}.mp4')} {shlex.quote(f'{Title}.mp4')} --show-progress --key {key}")        

        print("Decrypting audio file...")
        for audio in selected_audios:
            audio_locale = audio["audio_locale"]
            input_path = f"Downloads/enc_{Title}_{audio_locale}.m4a"
            output_path = f"{Title}_{audio_locale}.m4a"
            os.system(f"./mp4decrypt {shlex.quote(input_path)} {shlex.quote(output_path)} --show-progress --key {audio['key']}")
            print(f"Audio {audio_locale} decrypted successfully")
        print("All files decrypted successfully")
        print("Deleting Encoded files...")
        os.system(f"rm -rf {shlex.quote(f'Downloads/enc_{Title}.mp4')}")
        for audio in selected_audios:
                input_path = f"Downloads/enc_{Title}_{audio_locale}.m4a"
                os.system(f"rm -rf {input_path}")
        print("temp  files deleted successfully")
        print("Merging video and audio files...")       
    

        ffmpeg_command = f"{ffmpeg_path} -nostdin -y -i {shlex.quote(Title+'.mp4')}"        

        for audio in selected_audios:
            audio_file = f"{Title}_{audio['audio_locale']}.m4a"
            ffmpeg_command += f" -i {shlex.quote(audio_file)}"      

        if selected_subtitles:
            for subtitle in selected_subtitles:
                subtitle_file = f"{Title}_{subtitle['language']}.{subtitle['format']}"
                ffmpeg_command += f" -i {shlex.quote(subtitle_file)}"       
    

        filter_complex = get_filter_complex()
        if use_watermark:
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
        if aka == 1:
             os.makedirs(anime, exist_ok=True)
        output_file = f"{anime}/{Title}.{video['height']}p.["
        for i, audio in enumerate(selected_audios, start=1):
            lang = audio['audio_locale']
            lang_code = LANGUAGE_NAME_TO_ISO639_2B.get(lang, lang) if lang else "und" 
            if use_watermark:
               ffmpeg_command += f' -metadata:s:a:{i-1} language={lang_code} -metadata:s:a:{i-1} title="{Watermark_Name} - [{lang}]"'
            else:
               ffmpeg_command += f' -metadata:s:a:{i-1} language={lang_code} -metadata:s:a:{i-1} title="[{lang}]"'
            if i == 1:
               output_file += f"{lang}"
            else:
                output_file += f"+{lang}"       

        if selected_subtitles:
            output_file += f" ({audio_codec}) ] [" if use_watermark else f" ["
            for i, subtitle in enumerate(selected_subtitles, start=0):
                lang = subtitle['language']
                lang_code = LANGUAGE_NAME_TO_ISO639_2B.get(lang, lang) if lang else "und"      
                if use_watermark:
                   ffmpeg_command += f' -metadata:s:s:{i} language={lang_code} -metadata:s:s:{i} title="{Watermark_Name} - [{lang}] [{subtitle["type"]}]"'
                else:
                    ffmpeg_command += f' -metadata:s:s:{i} language={lang_code} -metadata:s:s:{i} title="[{lang}] [{subtitle["type"]}]"'
                if i == 0:
                   output_file += f"{lang} ({subtitle['format']})"
                else:
                   output_file += f"+ {lang} ({subtitle['format']})"
        else:
            output_file += f" ({audio_codec})]" if use_watermark else f" ]"     

        output_file += f"].{Watermark_Name}.{output_format}" if use_watermark else f"].{output_format}"     

        ffmpeg_command += f" -c:v {encoding_code} -c:a {audio_codec} -c:s copy {shlex.quote(output_file)}"      

        print("ffmpeg command:", ffmpeg_command)
        os.system(ffmpeg_command)
        print("Video and audio files merged successfully")
        print("Deleting temporary files...")
        print("Temporary files deleted successfully")
        os.system(f"rm -rf '{Title}.mp4'")
        for audio in selected_audios:
            audio_file = f"{Title}_{audio['audio_locale']}.m4a"
            os.system(f"rm -rf '{audio_file}'")
        if selected_subtitles:
            for subtitle in selected_subtitles:
                subtitle_file = f"{Title}_{subtitle['language']}.{subtitle['format']}"
                os.system(f"rm -rf '{subtitle_file}'")
        if aka == 1:
           aka = 0

                
