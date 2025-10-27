# Changelog
All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]
### Fixed
- GitHub 429 on images by loading the Screenshots from an external domain

## [0.9.0] - 2025-10-13
### Added
- Add REST API with API key auth.
- Add ListenBrainz discovery + Lidarr monitoring.
- Deep Lidarr Integration

### Security
- Harden startup and refactor web/API logic.

## [0.8.0] - 2025-10-10
### Added
- "Request Artist" logic for non-admin users. Admins can approve/deny requests.

## [0.7.0] - 2025-10-10
### Added
- LastFM integration (for each user) to get "My LastFM recommendations".

### Changed
- Settings persistence now writes atomically to `settings_config.json` and forces `0600` permissions to keep API keys and admin credentials private inside the container.

## [0.6.0] - 2025-10-09
### Added
- OpenAI-powered "AI Assist" modal that turns natural language prompts into fresh discovery sessions.
- Settings modal now surfaces every persisted configuration option, grouped by integration.

### Changed
- `.env` enumerates all available environment keys with sensible defaults.
- Discovery sidebar, header, and card layout refreshed for a nicer experience.

### Fixed
- Biography modal sanitisation now retains Last.fm paragraph breaks and inline links for improved readability.

## [0.5.0] - 2025-10-08
### Added
- Application factory bootstrapping with modular blueprints, services, and Socket.IO handlers.
- CSRF protection via Flask-WTF across all forms and API posts.
- Flask-Migrate integration that automatically initializes and upgrades the database on container start.

### Changed
- Docker entrypoint now exports `PYTHONPATH`, prepares the migrations directory under the mounted config volume, and runs migrations before Gunicorn boots.
- Release version metadata is injected at build time and surfaced in the footer badge.

## [0.4.0] - 2025-10-08
### Added
- Software version and update status in footer

### Fixed
- Actually use .env file instead of environment docker variables

## [0.3.0] - 2025-10-08
### Added
- Fallback to play iTunes previews when a YouTube API key is unavailable.

## [0.2.0] - 2025-10-07
### Added
- Full user management and authentication workflow.
- Super-admin bootstrap settings.

## [0.1.0] - 2025-10-06
### Added
- Revamped user interface with progress spinners and a “Load more” button.
- YouTube-based audio prehear support.

### Removed
- Spotify integration.
