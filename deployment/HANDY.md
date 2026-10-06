# Handy with the scoped gateway

Handy 0.9.8 remains stock. Its local speech-recognition model and prompt were preserved. The gateway handles only its optional text post-processing.

Two separate failures occurred. The newly entered key was absent from the live NAS auth configuration and returned 401. The registered Personal key fixed authentication, but chat requests then returned 403 because the account-binding policy requires an explicit session identity and Handy supplies none.

## Installed Mac adapter

Stock Homebrew Caddy runs a separate loopback listener at `http://127.0.0.1:8318/v1`, launch agent `me.cpa.handy-personal`. It accepts only the existing Personal key, presents the authenticated Personal catalog in OpenAI format, and adds a persistent Personal application session ID before forwarding chat completions over verified TLS to the NAS. It forces the upstream Personal credential even if a request contains duplicate authorization headers. The original localhost compatibility relay on port 8317 and NAS policy are unchanged.

This is gateway deployment glue, not a fork or replacement build of Handy. The application identity groups Handy's stateless operations within Personal; it does not claim a separate agent thread for every dictation. Work keys receive 401 at this listener and Work model routes receive 403 from NAS policy. The listener supports only model discovery and chat completions.

The model-list export is `personal/catalogs/handy-models.json`. Its presence opts it into the existing five-minute catalog sync. It contains only model IDs, never native prompts or credentials. The relay's private Caddyfile holds the Personal key and its separate `session.json` holds the application identity. Keep these files private and preserve session identity across reinstalls.

The reviewed source is `deployment/handy-personal-client`, based on `deployment/litellm-catalog-labels`. Before installing this opt-in, install the matching client sync helpers, then install stock Caddy and the relay:

```sh
/opt/homebrew/bin/python3 deployment/mac/scripts/install_remote_sync.py --profiles "$HOME/Library/Application Support/Agent Profiles" --endpoint https://YOUR-NAS.YOUR-TAILNET.ts.net
/opt/homebrew/bin/python3 deployment/mac/scripts/install_handy.py --profiles "$HOME/Library/Application Support/Agent Profiles"
cpa-catalog-sync --apply
```

The relay installer refuses if the installed sync helper differs from its reviewed source, so the new list cannot silently remain a one-time export. On later changes, close Handy or wait until post-processing is idle and rerun `install_handy.py --replace`. This restarts only the owned Handy listener. Keep the original compatibility relay and all live agents running. On another machine, this macOS-only launcher needs the appropriate OS service adapter; do not claim it is installed automatically everywhere.

Handy uses Custom provider, the loopback URL above, the registered Personal key and `personal/codex-oauth/gpt-6-luna`. Its model refresh log returned 200. Direct synthetic text processing through the adapter returned 200. Model discovery listed 73 Personal models, zero foreign IDs; unauthenticated and Work keys returned 401, and a Work model request returned 403. These tests did not record microphone audio or transmit historical dictations. The native Handy settings display was checked.

## Upstream alternative

[Handy discussion #2128](https://github.com/cjpais/Handy/discussions/2128) describes the same missing-header problem and local proxy workaround. The maintainer prefers proper provider support over generic header additions. [Issue #485](https://github.com/cjpais/Handy/issues/485) covers Cloudflare authentication headers and was closed to move feature requests to Discussions, not as an implemented fix. The search found no matching session/header implementation PR. PR #633 concerns environment-based URLs, which does not supply request identity.

A future Handy contribution should agree on explicit provider/gateway support first. If headers are accepted, scope them per provider, reject transport headers and CR/LF, redact logs, preserve normal authentication and prevent credential forwarding on cross-origin redirects. Dynamic identity should be created per dictation and reused for that dictation's retries. The original invalid-key 401 is not a Handy bug.

The adapter remains a removable local workaround until an upstream-compatible Handy release can send suitable identity and discover the scoped catalog directly. No issue, discussion message or Handy PR was posted during this review.
