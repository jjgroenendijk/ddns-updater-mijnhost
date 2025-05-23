# 🌩️ Mijn.host Dynamic DNS Updater 🐳

Automatically keep your [mijn.host](https://mijn.host) DNS records synced with your dynamic IP! This Dockerized updater handles multiple domains and A/AAAA records with a simple YAML config. Uses a **pre-built image** for quick setup.

## ✨ Core Features

*   🔄 **Auto DNS Updates**: For multiple domains & A/AAAA records.
*   🆕 **Auto Record Creation**: If a record doesn't exist, it's made.
*   ⚙️ **Easy YAML Config**: `dns_config.yml` for all your settings.
*   🐳 **Dockerized**: Pull & run! No local build needed.
*   💾 **Smart IP Caching**: Reduces API calls.
*   📝 **Clear Logging**: See what's happening.

## 🚀 Get Started

**Before you begin:**
*   Ensure Docker is installed and running.
*   Have your Mijn.host API Key ready.
*   Know which domain(s) at Mijn.host you want to update.

### 1️⃣ Prepare Your Local Files

You'll need these files in your project directory:

*   **`.env` file (for your API Key)**:
    Create it with this content:
    ```env
    MIJNHOST_API_KEY=YOUR_MIJNHOST_API_KEY_HERE 
    ```
    🔑 **Crucial**: Add `.env` to your `.gitignore`!

*   **`dns_config.yml` file (your domain settings template)**:
    An example file will be created after the first run in the config directory (`./config/dns_config.yml`).

### 2️⃣ Configure Docker Compose

Create a `docker-compose.yml` file in your project directory:

```yaml
services:
  ddns-updater:
    image: jjgroenendijk/ddns-updater-mijnhost:latest
    container_name: mijnhost_ddns_updater
    restart: unless-stopped
    environment:
      - MIJNHOST_API_KEY=${MIJNHOST_API_KEY}
    volumes:
      - ./config:/app/config
```

### 3️⃣ Run the Updater!

Open your terminal in the project directory and launch:

```bash
docker-compose up -d
```

**That's it!** Your DDNS updater is now running.

## 🛠️ Managing Your Updater

**View Logs**: See what the updater is doing.
    ```bash
    docker-compose logs -f ddns-updater
    ```
**Stop**:
    ```bash
    docker-compose down
    ```

## Alternative: `docker run` (Manual)

If you prefer not to use Docker Compose:

1.  Ensure steps 1️⃣ (Prepare Local Files) are done.
2.  Run this command (replace `YOUR_MIJNHOST_API_KEY_HERE` if not using `.env` properly):
    ```bash
    docker run -d --name ddns_updater \
      --restart=unless-stopped \
      -e MIJNHOST_API_KEY="YOUR_MIJNHOST_API_KEY_HERE" \
      -v "$(pwd)/config:/app/config" \
      jjgroenendijk/ddns-updater-mijnhost:latest
    ```

## 🛡️ Security Reminder

*   Your `MIJNHOST_API_KEY` is sensitive. Keep it safe in `.env` and **ensure `.env` is in your `.gitignore`**.
*   The container runs as a non-root user for added security.

Enjoy your always-updated DNS records! 🎉


Test123
