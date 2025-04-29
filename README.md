# Crunchy-Bot/CLI

Crunchy Bot/CLI allows users to download videos from the Crunchyroll platform via a command-line interface (CLI) or a Telegram bot.

## Features

* Download Crunchyroll videos via CLI or Telegram Bot
* Customizable output title format
* Subtitle selection (hardsubs or softsubs, depending on availability)
* Audio track selection
* Batch downloading capabilities
* Metadata tagging for downloaded files
* Optional watermarking (if configured)

## Prerequisites

Before you can use Crunchy-Bot/CLI, you need the following:

1.  **`l3.wvd` File:**
    * This project requires a Widevine L3 CDM file (`l3.wvd`) for decrypting Crunchyroll streams.
    * **IMPORTANT:** This file is **NOT** provided in this repository due to legal restrictions. You must acquire this file yourself.
    * Place the `l3.wvd` file in the root directory of this project (the same folder where `cli.py` and `tg.py` are located).

2.  **`mp4decrypt` Binary:**
    * A `mp4decrypt` binary is necessary for decrypting the downloaded video segments.
    * Ensure you have the correct binary compatible with your operating system and architecture (e.g., Linux x86_64, Linux ARM, Windows x64). You may need to compile it or find a pre-built version.
    * Place the `mp4decrypt` binary in the project's root directory or ensure it is accessible via your system's PATH environment variable.
    * **Make the binary executable** (on Linux/macOS):
        ```bash
        chmod +x mp4decrypt
        ```

## Installation

Follow these steps to set up the project:

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/ToonTamilIndia/Crunchy-Bot-CLI.git
    cd Crunchy-Bot-CLI
    ```

2.  **Install dependencies:**
    It's highly recommended to use a Python virtual environment.
    ```bash
    # Create a virtual environment (optional but recommended)
    python3 -m venv venv

    # Activate the virtual environment
    # On Linux/macOS:
    source venv/bin/activate

    # Install required packages
    pip install -r requirements.txt
    ```

## Configuration

* Both the CLI and the Telegram Bot functionalities can be customized through the `config.py` file.
* Open `config.py` in a text editor and adjust settings such as download paths, filename templates, Telegram Bot Token, allowed user IDs, and other preferences according to your needs.

## Usage

Make sure you have completed the **Prerequisites**, **Installation**, and **Configuration** steps before running the bot.

1.  **Command-Line Interface (CLI):**
    * Navigate to the project directory in your terminal.
    * Activate the virtual environment if you created one (`source venv/bin/activate`).
    * Run the CLI script:
        ```bash
        python3 cli.py
        ```
    * The script will guide you through logging into Crunchyroll and selecting videos or series to download.

2.  **Telegram Bot:**
    * Ensure you have entered your Telegram Bot Token and configured other relevant settings in `config.py`.
    * Navigate to the project directory in your terminal.
    * Activate the virtual environment if you created one (`source venv/bin/activate`).
    * Run the Telegram bot script:
        ```bash
        python3 tg.py
        ```
    * Interact with your bot on Telegram using the commands it supports.

## Deployment

You can deploy Crunchy-Bot/CLI in several ways:

### Docker

1.  **Build the Docker image:**
    ```bash
    docker build -t crunchy-bot-cli .
    ```

2.  **Run the container:**
    * For the CLI (interactive):
        ```bash
        docker run crunchy-bot-cli
        ```
    * For the Telegram Bot (detached):
        ```bash
        docker run -d --name crunchy-tg-bot
        ```
    * **Adjust the Dockerfile to specify the entry point**  
  Set the command to run the desired application script (`cli.py` or `tg.py`). By default, `tg.py` is used:

  ```Dockerfile
  # For CLI mode:
  CMD ["python3", "cli.py"]

  # For Telegram Bot mode (default):
  CMD ["python3", "tg.py"]
  ```

### VPS / Self-Hosting

1.  Connect to your VPS or server via SSH.
2.  Ensure Python 3 and `pip` are installed.
3.  Follow the **Installation** steps (clone repo, install dependencies, preferably in a virtual environment).
4.  Place your `l3.wvd` file and the executable `mp4decrypt` binary in the project directory.
5.  Configure `config.py` as needed.
6.  **Running Persistently (especially for the Telegram bot):**
    * **Using `tmux` or `screen`:**
        * Start a new session: `tmux new -s crunchybot`
        * Activate virtual environment: `source venv/bin/activate`
        * Run the script: `python3 tg.py`
        * Detach from the session: Press `Ctrl+b` then `d`. The script will keep running.
        * Reattach later: `tmux attach -t crunchybot`
    * **Using `systemd` (Linux):**
        * Create a service file (e.g., `/etc/systemd/system/crunchybot.service`).
            ```ini
            [Unit]
            Description=Crunchyroll Telegram Bot Service
            After=network.target

            [Service]
            User=your_username # Replace with the user the bot should run as
            Group=your_group   # Replace with the user's group
            WorkingDirectory=/path/to/Crunchy-Bot-CLI # Replace with the actual path
            ExecStart=/path/to/Crunchy-Bot-CLI/venv/bin/python3 /path/to/Crunchy-Bot-CLI/tg.py # Adjust path to python if not using venv
            Restart=always # Or 'on-failure'
            StandardOutput=file:/var/log/crunchybot.log # Optional: Log output
            StandardError=file:/var/log/crunchybot.err.log # Optional: Log errors

            [Install]
            WantedBy=multi-user.target
            ```
        * Reload systemd: `sudo systemctl daemon-reload`
        * Enable the service (to start on boot): `sudo systemctl enable crunchybot.service`
        * Start the service: `sudo systemctl start crunchybot.service`
        * Check status: `sudo systemctl status crunchybot.service`

## Credits

* This project takes inspiration and possibly uses adapted code from [Yoimi by NyaShinn1204](https://github.com/NyaShinn1204/Yoimi). Many thanks to the original author.
