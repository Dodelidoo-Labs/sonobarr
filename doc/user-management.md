# User Management And Artist Approval

## Scope

This document describes the user access flags that control account status, administrative privileges, and artist approval behavior.

## User Flags

The `users` table includes these access-control fields:

- `is_active`: Controls whether the user can authenticate.
- `is_admin`: Grants access to admin routes and direct artist addition.
- `auto_approve_artist_requests`: Allows non-admin users to add artists directly without waiting for manual admin approval.

## Admin UI Controls

The user management page at `/admin/users` provides toggles for:

- Active account
- Admin privileges
- Auto approve artist additions

Admins can set these flags when creating a user and when editing an existing user.

## Artist Addition And Request Flow

Server-side behavior is enforced in `DataHandler`:

- Users with `is_admin = true` or `auto_approve_artist_requests = true` can add artists directly to Lidarr.
- Users without either flag submit a pending artist request for manual admin approval.
- Unauthorized direct add attempts are rejected with an "Approval Required" message.

The frontend receives permission metadata from the socket `user_info` payload and renders the action button accordingly:

- Direct-add users see the default add action.
- Manual-approval users see the request action.
