# W8 - Experience and identity

Status: all six items built and tested.

Important: **SSO works against a fake provider; needs your identity provider (Azure AD / Okta / Ping etc.) to verify.** SCIM is **not built**.

## Status per item

| # | Item | Status |
|---|------|--------|
| 1 | Dark mode and mobile layout | Done |
| 2 | Whole-KB map (`/map`) and impact (`/impact`) | Done |
| 3 | Environment switcher | Done |
| 4 | SSO / OIDC (`tools/auth_oidc.py`) | Done, fake provider only |
| 5 | Top-bar search to `/search` | Done (`/search` is registered) |
| 6 | Icon rail with the new screens | Done (rail scrolls) |

## Files

Created:
- `tools/auth_oidc.py`
- `tools/ui/screens_map.py`
- `tools/tests/test_ui_theme.py` (21 tests)
- `tools/tests/test_ui_map.py` (21 tests)
- `tools/tests/test_auth_oidc.py` (about 25 tests)

Edited (small, targeted):
- `tools/ui/ui_common.py`: CSS tokens, dark block, mobile block, `Ctx` gained optional `theme`, `env`, `sso`, `roles`, theme link, environment box, `SEARCH_FORM`, rail icons.
- `tools/ui/server.py`: `/theme`, `/env`, `/login`, `/oidc/callback`, `/logout`, SSO gate, signed-session user, search-form switch, `/whoami` refused while SSO is on.
- `tools/ui/views.py`: one line, the right pane of Build uses `C.current_env(ctx)`.
- `tools/ui/screens_compare.py` (not mine, one small addition the brief asked for): a "Database environment" card.

## How it works / how to run

1. Theme. Colours are CSS variables. The `theme` cookie holds `auto`, `dark` or `light`. `GET /theme?set=dark` (or `POST /theme`) sets it and returns to the page you were on. No JavaScript. At 800px or less the rail becomes a scrolling strip, panes stack, tables scroll sideways and buttons are at least 40px high.
2. Map. `/map` shows a clustered overview (blocks per layer and folder, weighted lines). Layers: Sources, Tables, Jobs, APIs, Screens (plus Other), mapped from graph node types. Click a block to drill down, click an object to recentre. The neighbourhood view takes 1 to 3 hops, draws SVG with radial rings, and shows at most 300 nodes with a "Showing N of M" note. Edges: parsed solid, catalogue dashed, ai-proposed dotted. There is a list view and a search box. `/impact?id=...` lists what changes if an object changes (and what it depends on), with trust signals from `trust.Trust`.
3. Environment. The header lists environments from `db-environments.yaml` and stores the choice in the `metis_env` cookie. With one environment (or none) the header shows plain text as before. Build and Compare use the chosen environment.
4. SSO. Add an `auth:` section to the profile:
   ```
   auth:
     mode: oidc            # none (default) | oidc
     issuer: https://idp.example
     client_id: ...
     client_secret_env: METIS_OIDC_SECRET
     redirect_uri: https://host/oidc/callback
     scopes: [openid, profile, email]
     allowed_domains: [example.com]
     session_secret_env: METIS_SESSION_SECRET
     groups_claim: groups
     group_map: {idp-group: role}
     session_hours: 8
   ```
   Check it with `python auth_oidc.py check <kb> [--online]`. With `mode: none` behaviour is exactly as before.
   Flow: discovery, `/login` redirect with state, nonce and PKCE S256, code exchange at `/oidc/callback`, ID-token checks (iss, aud/azp, exp, iat, nbf, nonce, sub, RS256 only), HMAC-signed session cookie. Identity is the verified `preferred_username`, else the verified `email`. With SSO on, the name box is replaced by "Signed in as ... Sign out", the `metis_user` cookie is ignored, and `kb_gate` actions record the verified identity. RSA is checked with `cryptography` when installed, otherwise with pure-Python big-int math (both tested).
5. Search. The top bar posts `GET /search?q=` when `/search` is registered, otherwise it keeps `GET /files?find=`. `/files?find=` still works.
6. Rail. Icons exist for owners, search, chat, quality, notify, federation, suggest, map. The rail scrolls when it is too tall. A test renders it with all of them.

## Tests

From `tools/`: `python -m unittest tests.test_ui_theme tests.test_ui_map tests.test_auth_oidc -v`.
Last run of every `tests.test_ui*` module plus `tests.test_auth_oidc`: 307 tests, OK (1 skipped).

## Limits (honest)

- SSO was only tested against a fake in-process provider. It has not met Azure AD, Okta or Ping. Expect to adjust claim names, `groups_claim`, scopes and redirect URIs for yours.
- SCIM (automatic user and group provisioning) is not built.
- No refresh tokens and no back-channel logout. Sessions end when `session_hours` passes or on Sign out.
- IdP groups are mapped to role labels and shown. They do not automatically grant `kb_gate` lead rights. Leads still come from the profile `owners` / `gate.certifiers`, matched by the verified name.
- Only RS256 ID tokens are accepted. Other algorithms (including `none` and HS256) are rejected.
- The map overview caps folders per layer (15) and links (200). The neighbourhood view caps at 300 nodes.
- Dark-mode contrast is tested for the shared tokens. Inline colours written by other screens are remapped by CSS overrides, not checked one by one.

## Hooks for the integrator

- `templates/kb-profile.yaml`: add the `auth:` block above with `mode: none` as default.
- CHANGELOG and manual: dark mode, mobile layout, environment switcher, map and impact, SSO, top-bar search.
- **Bug in W1's file, not fixed by me:** `screens_owners.py` is skipped when the server starts: `ValueError: action /owners/recalibrate returns to unknown screen /owners?view=recalibrate`. `/owners` is therefore not registered in the live server, although `tests/test_ui_owners.py` passes.
- `/map` and `/impact` are both in `screens_map.py`; `NAV` has only `/map`.
- `server.py` switches the top-bar search to `/search` after `load_screens()`. If W2 removes `screens_search.py`, it falls back to `/files` on its own.
