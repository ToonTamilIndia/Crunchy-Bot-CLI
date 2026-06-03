# Crunchy-Bot/CLI

<p align="center">
  <a href="https://github.com/ToonTamilIndia/Crunchy-Bot-CLI">
    <img src="https://readme-typing-svg.demolab.com?font=Fira+Code&weight=700&size=30&duration=3000&pause=1000&color=F97316&center=true&vCenter=true&width=600&height=80&lines=Crunchy-Bot%2FCLI;CLI+%26+Telegram+Media+Workflow;Download+%7C+Merge+%7C+Deliver" alt="Typing SVG" />
  </a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.9%2B-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/FFmpeg-Required-007808?style=for-the-badge&logo=ffmpeg&logoColor=white" alt="FFmpeg" />
  <img src="https://img.shields.io/badge/Telegram-Bot-26A5E4?style=for-the-badge&logo=telegram&logoColor=white" alt="Telegram" />
  <img src="https://img.shields.io/badge/Docker-Supported-2496ED?style=for-the-badge&logo=docker&logoColor=white" alt="Docker" />
  <img src="https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge" alt="License" />
</p>

<p align="center">
  <img src="https://img.shields.io/github/stars/ToonTamilIndia/Crunchy-Bot-CLI?style=flat-square&color=f97316" alt="Stars" />
  <img src="https://img.shields.io/github/forks/ToonTamilIndia/Crunchy-Bot-CLI?style=flat-square&color=3b82f6" alt="Forks" />
  <img src="https://img.shields.io/github/issues/ToonTamilIndia/Crunchy-Bot-CLI?style=flat-square&color=ef4444" alt="Issues" />
  <img src="https://img.shields.io/github/last-commit/ToonTamilIndia/Crunchy-Bot-CLI?style=flat-square&color=22c55e" alt="Last Commit" />
  <img src="https://img.shields.io/github/repo-size/ToonTamilIndia/Crunchy-Bot-CLI?style=flat-square&color=8b5cf6" alt="Repo Size" />
</p>

---

> A command-line and Telegram bot based media downloader workflow for Crunchyroll links.
> Manage episode downloads, quality selection, audio and subtitle selection, file merging, metadata tagging, naming, and optional Telegram delivery — all from one project.

---

## Table of Contents

- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [CLI Usage](#cli-usage)
- [Telegram Bot Usage](#telegram-bot-usage)
- [User Roles](#user-roles)
- [Bot Commands](#bot-commands)
- [Admin Commands](#admin-commands)
- [Docker Deployment](#docker-deployment)
- [VPS Deployment](#vps-deployment)
- [Running with tmux](#running-with-tmux)
- [Running with systemd](#running-with-systemd)
- [Project Structure](#project-structure)
- [Credits](#credits)
- [Disclaimer](#disclaimer)
- [License](#license)

---

## Features

<table>
<tr>
<td><img src="https://img.shields.io/badge/-Episode%20%26%20Series%20Downloads-f97316?style=flat-square" alt="Feature" /></td>
<td>Download single episodes or full series</td>
</tr>
<tr>
<td><img src="https://img.shields.io/badge/-Dual%20Interface-3b82f6?style=flat-square" alt="Feature" /></td>
<td>CLI and Telegram bot interfaces</td>
</tr>
<tr>
<td><img src="https://img.shields.io/badge/-Quality%20Selection-22c55e?style=flat-square" alt="Feature" /></td>
<td>Choose from 360p, 480p, 720p, 1080p, or original</td>
</tr>
<tr>
<td><img src="https://img.shields.io/badge/-Audio%20Track%20Selection-8b5cf6?style=flat-square" alt="Feature" /></td>
<td>Select one or more audio tracks when available</td>
</tr>
<tr>
<td><img src="https://img.shields.io/badge/-Subtitle%20Support-06b6d4?style=flat-square" alt="Feature" /></td>
<td>Download subtitles and convert VTT to SRT</td>
</tr>
<tr>
<td><img src="https://img.shields.io/badge/-File%20Merging-ec4899?style=flat-square" alt="Feature" /></td>
<td>Merge video, audio, and subtitles using FFmpeg</td>
</tr>
<tr>
<td><img src="https://img.shields.io/badge/-Metadata%20Tagging-eab308?style=flat-square" alt="Feature" /></td>
<td>Tag final output files with metadata</td>
</tr>
<tr>
<td><img src="https://img.shields.io/badge/-Custom%20Naming-14b8a6?style=flat-square" alt="Feature" /></td>
<td>Flexible output file naming</td>
</tr>
<tr>
<td><img src="https://img.shields.io/badge/-Optional%20Watermarking-a855f7?style=flat-square" alt="Feature" /></td>
<td>Apply watermarks to output files</td>
</tr>
<tr>
<td><img src="https://img.shields.io/badge/-Telegram%20Delivery-26A5E4?style=flat-square" alt="Feature" /></td>
<td>Upload final files directly to Telegram</td>
</tr>
<tr>
<td><img src="https://img.shields.io/badge/-Role%20Based%20Access-ef4444?style=flat-square" alt="Feature" /></td>
<td>Regular, premium, and sudo user roles</td>
</tr>
<tr>
<td><img src="https://img.shields.io/badge/-Batch%20Downloads-f59e0b?style=flat-square" alt="Feature" /></td>
<td>Download multiple files in sequence</td>
</tr>
</table>

---

## Requirements

### Python

<img src="https://img.shields.io/badge/Python-3.9%2B%20Recommended-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python" />

### FFmpeg

<img src="https://img.shields.io/badge/FFmpeg-Required-007808?style=flat-square&logo=ffmpeg&logoColor=white" alt="FFmpeg" />

FFmpeg is required for merging, subtitle handling, metadata tagging, and optional watermarking.

Verify your FFmpeg installation:

```bash
ffmpeg -version
```

### Optional Decryption Tools

Some streams may require additional tools depending on the content type and your legal access rights.

> **Important:** This project does not include any DRM files, device files, licenses, or protected platform secrets. You are solely responsible for using this project only with content you are legally allowed to access and process.

#### mp4decrypt

If your permitted workflow requires `mp4decrypt`, make sure it is available in the project folder or installed globally in your system path.

On Linux or macOS, set the correct permissions:

```bash
chmod +x mp4decrypt
```

---

## Installation

**Clone the repository:**

```bash
git clone https://github.com/ToonTamilIndia/Crunchy-Bot-CLI.git
cd Crunchy-Bot-CLI
```

**Create and activate a virtual environment:**

```bash
python3 -m venv venv
source venv/bin/activate
```

**Install dependencies:**

```bash
pip install -r requirements.txt
```

---

## Configuration

Edit `config.py` and update all required values before running the project.

```python
# Telegram Bot Credentials
BOT_TOKEN = "your_bot_token"
API_ID    = 123456
API_HASH  = "your_api_hash"

# User Access Control
sudo_users    = []
premium_users = []

# Download Defaults
DEFAULT_QUALITY  = "720p"
ENABLE_WATERMARK = False
DEBUG            = False
```

### Configuration Reference

| Option | Description |
|---|---|
| `BOT_TOKEN` | Your Telegram bot token from BotFather |
| `API_ID` | Telegram API ID from my.telegram.org |
| `API_HASH` | Telegram API hash from my.telegram.org |
| `sudo_users` | List of Telegram user IDs with admin access |
| `premium_users` | List of Telegram user IDs with premium access |
| `DEFAULT_QUALITY` | Default video quality for downloads |
| `ENABLE_WATERMARK` | Enable or disable watermarking on output files |
| `DEBUG` | Enable verbose debug logging |

---

## CLI Usage

<img src="https://img.shields.io/badge/Interface-CLI-f97316?style=flat-square" alt="CLI" />

**Start the CLI:**

```bash
source venv/bin/activate
python3 cli.py
```

### Download Workflow

**Step 1 — Enter a Crunchyroll URL**

Single episode:

```
https://www.crunchyroll.com/watch/GXXXXXX
```

Full series:

```
https://www.crunchyroll.com/series/GXXXXXX
```

**Step 2 — Select video quality**

```
360p
480p
720p
1080p
original
```

**Step 3 — Select audio tracks**

Choose one or more available audio languages depending on the source content.

**Step 4 — Select subtitles**

Available subtitles can be downloaded and automatically converted from VTT to SRT.

**Step 5 — Confirm and download**

The CLI will:

1. Download all selected streams
2. Process and convert subtitles
3. Merge video, audio, and subtitles using FFmpeg
4. Apply optional metadata tags or watermark settings
5. Save the final output as an MKV file

---

## Telegram Bot Usage

<img src="https://img.shields.io/badge/Interface-Telegram%20Bot-26A5E4?style=flat-square&logo=telegram&logoColor=white" alt="Telegram Bot" />

**Start the bot:**

```bash
source venv/bin/activate
python3 tg.py
```

Open Telegram and send:

```
/start
```

**Start a download:**

```
/download https://www.crunchyroll.com/watch/GXXXXXX
```

The bot will guide you through an interactive workflow:

1. Select video quality
2. Select audio tracks
3. Select subtitle languages
4. Review all selected options
5. Start download and processing
6. Receive the final merged file directly in Telegram

---

## User Roles

### Regular Users

<img src="https://img.shields.io/badge/Role-Regular-22c55e?style=flat-square" alt="Regular" />

Basic access with default limits.

| Limit | Value |
|---|---|
| Maximum quality | 480p |
| Maximum audio tracks | 2 |

### Premium Users

<img src="https://img.shields.io/badge/Role-Premium-3b82f6?style=flat-square" alt="Premium" />

Extended access with fewer restrictions.

| Limit | Value |
|---|---|
| Maximum quality | No fixed limit |
| Maximum audio tracks | Multiple allowed |
| Download priority | Higher, if configured |

### Sudo Users

<img src="https://img.shields.io/badge/Role-Sudo%20%2F%20Admin-ef4444?style=flat-square" alt="Sudo" />

Full administrator access.

- Manage premium and sudo user lists
- Access all bot features without restriction
- Override all normal limits

---

## Bot Commands

| Command | Description |
|---|---|
| `/start` | Show the welcome message |
| `/help` | Show all available commands |
| `/download <url>` | Start a new download session |
| `/cancel` | Cancel the current download session |

---

## Admin Commands

| Command | Description |
|---|---|
| `/addpremium <user_id>` | Add a user to the premium list |
| `/rempremium <user_id>` | Remove a user from the premium list |
| `/listpremium` | Show all current premium users |
| `/addsudo <user_id>` | Add a user to the sudo list |
| `/remsudo <user_id>` | Remove a user from the sudo list |
| `/listsudo` | Show all current sudo users |

---

## Docker Deployment

<img src="https://img.shields.io/badge/Deploy-Docker-2496ED?style=flat-square&logo=docker&logoColor=white" alt="Docker" />

**Build the Docker image:**

```bash
docker build -t crunchy-bot-cli .
```

**Run the container:**

```bash
docker run -d --name crunchy-bot-cli crunchy-bot-cli
```

**Run with mounted volumes:**

```bash
docker run -d \
  --name crunchy-bot-cli \
  -v "$(pwd)/downloads:/app/downloads" \
  crunchy-bot-cli
```

---

## VPS Deployment

<img src="https://img.shields.io/badge/Deploy-VPS-8b5cf6?style=flat-square&logo=linux&logoColor=white" alt="VPS" />

**Connect to your VPS:**

```bash
ssh user@your-server-ip
```

**Install system dependencies:**

```bash
sudo apt update
sudo apt install python3 python3-pip python3-venv ffmpeg -y
```

**Clone and set up the project:**

```bash
git clone https://github.com/ToonTamilIndia/Crunchy-Bot-CLI.git
cd Crunchy-Bot-CLI

python3 -m venv venv
source venv/bin/activate

pip install -r requirements.txt
```

**Edit the configuration:**

```bash
nano config.py
```

**Run the bot:**

```bash
python3 tg.py
```

---

## Running with tmux

<img src="https://img.shields.io/badge/Process-tmux-14b8a6?style=flat-square&logo=tmux&logoColor=white" alt="tmux" />

**Install tmux:**

```bash
sudo apt install tmux -y
```

**Create a new session:**

```bash
tmux new -s crunchybot
```

**Start the bot inside the session:**

```bash
source venv/bin/activate
python3 tg.py
```

**Detach from the session:**

```
Ctrl + B, then D
```

**Reattach later:**

```bash
tmux attach -t crunchybot
```

---

## Running with systemd

<img src="https://img.shields.io/badge/Process-systemd-ec4899?style=flat-square&logo=linux&logoColor=white" alt="systemd" />

**Create the service file:**

```bash
sudo nano /etc/systemd/system/crunchybot.service
```

**Paste the following and update the paths to match your setup:**

```ini
[Unit]
Description=Crunchy-Bot/CLI Telegram Bot
After=network.target

[Service]
User=your_username
Group=your_group
WorkingDirectory=/path/to/Crunchy-Bot-CLI
ExecStart=/path/to/Crunchy-Bot-CLI/venv/bin/python3 /path/to/Crunchy-Bot-CLI/tg.py
Restart=always
RestartSec=5
StandardOutput=append:/var/log/crunchybot.log
StandardError=append:/var/log/crunchybot-error.log

[Install]
WantedBy=multi-user.target
```

**Enable and start the service:**

```bash
sudo systemctl daemon-reload
sudo systemctl enable crunchybot.service
sudo systemctl start crunchybot.service
```

**Check status:**

```bash
sudo systemctl status crunchybot.service
```

**View live logs:**

```bash
tail -f /var/log/crunchybot.log
```

---

## Project Structure

```
Crunchy-Bot-CLI/
├── cli.py               # Command-line interface entry point
├── tg.py                # Telegram bot entry point
├── config.py            # Project configuration
├── requirements.txt     # Python dependencies
├── Dockerfile           # Docker build file
├── downloads/           # Completed output files
├── temp/                # Temporary working files
├── utils/               # Shared utility modules
└── README.md            # Project documentation
```

---

## Credits

This project is inspired by and adapted from:

- **[Yoimi](https://github.com/NyaShinn1204/Yoimi)** by [NyaShinn1204](https://github.com/NyaShinn1204)
- **[multi-downloader-nx](https://github.com/anidl/multi-downloader-nx/)** by [anidl](https://github.com/anidl)
- **[Crunchy-Downloader](https://github.com/Crunchy-DL/Crunchy-Downloader)** by [Crunchy-DL](https://github.com/Crunchy-DL)

---

## Disclaimer

> This project is provided for **educational and personal-use automation purposes only**.
>
> This repository does **not** include DRM files, private keys, platform secrets, accounts, or protected content. Users are solely responsible for following all applicable copyright laws, platform terms of service, and local regulations.
>
> The maintainers are **not responsible** for any misuse of this project.

---

## License

```
MIT License

Copyright (c) ToonTamilIndia and ToonEncodesIndia
2025 - 2026
```

<p align="center">
  <img src="https://img.shields.io/badge/Made%20with-Python-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Made with Python" />
  <img src="https://img.shields.io/badge/Powered%20by-FFmpeg-007808?style=for-the-badge&logo=ffmpeg&logoColor=white" alt="Powered by FFmpeg" />
  <img src="https://img.shields.io/badge/Bot-Telegram-26A5E4?style=for-the-badge&logo=telegram&logoColor=white" alt="Telegram Bot" />
</p>

<p align="center">
  <a href="https://github.com/ToonTamilIndia/Crunchy-Bot-CLI">
    <img src="https://readme-typing-svg.demolab.com?font=Fira+Code&size=14&duration=4000&pause=2000&color=9ca3af&center=true&vCenter=true&width=400&height=30&lines=Copyright+%C2%A9+ToonTamilIndia+%26+ToonEncodesIndia" alt="Footer" />
  </a>
</p>