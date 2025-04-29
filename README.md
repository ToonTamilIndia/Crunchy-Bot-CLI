```markdown
# Crunchy-Bot/CLI

**Crunchy-Bot/CLI** is a comprehensive tool to download Crunchyroll videos either through a **command-line interface (CLI)** or an interactive **Telegram bot**. It supports decryption, merging, metadata tagging, multiple audio/subtitle selection, batch downloads, and optional watermarking.

---

## Features

- Download Crunchyroll episodes or full series
- CLI and Telegram bot interface
- DRM decryption using Widevine L3 and `mp4decrypt`
- Video quality selection (360p–1080p or original)
- Multiple audio track selection
- Subtitle and caption download (VTT to SRT conversion)
- Merges video/audio/subtitles using FFmpeg
- Custom file naming, output format, and optional watermark
- Upload final merged file directly to Telegram
- Role-based access and quality limits (Regular, Premium, Sudo)

---

## Prerequisites

1. **`l3.wvd` File**
   - Widevine CDM is required to decrypt protected content.
   - Not included in the repo — you must provide your own.
   - Place in project root (alongside `cli.py`, `tg.py`).

2. **`mp4decrypt` Binary**
   - Used to decrypt video/audio segments.
   - Place in root folder or ensure it’s in `PATH`.
   - Linux/macOS:
     ```bash
     chmod +x mp4decrypt
     ```

---

## Installation

```bash
git clone https://github.com/ToonTamilIndia/Crunchy-Bot-CLI.git
cd Crunchy-Bot-CLI
```

### (Optional) Create Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate
```

### Install Dependencies

```bash
pip install -r requirements.txt
```

---

## Configuration

Edit `config.py` to set:
- Crunchyroll credentials (optional): `Email`, `Password`
- Telegram Bot credentials: `BOT_TOKEN`, `API_ID`, `API_HASH`
- Watermark settings, file naming, debug options, etc.
- Access control: `sudo_users`, `premium_users`, etc.

---

## CLI Usage Guide

### Run CLI
```bash
source venv/bin/activate
python3 cli.py
```

### Workflow

#### **1. Enter Crunchyroll URL**
- Example:
  - Single Episode: `https://www.crunchyroll.com/watch/GXXXXXX`
  - Series: `https://www.crunchyroll.com/series/GXXXXXX`

#### **2. Select Options**
- **Video Quality:** Choose from available resolutions (360p, 480p, 720p, 1080p)
- **Audio Tracks:** Select one or multiple languages
- **Subtitles/Captions:** Choose from available subtitle tracks

#### **3. Download Process**
- Downloads video and audio segments
- Downloads and converts subtitles (VTT to SRT if needed)
- Decrypts content with `mp4decrypt`
- Merges all streams using FFmpeg
- Applies watermark (optional)
- Saves a final `.mp4` file in the current directory or organized folders

---

## Telegram Bot Usage Guide

### Run Bot
```bash
source venv/bin/activate
python3 tg.py
```

### How It Works

#### **1. Start the Bot**
- On Telegram, send `/start` to get a welcome message.

#### **2. Send a Crunchyroll Link**
```bash
/download https://www.crunchyroll.com/watch/GXXXXXX
```

#### **3. Interactive Workflow**
The bot will:
- Prompt you to select:
  - Video quality
  - Audio tracks (via buttons)
  - Subtitle/caption languages
- Summarize your choices
- Begin download, decryption, merging
- Upload final video directly to your Telegram chat

### User Roles
- **Regular Users**: Max 2 audio tracks, up to 480p
- **Premium Users**: No limits
- **Sudo Users**: Admins with full access and commands

### Bot Commands

| Command | Description |
|---------|-------------|
| `/start` | Show welcome message |
| `/help` | Show command list |
| `/download <url>` | Start download process |
| `/cancel` | Cancel current session |

### Admin (Sudo) Commands

| Command | Description |
|---------|-------------|
| `/addpremium <user_id>` | Add premium access |
| `/rempremium <user_id>` | Remove premium access |
| `/listpremium` | Show premium users |
| `/addsudo <user_id>` | Add another sudo user |
| `/remsudo <user_id>` | Remove sudo access |
| `/listsudo` | Show all sudo users |

---

## Deployment Options

### Docker

```bash
docker build -t crunchy-bot-cli .
docker run -it crunchy-bot-cli       # For CLI
docker run -d --name crunchy-tg-bot  # For Telegram bot
```

Edit Dockerfile if needed:
```Dockerfile
CMD ["python3", "cli.py"]  # or tg.py
```

---

### VPS Hosting (Systemd)

```bash
tmux new -s crunchybot
source venv/bin/activate
python3 tg.py
```

Or create a systemd service at `/etc/systemd/system/crunchybot.service`:

```ini
[Unit]
Description=Crunchyroll Telegram Bot
After=network.target

[Service]
User=your_user
WorkingDirectory=/path/to/Crunchy-Bot-CLI
ExecStart=/path/to/venv/bin/python3 /path/to/tg.py
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable crunchybot
sudo systemctl start crunchybot
```

---

## Credits

This project is inspired by and adapts components from:
- [Yoimi by NyaShinn1204](https://github.com/NyaShinn1204/Yoimi)

---

## Disclaimer

This project is intended for **educational purposes only**.  
You are responsible for following copyright laws and platform terms.
```
© ToonTamilIndia & ToonEncodesIndia 2025 - 26
