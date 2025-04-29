'''Crunchyroll Account Configurations 
if you want to use an account, set use_account to True and fill in the email and password.
if you want to use a guest account, set use_account to False and leave email and password empty.
'''
use_account = False
Email = "" #Your email here
Password = "" #Your password here

# --- Telegram Settings ---
API_ID = 7534167  # Replace with your API ID
API_HASH = "2" # Replace with your API Hash
BOT_TOKEN = "" # Replace with your Bot Token

# --- User Management & Limits ---
sudo_users = [] # List of sudo user IDs (as integers)
premium_users = [] # List of premium user IDs (as integers)
AUTHORIZED_USERS = [] # List of authorized user IDs to use bot in private (as integers)

# Limits for regular users
REGULAR_USER_AUDIO_LIMIT = 2
REGULAR_USER_VIDEO_LIMIT_P = 480 # Max height in pixels (e.g., 480 for 480p)

# --- Bot State ---
user_states = {} # user_id: {"step": "...", "data": {...}, "message": message_object}
active_downloads = {} # user_id: True/False (To prevent concurrent downloads per user)


#debugging

debug = False
level = ""
max_retries = 3 # Number of retries for failed downloads
retry_delay = 2 # seconds

#proxy settings

use_proxy = False # Set to True to use a proxy
proxy = "" # Proxy URL (e.g., "http://username:password@proxyserver:port")

# watermark settings
Watermark_Name = "ToonTamilIndia" # Your watermark name here
fontfile = "font.ttf" # Font file path
fontcolor = "white" # Font color
opaque = "0.4" # opposite of transparency, 0.0 is fully transparent and 1.0 is fully opaque
fontsize = "h/10"
x_axis = "10" # x-axis position of the watermark
y_axis = "(h-text_h)/2" # y-axis position of the watermark 


#ffmpeg settings
use_watermark = True # Set to True to use watermark
ffmpeg_path = "ffmpeg" # Path to ffmpeg executable
encoding_code = "libx264" # Encoding method note: if watermark is enabled, use "libx264" for encoding
output_format = "mkv" # Output format
audio_codec = "aac" # Audio codec
original_quality = False # Set to True to use original quality (no encoding)




#Custom Title
use_custom_title = False # Set to True to use a custom title
'''
{Season} - season number
{Episode} - episode number
{Title} - Title of the anime
{EpTitle} - Title of the episode
'''
Custom_Title = "{Title} S{Season}E{Episode} - {EpTitle}" # Custom title format

# audio mapping
locale_map = {
    "ja-JP": "Japanese",
    "en-US": "English (US)",
    "de-DE": "German",
    "es-419": "Spanish (Latin America)",
    "es-ES": "Spanish (Spain)",
    "fr-FR": "French",
    "it-IT": "Italian",
    "pt-BR": "Portuguese (Brazil)",
    "hi-IN": "Hindi",
    "ta-IN": "Tamil",
    "te-IN": "Telugu",
    "ru-RU": "Russian",
    "ar-SA": "Arabic (Saudi Arabia)",
    "ko-KR": "Korean",
    "vi-VN": "Vietnamese",
    "th-TH": "Thai",
    "ms-MY": "Malay",
    "id-ID": "Indonesian",
    "en-IN": "English (India)",
    "zh-CN": "Chinese (Simplified)",
    "zh-TW": "Chinese (Traditional)",
    "pl-PL": "Polish",
    "tr-TR": "Turkish",
    "sv-SE": "Swedish",
    "da-DK": "Danish",
    "no-NO": "Norwegian",
    "fi-FI": "Finnish",
    "cs-CZ": "Czech",
    "sk-SK": "Slovak",
    "nl-NL": "Dutch",
    "ro-RO": "Romanian",
    "bg-BG": "Bulgarian",
    "hr-HR": "Croatian",
    "sr-RS": "Serbian",
    "uk-UA": "Ukrainian",
    "el-GR": "Greek",
    "he-IL": "Hebrew",
    "th-TH": "Thai",
    "sw-KE": "Swahili",
    "af-ZA": "Afrikaans",
    "ms-MY": "Malay",
    "bn-BD": "Bengali",
    "mr-IN": "Marathi",
    "gu-IN": "Gujarati",
    "kn-IN": "Kannada",
    "pa-IN": "Punjabi",
    "ml-IN": "Malayalam",
    "or-IN": "Odia",
    "as-IN": "Assamese",
    "ur-IN": "Urdu",
    "ta-LK": "Tamil (Sri Lanka)",
    "te-LK": "Telugu (Sri Lanka)",
    "zh-HK": "Chinese (Hong Kong)"
}


LANGUAGE_NAME_TO_ISO639_2B = {
    "Afar": "aar",
    "Abkhazian": "abk",
    "Afrikaans": "afr",
    "Akan": "aka",
    "Albanian": "sqi",
    "Amharic": "amh",
    "Arabic": "ara",
    "Arabic (Saudi Arabia)": "ara",
    "Aragonese": "arg",
    "Armenian": "hye",
    "Assamese": "asm",
    "Avaric": "ava",
    "Avestan": "ave",
    "Aymara": "aym",
    "Azerbaijani": "aze",
    "Basque": "eus",
    "Belarusian": "bel",
    "Bengali": "ben",
    "Bislama": "bis",
    "Bosnian": "bos",
    "Breton": "bre",
    "Bulgarian": "bul",
    "Burmese": "mya",
    "Catalan": "cat",
    "Central Khmer": "khm",
    "Chamorro": "cha",
    "Chechen": "che",
    "Chinese": "zho",
    "Chinese (Hong Kong)": "zho",
    "Chinese (Taiwan)": "zho",
    "Chinese (Simplified)": "zho",
    "Chinese (Traditional)": "zho",
    "Corsican": "cos",
    "Cree": "cre",
    "Croatian": "hrv",
    "Czech": "ces",
    "Danish": "dan",
    "Dutch": "nld",
    "Dzongkha": "dzo",
    "English": "eng",
    "English (US)": "eng",
    "English (India)": "eng",
    "Esperanto": "epo",
    "Estonian": "est",
    "Ewe": "ewe",
    "Faroese": "fao",
    "Fijian": "fij",
    "Finnish": "fin",
    "French": "fra",
    "French (Canada)": "fra",
    "Fulah": "ful",
    "Galician": "glg",
    "Georgian": "kat",
    "German": "deu",
    "Greek": "ell",
    "Guarani": "grn",
    "Gujarati": "guj",
    "Haitian": "hat",
    "Hausa": "hau",
    "Hebrew": "heb",
    "Hindi": "hin",
    "Hungarian": "hun",
    "Icelandic": "isl",
    "Indonesian": "ind",
    "Interlingua": "ina",
    "Interlingue": "ile",
    "Inuktitut": "iku",
    "Irish": "gle",
    "Italian": "ita",
    "Japanese": "jpn",
    "Javanese": "jav",
    "Kannada": "kan",
    "Kashmiri": "kas",
    "Kazakh": "kaz",
    "Kinyarwanda": "kin",
    "Korean": "kor",
    "Kurdish": "kur",
    "Latin": "lat",
    "Latvian": "lav",
    "Lingala": "lin",
    "Lithuanian": "lit",
    "Luxembourgish": "ltz",
    "Macedonian": "mkd",
    "Malay": "msa",
    "Malayalam": "mal",
    "Maltese": "mlt",
    "Manx": "glv",
    "Maori": "mri",
    "Marathi": "mar",
    "Marshallese": "mah",
    "Modern Greek": "ell",
    "Mongolian": "mon",
    "Nepali": "nep",
    "North Ndebele": "nde",
    "Northern Sami": "sme",
    "Norwegian": "nor",
    "Norwegian Bokmål": "nob",
    "Norwegian Nynorsk": "nno",
    "Oriya": "ori",
    "Pashto": "pus",
    "Persian": "fas",
    "Polish": "pol",
    "Portuguese": "por",
    "Portuguese (Brazil)": "por",
    "Punjabi": "pan",
    "Quechua": "que",
    "Romanian": "ron",
    "Russian": "rus",
    "Sanskrit": "san",
    "Serbian": "srp",
    "Sindhi": "snd",
    "Sinhala": "sin",
    "Slovak": "slk",
    "Slovenian": "slv",
    "Somali": "som",
    "Spanish": "spa",
    "Spanish (Spain)": "spa",
    "Spanish (Latin America)": "spa",
    "Sundanese": "sun",
    "Swahili": "swa",
    "Swedish": "swe",
    "Tamil": "tam",
    "Telugu": "tel",
    "Thai": "tha",
    "Tibetan": "bod",
    "Turkish": "tur",
    "Ukrainian": "ukr",
    "Urdu": "urd",
    "Uzbek": "uzb",
    "Vietnamese": "vie",
    "Welsh": "cym",
    "Western Frisian": "fry",
    "Xhosa": "xho",
    "Yiddish": "yid",
    "Yoruba": "yor",
    "Zulu": "zul"
}