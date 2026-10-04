# Start here

This fork assembles one CLIProxyAPI gateway and three native plugins. The gateway routes requests to existing subscriptions and API accounts; it does not run model inference. EasyCLIProxyAPI manages the local Mac gateway. Codex, Claude Code, OpenCode and Pi remain clients. T3 Code runs those clients and uses their catalogs.

The source of truth is `stack.lock.json`, which pins reviewed commits in seven forks. The `review/*` branches hold scoped contributions. This `deployment/gateway-stack` branch adds deployment tools and documentation; do not propose the personal deployment folder as part of the upstream capability PR.

## Current design

```text
T3 Code / Codex / Claude Code / OpenCode / Pi
  -> personal or work downstream key
  -> one CLIProxyAPI gateway
       -> Codex / Claude / Antigravity OAuth credentials
       -> Work LiteLLM configured API deployments
       -> CommandCode and OpenCode Go provider plugins
       -> account-binding plugin checks scope/source and session policy
```

Routing IDs such as `personal/codex-oauth/gpt-6.1-sol` remain stable. Short labels such as `P/CX · 6.1 Sol` are presentation only. Compatibility aliases keep existing conversations addressable; they must not silently redirect to another account, provider, model or billing source. Canonical model identity selects trusted native prompts independently of routing names. Context limits, modalities and efforts must come from declared metadata, not guesses based on display names.

`P` / `W` mean Personal / Work; `CX` Codex OAuth, `CL` Claude OAuth, `AG` Antigravity, `LL` LiteLLM, `GO` OpenCode Go, `CC` CommandCode. Personal and work clients have separate home/config/key directories. Title generation in T3 is the user's stated exception. The binding plugin enforces scheduler routes; direct plugin endpoints are a documented limitation, so do not expose an unrestricted key as a general client key.

Every base capability starts with what the provider offers. Authenticated account metadata takes precedence over general provider/model metadata. Local code translates those values into each client's schema; it must not infer entitlement from a plan name, price or model name. The fork supports ultrafast and shows it whenever the matched account reports it. See [CAPABILITIES.md](CAPABILITIES.md) for precedence, missing-data behavior and remaining gaps.

## Local updates

1. Read [CONTRIBUTIONS.md](CONTRIBUTIONS.md) and [SYNC.md](SYNC.md).
2. Use Python 3.12+ on the build host. Check out exact sources with `python3 deployment/prepare_sources.py`. This creates an ignored `.sources` directory and refuses to replace changed checkouts.
3. Test and build changed components. Publish unique versions with checksums and increasing revisions. Preserve the existing channel URLs and rollback versions.
4. Easy's reviewed core channel and plugin store install published builds. The application itself still needs the reviewed local build until the patches land upstream or a trusted signed release is available. Do not use an official app update to replace the required safeguards.
5. Preserve keys, account/session bindings, catalogs and aliases; verify both scopes and a tool continuation. Main Codex app/CLI/config/catalog changes remain the user's cutover step.

Stable channels:

- Core: `https://raw.githubusercontent.com/samaluk/CLIProxyAPI/reviewed-channel/core.json`
- Native plugins: `https://raw.githubusercontent.com/samaluk/CLIProxyAPI/reviewed-channel/plugins.json`

T3 and Pi remain stock installations. Their optional fork branches are reviewable contributions, not dependencies to install automatically. T3's OpenCode v2 catalog loader may accept a partial initial snapshot; do not downgrade OpenCode or replace T3 merely because this occurs. The shared launcher must preserve OpenCode server authentication variables for `serve` while stripping inherited account/config overrides.

## Future Synology deployment

Read [NAS-HANDOFF.md](NAS-HANDOFF.md). The NAS has not been migrated by this sync. The container recipe builds Linux amd64 libraries from the same Debian base, without AVX requirements. Build on another machine; keep the weak NAS for runtime.

An agent can start with:

> Clone `https://github.com/samaluk/CLIProxyAPI`, branch `deployment/gateway-stack`. Read `deployment/README.md`, `deployment/stack.lock.json` and `deployment/NAS-HANDOFF.md`. Set up the pinned gateway on my Synology using the existing homelab/Komodo conventions and Tailscale. Preserve account bindings and routing IDs; transfer credentials privately. Verify the staged service before any client cutover. Keep my main Codex configuration unchanged and give me its final cutover step.

Credentials, auth files, catalogs containing native prompts, binding state and GUI secrets are intentionally absent from this public repository. The handoff agent must use the existing private deployment or ask for the specific missing credential; it must not invent replacements.
