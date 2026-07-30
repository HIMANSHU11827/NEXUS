# Authentication

User identity — OAuth 2.0 login flows, session tokens, dashboard auth, and gateway authorization.

**Version:** 2.0.0

## Features
- OAuth 2.0 / PKCE flow: Google and GitHub providers
- `validate_dashboard_token()` — constant-time token comparison
- `check_auth(request)` — multi-layer: session cookie → Bearer token → local anonymous
- `get_oauth_authorize_url()` / `handle_oauth_callback()` — full OAuth redirect flow
- `is_gateway_authorized(platform, sender_id)` — gateway sender authorization
- PUBLIC_PATHS: health, auth endpoints, OpenAPI docs excluded from auth
