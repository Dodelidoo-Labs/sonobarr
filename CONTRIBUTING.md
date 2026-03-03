# Contributing to Sonobarr

Thank you for contributing to Sonobarr. This guide defines the required workflow for local development, testing, and pull requests.

## Branch and Pull Request Policy

- Base all work on the `develop` branch.
- Open pull requests against `develop`.
- Keep each pull request focused on one feature or one fix.
- For substantial non-bugfix work, open an issue first to align on scope.

## Local Development Setup

1. Clone the repository and switch to `develop`:
   ```bash
   git clone https://github.com/Dodelidoo-Labs/sonobarr.git
   cd sonobarr
   git checkout develop
   ```
2. Create `docker-compose.override.yml` with a local source mount and your reverse proxy network:
   ```yaml
   services:
     sonobarr:
       build:
         context: .
         dockerfile: Dockerfile
         network: host
       image: sonobarr-local
       volumes:
         - ./config:/sonobarr/config
         - /etc/localtime:/etc/localtime:ro
         - ./src:/sonobarr/src
       # ports:
       #   - "5000:5000"
       networks:
         npm_proxy:
           ipv4_address: 192.168.97.23 # update for your environment

   networks:
     npm_proxy:
       external: true
   ```
3. Build and start the local stack:
   ```bash
   sudo docker compose up -d
   ```
4. Implement your changes in `src/`, `migrations/`, and related project files.

## Validation Requirements

Before opening a pull request, verify the change in a running container:

1. Restart and validate normal startup:
   ```bash
   sudo docker compose down && sudo docker compose up -d
   ```
2. Confirm behavior in the UI and clear browser cache if needed.
3. Run final clean start validation:
   ```bash
   sudo docker compose down -v --remove-orphans
   sudo docker system prune -a --volumes -f
   sudo docker compose up -d
   ```

### Manual Test Coverage

- Test as both an admin and a regular user account.
- Test in at least two different browsers, for example Safari and Chrome.
- Validate both developer expectations and end-user behavior.
- Preserve backward compatibility and verify upgrade and downgrade paths for schema changes.

If your change affects configuration or database state, remove `./config` before rebuilding so migrations and initialization paths are tested from a clean state.

## Pull Request Quality Bar

- Include a clear summary of what changed and why.
- Describe how you tested it, including user roles and browsers used.
- Note any migration impact, compatibility concerns, or operational risks.
- Expect maintainer review of both code quality and runtime behavior before merge.

## Attribution and Changelog

Maintainers curate release notes and changelog entries. If you want explicit credit text, include your preferred attribution in the pull request description.

## AI-Assisted Contributions

AI-assisted contributions are allowed. You are responsible for the submitted code quality and correctness, including security and maintainability.

Low-quality, unreviewed, or non-functional generated code will be rejected. Repeated low-quality submissions after maintainer feedback can result in loss of contribution privileges.
