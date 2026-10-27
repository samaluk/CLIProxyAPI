# Start here

The October 27 Argon dogfood layer changes only the locked OpenCode Go plugin.
`Dockerfile.go-plugin` builds its exact clean source using the contributor-required
debug tag and stamps `0.2.2-argon.20261027.1`. The base is the immutable October 24
native-images release; core, catalog gateway, CommandCode and account binding
binaries are retained. Source-tree and plugin hashes replace only that component
in the embedded provenance. Revert the image pin for software rollback while
retaining the latest OAuth and session state.

The standalone feature is on
[`samaluk/opencode-go-cliproxyapi:feature/gemini-argon`](https://github.com/samaluk/opencode-go-cliproxyapi/tree/feature/gemini-argon),
based directly on upstream main. The locked dogfood branch also retains the six
existing runtime contributions. All three client APIs passed live streaming,
non-streaming and tool-result continuation checks against the user's existing
Go account. The upstream PR is intentionally deferred until after dogfooding.

This fork assembles one CLIProxyAPI gateway and three native plugins. The gateway routes requests to existing subscriptions and API accounts; it does not run model inference. The Synology runs the gateway in Docker through homelab/Komodo. EasyCLIProxyAPI is retained on the Mac for rollback, with automatic core startup disabled. Codex, Claude Code, OpenCode and Pi remain clients. T3 Code runs those clients and uses their catalogs.

The source of truth is `stack.lock.json`, which pins reviewed commits in seven forks. Four components run in the NAS image: core and three native plugins. The October 23 runtime release is assembled on `deployment/20261023-upstream-defaults`, based on `deployment/proxy-authoritative-clients`. Each runtime source contains its original upstream's default `main` as fetched on October 23. Existing review branches and client layers remain intact. Easy, Pi and T3 pins remain separate historical records; stock client applications are outside this server release.

Core advances from 8.0.27 to 8.0.40 and OpenCode Go from 0.1.11 to 0.2.2, retaining the existing capability, scope, cooldown and tool-history contributions. CommandCode and account binding already match their unchanged upstream defaults. Rebase resolutions preserve upstream dynamic Claude thinking and the registered OpenCode Go release version; a stale test fixture now imports the v8 plugin API. The Linux build uses Go 1.26.10 and generic amd64, with source and binary hashes embedded in the image.

The published candidate is `ghcr.io/samaluk/cpa-gateway:20261023-upstream-defaults-1@sha256:c30dd8a9f7d414eedfd1b87cf9151fc538d11c739998d428a0bdacc810c4a9a1`. Deploy it only after NAS preflight; the homelab Compose digest identifies the deployed artifact. Full Go suites on macOS and Linux report Home cluster heartbeat and Git-backed storage corruption failures; these same failures reproduce on clean upstream `d946c4fb`. The NAS uses neither feature. All other core packages pass, as do affected-package race checks, all native plugin tests/race/vet, gateway tests, the required server build and all C-shared builds. Record NAS preflight and live acceptance separately. Rollback changes the image while preserving the newest OAuth and binding state.

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

## Update the deployed gateway

1. Read [CONTRIBUTIONS.md](CONTRIBUTIONS.md) and [SYNC.md](SYNC.md).
2. Use Python 3.12+ on the build host. Check out exact sources with `python3 deployment/prepare_sources.py`. This creates an ignored `.sources` directory and refuses to replace changed checkouts.
3. Test and build changed components. Publish unique versions with checksums and increasing revisions. Preserve the existing channel URLs and rollback versions.
4. Build the pinned Linux image on a build host, publish a unique tag and digest, and update both services in `homelab/easy-cli-proxy/compose.yaml` through a PR. Komodo deploys main. Easy's local update button does not update the NAS. Catalog definitions sync to managed clients every five minutes; see [REMOTE-GATEWAY.md](https://github.com/samaluk/CLIProxyAPI/blob/deployment/handy-personal-client/deployment/REMOTE-GATEWAY.md).
5. Preserve keys, account/session bindings, catalogs and aliases; verify both scopes and a tool continuation. Main Codex app/CLI/config/catalog changes remain the user's cutover step.

Mac rollback channels, not the NAS release mechanism:

- Core: `https://raw.githubusercontent.com/samaluk/CLIProxyAPI/reviewed-channel/core.json`
- Native plugins: `https://raw.githubusercontent.com/samaluk/CLIProxyAPI/reviewed-channel/plugins.json`

T3 and Pi remain stock installations. Their optional fork branches are reviewable contributions, not dependencies to install automatically. T3's OpenCode v2 catalog loader may accept a partial initial snapshot; do not downgrade OpenCode or replace T3 merely because this occurs. The shared launcher must preserve OpenCode server authentication variables for `serve` while stripping inherited account/config overrides.

## Central Synology deployment

Read [REMOTE-GATEWAY.md](https://github.com/samaluk/CLIProxyAPI/blob/deployment/handy-personal-client/deployment/REMOTE-GATEWAY.md) for the central catalog service and client sync installer, and [NAS-HANDOFF.md](NAS-HANDOFF.md) for credential cutover precautions. The homelab `easy-cli-proxy` stack owns the NAS deployment. The container recipe builds Linux amd64 libraries from the same Debian base, without AVX requirements. Build on another machine; keep the weak NAS for runtime.

An agent can start with:

> Clone `https://github.com/samaluk/CLIProxyAPI`, branch `deployment/handy-personal-client`. Read `deployment/THREAD-HANDOFF.md`, `deployment/README.md`, `deployment/stack.lock.json` and `deployment/NAS-HANDOFF.md`. Maintain the deployed Synology gateway using the existing homelab/Komodo conventions and Tailscale. Read `deployment/REMOTE-GATEWAY.md` before changing clients. Preserve account bindings and routing IDs; keep the NAS as the sole OAuth refresh owner. Verify each release before updating additional clients. Keep my main Codex configuration unchanged and give me its final cutover step.

Credentials, auth files, catalogs containing native prompts, binding state and GUI secrets are intentionally absent from this public repository. The handoff agent must use the existing private deployment or ask for the specific missing credential; it must not invent replacements.
