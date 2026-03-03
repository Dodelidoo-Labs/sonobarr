# Super-admin Bootstrap Behavior

## Scope

This document defines the startup bootstrap contract for the super-admin account.

## Environment Variables

Sonobarr reads these variables from environment values:

- `sonobarr_superadmin_username`
- `sonobarr_superadmin_password`
- `sonobarr_superadmin_display_name`
- `sonobarr_superadmin_reset`

If username or password is missing or blank, Sonobarr falls back to:

- Username: `admin`
- Password: `change-me`

## Startup Behavior

On startup, Sonobarr runs super-admin bootstrap once per process launch:

1. If no admin exists yet, it creates the bootstrap user and sets admin privileges.
2. If at least one admin exists and `sonobarr_superadmin_reset` is not truthy, bootstrap exits without changes.
3. If `sonobarr_superadmin_reset` is truthy and the configured bootstrap username already exists, Sonobarr updates its password, display name, and admin flag.
4. If `sonobarr_superadmin_reset` is truthy and the configured bootstrap username does not exist, Sonobarr creates that user as admin.

Accepted truthy values for `sonobarr_superadmin_reset` are: `1`, `true`, `yes` (case-insensitive).

## Operational Notes

- `sonobarr_superadmin_reset` is evaluated only at startup, so a restart is required.
- Leave `sonobarr_superadmin_reset=false` during normal operation.
- For one-time recovery, set `sonobarr_superadmin_reset=true`, restart once, then switch it back to `false`.
- Reset targets only the configured bootstrap username; other admin users are not rewritten.
