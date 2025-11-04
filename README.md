# Sonobarr

> Music discovery for Lidarr power users, blending Last.fm insights, ListenBrainz playlists, and a modern web UI.

[![Release](https://img.shields.io/github/v/release/Dodelidoo-Labs/sonobarr?label=Latest%20release&cacheSeconds=60)](https://github.com/Dodelidoo-Labs/sonobarr/releases)
[![Container](https://img.shields.io/badge/GHCR-sonobarr-blue?logo=github)](https://github.com/Dodelidoo-Labs/sonobarr/pkgs/container/sonobarr)
[![License](https://img.shields.io/github/license/Dodelidoo-Labs/sonobarr)](./LICENSE)

Sonobarr marries your existing Lidarr library with Last.fm’s discovery graph to surface artists you'll actually like. It runs as a Flask + Socket.IO application, ships with a polished Bootstrap UI, and includes admin tooling so folks can share a single instance safely.

<p align="center">
  <img src="https://inubes.app/apps/files_sharing/publicpreview/5j6WJYrCGcBijdo?file=/&fileId=27122&x=3840&y=2160&a=true&etag=e598390299bd52d0b98cf85a4d7aacee" alt="Sonobarr logo">
</p>

---

## Table of contents

1. [Features at a glance](#features-at-a-glance)
2. [How it works](#how-it-works)
3. [Quick start (Docker)](#quick-start-docker)
4. [Environment reference](#environment-reference)
5. [Local development](#local-development)
6. [Using the app](#using-the-app)
7. [Screenshots](#screenshots)
8. [Troubleshooting & FAQ](#troubleshooting--faq)
9. [Contributing](#contributing)
10. [License](#license)

---

## Features at a glance

- 🔌 **Deep Lidarr integration** – sync monitored artists, apply per-source monitor strategies, toggle monitor-new-albums policies, and send additions straight back to Lidarr.
- 🧭 **Personal discovery hub** – stream batches sourced from your Lidarr library, your saved Last.fm scrobbles, and ListenBrainz Weekly Exploration playlists, all controllable from the sidebar.
- 🤖 **AI assistant** – describe the vibe you want and let any OpenAI-compatible model seed new sessions with fresh artists, respecting optional library exclusions.
- 🙋 **Artist requests workflow** – non-admins raise requests, admins approve or reject with a single click, and every action is audited in real time.
- 🎧 **Preview & context panels** – launch YouTube or iTunes previews, inspect Last.fm biographies, and read key stats without leaving the grid.
- ⚡️ **Real-time UX** – Socket.IO keeps discovery progress, toast alerts, and button states in sync across every connected client.
- 👥 **Role-based access** – authentication, user management, profile controls for personal services, and admin-only settings live in one UI.
- 🛡️ **Hardened configuration** – atomic settings writes, locked-down file permissions, and CSRF-protected forms keep secrets safe.
- 🔔 **Update & schema self-healing** – footer badges surface new releases and the app backfills missing DB columns before loading users.
- 🐳 **Docker-first deployment** – official GHCR image, rootless-friendly UID/GID mapping, and automatic migrations on start.
- 🌐 Public API – REST API for integrating external tools such as custom dashboards (Documentation upcoming, for now study `/api/docs/` on your instance).


---

## How it works

```text
┌──────────────────────┐        ┌──────────────────────┐
│ Lidarr (HTTP API)    │◀──────▶│ Sonobarr backend     │
│  - Artist catalogue  │        │  Flask + Socket.IO   │
│  - API key auth      │        │  Last.fm + Deezer    │
└──────────────────────┘        │  Worker threads      │
                                └─────────┬────────────┘
                                          │
                                          ▼
                                ┌──────────────────────┐
                                │ Sonobarr web client  │
                                │  Bootstrap + JS      │
                                │  Admin UX            │
                                └──────────────────────┘
```

1. Sonobarr spins up with a persistent SQLite database inside the `config/` volume.
2. Admins provide Lidarr + Last.fm credentials through the settings modal.
3. When a user starts a discovery session, Sonobarr pulls artists from Lidarr, fans out to Last.fm, and streams cards back to the browser.
4. Optional preview and biography data is enriched via YouTube/iTunes/MusicBrainz.

---

## Quick start (Docker)

> 🐳 **Requirements**: Docker Engine ≥ 24, Docker Compose plugin, Last.fm API key, Lidarr API key.

1. Create a working directory, cd into it, and make sure it’s owned by the UID/GID the container will use (defaults to `1000:1000`). This keeps every file the container writes accessible to you:
   ```bash
   mkdir -p sonobarr && cd sonobarr
   sudo chown -R 1000:1000 .
   ```
2. Download the sample configuration:
   ```bash
   curl -L https://raw.githubusercontent.com/Dodelidoo-Labs/sonobarr/develop/docker-compose.yml -o docker-compose.yml
   curl -L https://raw.githubusercontent.com/Dodelidoo-Labs/sonobarr/develop/.sample-env -o .env
   ```
3. Open `.env` and populate **at least** these keys:
   ```env
   secret_key=change-me-to-a-long-random-string
   lidarr_address=http://your-lidarr:8686
   lidarr_api_key=xxxxxxxxxxxxxxxxxxxxxxxx
   last_fm_api_key=xxxxxxxxxxxxxxxxxxxxxxxx
   last_fm_api_secret=xxxxxxxxxxxxxxxxxxxxxxxx
  # Optional – enables the AI assistant modal (any OpenAI-compatible endpoint)
  # openai_api_key=sk-...
  # openai_api_base=https://api.openai.com/v1
   ```
   > All keys in `.env` are lowercase by convention; the app will happily accept uppercase equivalents if you prefer exporting variables.
4. Start Sonobarr:
   ```bash
   docker compose up -d
   ```
5. Browse to `http://localhost:5000` (or the host behind your reverse proxy) and sign in using the super-admin credentials defined in `.env`.

### Reverse proxy deployment

The provided `docker-compose.yml` exposes port 5000. It is however a better practice to attache Sonobarr to an external network. To do so, add the network name and static IP so it fits your proxy stack (NGINX Proxy Manager, Traefik, etc.) to the docker compose file. No additional `environment:` stanza is needed - everything comes from the `.env` file referenced in `env_file`.

For example:
```
...
    networks:
      npm_proxy:
        ipv4_address: 192.168.97.23

networks:
  npm_proxy:
    external: true
```

### Updating

```bash
docker compose pull
docker compose up -d
```

The footer indicator will show a green dot when you are on the newest release and red when an update is available.

---

## Environment reference

All variables can be supplied in lowercase (preferred for `.env`) or uppercase (useful for CI/CD systems). Defaults shown are the values Sonobarr falls back to when nothing is provided.

| Key | Default | Description |
| --- | --- | --- |
| `secret_key` (**required**) | – | Flask session signing key. Must be a long random string; store it in `.env` so sessions survive restarts. |
| `lidarr_address` | `http://192.168.1.1:8686` | Base URL of your Lidarr instance. |
| `lidarr_api_key` | – | Lidarr API key for artist lookups and additions. |
| `root_folder_path` | `/data/media/music/` | Default root path used when adding new artists in Lidarr. |
| `lidarr_api_timeout` | `120` | Seconds to wait for Lidarr before timing out requests. |
| `quality_profile_id` | `1` | Numeric profile ID from Lidarr (see [issue #1](https://github.com/Dodelidoo-Labs/sonobarr/issues/1)). |
| `metadata_profile_id` | `1` | Numeric metadata profile ID. |
| `fallback_to_top_result` | `false` | When MusicBrainz finds no strong match, fall back to the first Lidarr search result. |
| `search_for_missing_albums` | `false` | Toggle Lidarr’s “search for missing” flag when adding an artist. |
| `dry_run_adding_to_lidarr` | `false` | If `true`, Sonobarr will simulate additions without calling Lidarr. |
| `last_fm_api_key` | – | Last.fm API key for similarity lookups. |
| `last_fm_api_secret` | – | Last.fm API secret. |
| `youtube_api_key` | – | Enables YouTube previews in the “Listen” modal. Optional but recommended. |
| `openai_api_key` | – | Optional key for your OpenAI-compatible provider. Leave empty if your endpoint allows anonymous access. |
| `openai_model` | `gpt-4o-mini` | Override the model slug sent to the provider. |
| `openai_api_base` | – | Custom base URL for LiteLLM, Azure OpenAI, self-hosted Ollama gateways, etc. Blank uses the SDK default. **Must be complete base url such as `http://IP:PORT/v1` for example. |
| `openai_extra_headers` | – | JSON object of additional headers sent with every LLM call (e.g., custom auth or routing hints). |
| `openai_max_seed_artists` | `5` | Maximum number of seed artists returned from each AI prompt. |
| `similar_artist_batch_size` | `10` | Number of cards sent per batch while streaming results. |
| `auto_start` | `false` | Automatically start a discovery session on load. |
| `auto_start_delay` | `60` | Delay (seconds) before auto-start kicks in. |
| `sonobarr_superadmin_username` | `admin` | Username of the bootstrap admin account. |
| `sonobarr_superadmin_password` | `change-me` | Password for the bootstrap admin. Set to a secure value before first launch. |
| `sonobarr_superadmin_display_name` | `Super Admin` | Friendly display name shown in the UI. |
| `sonobarr_superadmin_reset` | `false` | Set to `true` **once** to reapply the bootstrap credentials on next start. |
| `release_version` | `unknown` | Populated automatically inside the Docker image; shown in the footer. No need to set manually. |
| `sonobarr_config_dir` | `/sonobarr/config` | Override where Sonobarr writes `app.db`, `settings_config.json`, and migrations. |

> ℹ️ `secret_key` is mandatory. If missing, the app refuses to boot to prevent insecure session cookies. With Docker Compose, make sure the key exists in `.env` and that `.env` is declared via `env_file:` as shown above.

---

## Local development

See [CONTRIBUTING.md](https://github.com/Dodelidoo-Labs/sonobarr/blob/main/CONTRIBUTING.md)

### Tests

Currently relying on manual testing. Contributions adding pytest coverage, especially around the data handler and settings flows, are very welcome.

---

## Using the app

1. **Sign in** with the bootstrap admin credentials. Create additional users from the **User management** page (top-right avatar → *User management*).
2. **Configure integrations** via the **Settings** button (top bar gear icon). Provide your Lidarr endpoint/key and optional YouTube key (can both be set in .env or UI)
3. **Fetch Lidarr artists** with the left sidebar button. Select the artists you want to base discovery on.
4. Hit **Start**. Sonobarr queues batches of similar artists and streams them to the grid. Cards show genre, popularity, listeners, similarity (from Last.fm), plus a status LED dot in the image corner.
5. Use **Bio** and **Listen** buttons for deeper context - the bio modal keeps Last.fm paragraph spacing intact. Click **Add to Lidarr** to push the candidate back into your library; feedback appears on the card immediately.
6. Stop or resume discovery anytime. Toast notifications keep everyone informed when conflicts or errors occur.

### AI-powered prompts

- Click the **AI Assist** button on the top bar to open a prompt modal.
- Describe the mood, genres, or examples you're craving (e.g. "dreamy synth-pop like M83 but calmer").
- Provide an API key and/or base URL in the settings modal (.env works too) for whichever OpenAI-compatible provider you use; without valid credentials the assistant stays disabled.
- The assistant picks a handful of seed artists, kicks off a discovery session automatically, and keeps streaming cards just like a normal Lidarr-driven search.

The footer shows:
- GitHub repo shortcut.
- Current version.
- A red/green status dot indicating whether a newer release exists.

---

## Screenshots

<p align="center">
  <img src="https://inubes.app/apps/files_sharing/publicpreview/6LQMEJWWxaP93Lz?file=/&fileId=27049&x=3840&y=2160&a=true&etag=c09db4470dc9f3ea6adca89d7e519aca" alt="Login Window" width="46%">
  <img src="https://inubes.app/apps/files_sharing/publicpreview/awtmqFTk4gddC4q?file=/&fileId=27051&x=3840&y=2160&a=true&etag=a054127eb80304f9ee6d1f5037e967d3" alt="Profile Settings" width="46%">
  <img src="https://inubes.app/apps/files_sharing/publicpreview/YD7SnFBwzoKcxrT?file=/&fileId=27064&x=3840&y=2160&a=true&etag=42d6f455b8d9528d97fbb85ec8fb51cb" alt="User Admin" width="46%">
  <img src="https://inubes.app/apps/files_sharing/publicpreview/YESTFRzJyH4AWwg?file=/&fileId=27046&x=3840&y=2160&a=true&etag=e279e593823bd55468450673a4e1b71a" alt="Configuration" width="46%">
  <img src="https://inubes.app/apps/files_sharing/publicpreview/CPd6anAATKAmboR?file=/&fileId=27047&x=3840&y=2160&a=true&etag=b4babd5f0b45245530ccbca71d73770d" alt="Configuration" width="46%">
  <img src="https://inubes.app/apps/files_sharing/publicpreview/NgErxcLzKEaGAt2?file=/&fileId=27038&x=3840&y=2160&a=true&etag=0cfde7b7b3d91ccecd58a708d5d4cd14" alt="AI Assist" width="46%">
  <img src="https://inubes.app/apps/files_sharing/publicpreview/x8eLQmmQjk76ddy?file=/&fileId=27045&x=3840&y=2160&a=true&etag=1f5bcc01a182f3beb87b587c9aaafb9b" alt="Artist Suggestions" width="46%">
  <img src="https://inubes.app/apps/files_sharing/publicpreview/bGH8wcnX3YofGdZ?file=/&fileId=27050&x=3840&y=2160&a=true&etag=edcb5d90429848ef0e2c3e0a9933e3aa" alt="Pre Hear" width="46%">
</p>

---

## Troubleshooting & FAQ

### The container exits with "SECRET_KEY environment variable is required"
Ensure your Compose file references the `.env` file via `env_file:` and that `.env` contains a non-empty `secret_key`. Without it, Flask cannot sign sessions.

### UI says "Update available" even though I pulled latest
The footer compares your runtime `release_version` with the GitHub Releases API once per hour. If you built your own image, set `RELEASE_VERSION` at build time (`docker build --build-arg RELEASE_VERSION=custom-tag`).

### Artists fail to add to Lidarr
Check the container logs - Sonobarr prints the Lidarr error payload. Common causes are incorrect `root_folder_path`, missing write permissions on the Lidarr side, or duplicate artists already present.

---

## Contributing

See [CONTRIBUTING.md](https://github.com/Dodelidoo-Labs/sonobarr/blob/main/CONTRIBUTING.md)

---

## License

This project is released under the [MIT License](./LICENSE).

Original work © 2024 TheWicklowWolf. Adaptations and ongoing maintenance © 2025 Dodelidoo Labs.
