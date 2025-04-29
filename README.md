```markdown
# 🚀 **Crunchy-Bot/CLI** 🎬

**Crunchy-Bot/CLI** is your ultimate tool to download **Crunchyroll** videos seamlessly. Whether you prefer the **command-line interface (CLI)** or want a more interactive experience through a **Telegram bot**, this tool has you covered! It supports everything from decryption, merging, metadata tagging, multiple audio/subtitle selections, batch downloads, and even optional watermarking. All this wrapped up in a sleek and easy-to-use interface.

---

## 🔥 **Features** 

- 🎥 **Download Crunchyroll Episodes or Entire Series** with ease
- 💻 **CLI & Telegram Bot Interface** for flexible usage
- 🔐 **DRM Decryption** via Widevine L3 & `mp4decrypt`
- 📺 **Choose Video Quality** (360p, 480p, 720p, 1080p, or original)
- 🎶 **Select Audio Tracks** (multiple languages supported)
- 📝 **Subtitles & Captions** (VTT to SRT conversion)
- 🔄 **Merge Video, Audio, and Subtitles** with FFmpeg
- 📝 **Custom Naming** (file format, optional watermark)
- 🚀 **Upload Final File** Directly to Telegram
- 👤 **Role-based Access Control** (Regular, Premium, Sudo Users)

---

## 🛠️ **Prerequisites**

Before getting started, you'll need:

1. **Widevine L3 (`l3.wvd`) File**
   - Required for DRM decryption.
   - **Not included** in the repo—please provide your own.
   - Place it in the project root directory alongside `cli.py` and `tg.py`.

2. **`mp4decrypt` Binary**
   - Needed for decrypting video and audio segments.
   - Ensure it's in the root folder or accessible via `PATH`.
   - On **Linux/macOS**:
     ```bash
     chmod +x mp4decrypt
     ```

---

## 📥 **Installation**

Get started by cloning the repo and installing dependencies:

```bash
git clone https://github.com/ToonTamilIndia/Crunchy-Bot-CLI.git
cd Crunchy-Bot-CLI
```

### Optional: Create a Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate
```

### Install Required Dependencies

```bash
pip install -r requirements.txt
```

---

## ⚙️ **Configuration**

Edit the `config.py` file to set up your personal settings:

- **Crunchyroll Credentials** (optional): `Email`, `Password`
- **Telegram Bot Credentials**: `BOT_TOKEN`, `API_ID`, `API_HASH`
- **Watermark, File Naming, Debug Options, etc.**
- **Access Control**: Define `sudo_users`, `premium_users`, and more!

---

## 🖥️ **CLI Usage Guide**

### Run the CLI

```bash
source venv/bin/activate
python3 cli.py
```

### **Download Workflow**

1. **Enter Crunchyroll URL**:
   - **Single Episode**: `https://www.crunchyroll.com/watch/GXXXXXX`
   - **Series**: `https://www.crunchyroll.com/series/GXXXXXX`

2. **Select Your Options**:
   - **Video Quality**: Choose from 360p, 480p, 720p, 1080p
   - **Audio Tracks**: Choose one or more languages
   - **Subtitles**: Choose subtitle languages

3. **Download Process**:
   - Downloads video, audio, and subtitles
   - Converts subtitles from VTT to SRT if necessary
   - Decrypts with `mp4decrypt`
   - Merges all streams using **FFmpeg**
   - Optional **Watermarking**
   - Saves a final `.mp4` file

---

## 🤖 **Telegram Bot Usage Guide**

### Run the Bot

```bash
source venv/bin/activate
python3 tg.py
```

### **How It Works**:

1. **Start the Bot**: Send `/start` on Telegram to begin.
2. **Send Crunchyroll Link**:
   ```bash
   /download https://www.crunchyroll.com/watch/GXXXXXX
   ```

3. **Interactive Workflow**:
   - Choose **Video Quality** via buttons
   - Select **Audio Tracks** (multiple options available)
   - Choose **Subtitles/Captions** languages
   - Review your selections
   - Download, decrypt, merge, and get your final video directly on Telegram

### **User Roles**:

- **Regular Users**: Max 2 audio tracks, 480p quality
- **Premium Users**: Unlimited audio tracks, no resolution limits
- **Sudo Users**: Admins with full access and controls

### **Bot Commands**:

| Command               | Description                              |
|-----------------------|------------------------------------------|
| `/start`              | Show welcome message                    |
| `/help`               | Display available commands               |
| `/download <url>`     | Start downloading the content            |
| `/cancel`             | Cancel the current download session      |

### **Admin (Sudo) Commands**:

| Command               | Description                              |
|-----------------------|------------------------------------------|
| `/addpremium <user_id>` | Add a user to the Premium tier          |
| `/rempremium <user_id>` | Remove Premium access from a user       |
| `/listpremium`        | Show list of Premium users               |
| `/addsudo <user_id>`  | Add a new Sudo (admin) user             |
| `/remsudo <user_id>`  | Remove Sudo privileges                  |
| `/listsudo`           | Show list of all Sudo users              |

---

## 🚀 **Deployment Options**

### Docker

Run in a containerized environment:

```bash
docker build -t crunchy-bot-cli .
docker run -it crunchy-bot-cli       # For CLI
docker run -d --name crunchy-tg-bot  # For Telegram Bot
```

You can customize the `Dockerfile` to specify the bot mode:

```Dockerfile
CMD ["python3", "cli.py"]  # or tg.py
```

---

### VPS Hosting with Systemd

To run the bot on a VPS with **Systemd**:

```bash
tmux new -s crunchybot
source venv/bin/activate
python3 tg.py
```

For **automatic startup**, create a `systemd` service at `/etc/systemd/system/crunchybot.service`:

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

Then enable and start the service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable crunchybot
sudo systemctl start crunchybot
```

---

## 💡 **Credits**

This project is inspired by and adapted from:
- [Yoimi by NyaShinn1204](https://github.com/NyaShinn1204/Yoimi)

---

## ⚖️ **Disclaimer**

This project is intended for **educational purposes only**.  
You are responsible for following copyright laws and platform terms.

---

© **ToonTamilIndia** & **ToonEncodesIndia** 2025 - 26
```
