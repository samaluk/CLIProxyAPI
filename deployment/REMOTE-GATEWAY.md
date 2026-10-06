# One gateway, several clients

The NAS owns provider credentials, refreshes OAuth tokens and routes inference.
Clients keep only their scoped downstream keys and model definitions. Moving the
API server alone would leave model catalogs stale on every client, so the
container also serves an authenticated catalog at `/catalog/v1`.

```text
T3 / scoped Codex, Claude Code, OpenCode, Pi
  -> Tailscale HTTPS origin
     -> catalog service: /catalog/v1
     -> CLIProxyAPI: /v1/*, /v1/messages, management UI
        -> existing subscriptions and API accounts
```

The catalog service exports only the routes for the requesting personal or work
key. For Codex OAuth it reads the matched account's official model discovery,
which outranks generic proxy metadata. It preserves explicitly empty effort or
speed lists and does not infer entitlements from prices or plan names. A route
shared by multiple accounts is deferred because its account capability set is
ambiguous. Other providers use the gateway's route metadata. Missing fields keep
saved client fallbacks; they are not evidence of an entitlement.

Native prompt templates are separate from capability data. An administrator
provisions `trusted-templates.json` privately. Clients explicitly trust that file
through the installed gateway configuration; generic proxy prose never replaces
native instructions. New Codex entries require an exact canonical template.
Models missing provider discovery or a trusted template remain in the sync
receipt for follow-up. Register newly released models on the verified account
in the gateway first. Catalog refresh does not invent routes.

## Install on a client

Requires Python 3.11 or newer, Tailscale connectivity, installed harness binaries
and private scoped profiles. macOS uses
`~/Library/Application Support/Agent Profiles`; Linux/WSL can use
`~/.config/cpa/profiles`. Never copy Mac binary paths into a Linux configuration.
Provision each scope with `keys/downstream.key` and the harness configuration
files it uses. Keep work keys only on machines authorized for work.

From this fork, run the installer with the actual absolute paths on that host:

```sh
python3 deployment/mac/scripts/install_remote_sync.py \
  --profiles "$HOME/.config/cpa/profiles" \
  --endpoint https://YOUR-NAS.YOUR-TAILNET.ts.net \
  --binary codex=/absolute/path/to/codex \
  --binary opencode=/absolute/path/to/opencode
cpa-catalog-sync --apply
```

Add `--binary claude=...` or `--binary pi=...` when installed. Pi uses the scoped native catalog when installed with `--t3-pi-profiles`. Keep its stock
CPA mapper package and Bun for capability conversion, but retire the old combined-discovery extension from managed profile package lists. Reinstall
with no binary flags to retain existing paths. The installer copies reviewed
Python helpers locally; each refresh downloads model data only. It never
executes gateway-supplied scripts or changes client binaries.

It installs `codex-personal`, `codex-work` and equivalent wrappers for the
configured harnesses, plus each profile's child-process wrappers. Existing T3
instances can keep using those wrapper paths. The shared launcher reads one
`gateway.json` origin. Existing CPA provider IDs stay unchanged so saved threads
can resume. Native `~/.codex/config.toml` and its active catalog are protected;
changing the coordinating Codex app remains a separate cutover step.

The installer adds a five-minute launchd job on macOS or a systemd user timer on
Linux. Use `--no-schedule` for staging. Linux user timers require a running user
manager; enable lingering administratively if updates must continue after
logout. Native Windows installation is not yet implemented; use WSL or finish a
Task Scheduler adapter before claiming that machine is migrated.

## What updates propagate

`cpa-catalog-sync` previews; `cpa-catalog-sync --apply` reconciles existing scoped
files. The former `cpa-catalog-refresh` command uses this same path after install.
A change to model limits, input/output types, efforts, supported runtime flags
or speed tiers updates each supported client schema. Model IDs, user defaults
where still valid, saved prompts and temporarily missing models remain intact.
Labels use the shared short naming rules. Claude reads limits from the scoped
catalog through its launcher. OpenCode and Pi receive their own schemas.

T3 and long-running harness processes may cache a catalog. Reload that provider
or start a new process to see new definitions. Sync does not terminate live
threads. The stock T3 initial OpenCode catalog race remains a separate upstream
issue; automatic file propagation does not fix that loader.

The server caches discovery for one minute and clients use conditional ETags.
Client caches are bound to the origin, scope and downstream key. HTTP failures,
redirects, invalid/empty catalogs, wrong-scope routes and concurrent file edits
fail closed. Saved files remain available. `sync-state/status.json` records the
last successful run, revision, deferred routes and missing templates. Scheduler
logs record failed runs. Backups and installation restore manifests stay private
under `sync-state/`.

## Software releases and rollback

Use the image build in `deployment/Dockerfile` and `stack.lock.json`. Publish a
unique version and digest, update both services in the homelab Compose file in
one PR, then let Komodo deploy from main. Core and native plugins must always
come from the same reviewed image. Catalog updates need no image reinstall;
code, plugin or capability-mapping changes do.

Do not deploy the Mac plugin store's dylib entries into the Linux image. Easy's
local update button does not manage the NAS container lifecycle. Use the NAS
management UI for account/model configuration and the homelab PR for software.

Before OAuth cutover, stop the old core and transfer the final credential and
binding state privately. Never run two refresh owners. Keep current state when
rolling back software. If moving ownership back to the Mac, first stop the NAS
and copy its newest auth/bindings back. Preserve aliases and downstream keys.

## Existing Mac localhost connections

A loopback Caddy relay preserves older clients and saved CPA provider connections at `http://127.0.0.1:8317`. It forwards to the NAS HTTPS origin with certificate validation and immediate streaming flush. It stores no OAuth credentials and does not refresh them. Managed scoped profiles use NAS HTTPS directly. Native main Codex configuration and its model catalog are not rewritten.

The deployed Mac uses the Homebrew Caddy executable, `Agent Profiles/compatibility.Caddyfile`, and launch agent `me.cpa.gateway-relay`. The listener binds only to 127.0.0.1, the Caddy admin endpoint is off, and the upstream Host header matches the NAS certificate. Synology SSH forwarding is disabled, so this relay does not depend on an SSH tunnel or an sshd policy change.

Keep Easy's `start-core-on-launch` disabled while the NAS owns refresh. A local core would also compete for port 8317. To roll back ownership, stop the NAS, transfer its latest credentials and bindings privately, stop the compatibility relay, and only then start the old core.

## October 4 acceptance and remaining work

Both NAS containers are healthy. Personal Codex OAuth and Work LiteLLM passed streamed tool calls and continuations. Cross-scope requests returned 403; an unauthenticated catalog request returned 401. Codex, Claude Code, OpenCode and Pi managed Mac launchers completed inference through the NAS; Debian's scoped Codex launcher did too. The management page and authenticated localhost relay returned 200. Mac launchd and Debian systemd user timers are installed.

The Work Claude credential returns `invalid_grant` and requires account reauthentication. Two Personal image routes are absent from native account discovery, and Work DeepSeek v4.1 Flash lacks a trusted Codex prompt template; sync reports these without inventing definitions. Offline computers still need client installation and acceptance. Native Windows scheduling remains unimplemented. Cursor and Antigravity retain native T3 paths. T3/mobile saved-thread UI and concurrent NAS load have not been revalidated by these CLI checks.

## Pi account selection on a shared machine

Install with `--pi-selector` to add `~/.local/bin/pi`. Keep the native Pi executable in `gateway.json`; do not set that binary path to the selector. The installer remembers this opt-in across later helper updates. Put `~/.local/bin` before the package-manager Pi entry in PATH and run `rehash` in existing zsh terminals if needed.

- `pi` asks Personal or Work before starting. It cancels on an empty answer.
- `pi personal` / `pi work` and `pi-personal` / `pi-work` open the selected profile directly.
- Children inherit `AGENT_PROFILE`, so an ordinary child `pi` uses its parent's profile. Unscoped noninteractive calls stop and require a choice.
- Each profile has its own Pi directory, auth, settings and sessions. The legacy `~/.pi/agent` home remains available on disk; mixed historical sessions are not automatically assigned to an account.
- The launcher sets the selected gateway origin/key and clears inherited `CLIPROXYAPI_*` overrides. This prevents provider environment precedence from silently selecting the other account.

Set each profile's stock `enabledModels` to its preferred exact model followed by `cliproxyapi/personal/**` or `cliproxyapi/work/**`. Pi opens its model picker in scoped mode and limits normal cycling to that set. Its explicit all-models view can still display names from legacy combined discovery; the gateway enforces authorization with the selected key. This is ordinary profile separation, not a same-user filesystem sandbox.

On the migrated Mac, Personal keeps its existing OpenCode Go GLM 5.3 Flash default. Work uses Work LiteLLM GPT-5.6 Luna while Work Claude requires reauthentication. Changing a picker default may also require moving that exact ID to the front of `enabledModels`, because Pi prioritizes the first scoped model on a new session.

## T3 model discovery with stock OpenCode 2

T3 can cache OpenCode 2's initial built-in catalog before configured providers finish loading. This is tracked by [T3 issue #15155](https://github.com/pingdotgg/t3code/issues/15155). A completed CLI or API catalog does not prove that T3's picker loaded it.

On the Mac, the opt-in `--t3-opencode-services` installer option connects the existing scoped T3 instances to stock OpenCode background services. Personal uses loopback port 49374 and Work uses 49375, with separate profile directories and existing service passwords. These local services run the harness; inference still goes through the single NAS gateway. Neither T3 nor OpenCode is patched by this workaround.

The installer remembers the opt-in. `cpa-catalog-sync --apply` and its five-minute scheduled invocation start missing services, wait for the expected scoped catalog, then reconcile only those two T3 connections. When the OpenCode definition file changes, stock `reload` refreshes loaded locations without terminating running sessions. Successful definition hashes are recorded only after both profiles pass, so a failed reload remains pending on the next run. Existing T3 settings are backed up privately before a connection change; other providers and saved custom models are preserved.

Both Personal and Work profiles and matching `opencode_personal` / `opencode_work` T3 instances must already exist. The helper fails instead of modifying an unrelated instance or moving a running service from another port. For a binary update, update stock OpenCode normally, then restart each scoped service during an idle window with `opencode-personal service restart` and `opencode-work service restart`, and run catalog sync. T3's own binary update button updates the CLI, not an already-running external service.

October 4 validation: OpenCode 2.0.22 returned 106 Personal and 29 Work configured models. The stock T3 nightly picker displayed gateway models for both accounts after the connection change. Remove this workaround only after #15155 is fixed and a fresh T3-managed server discovers the complete catalog for both profiles.

## OpenCode 2 reasoning variants

OpenCode 2.0.22 imports V1 `variants` objects but exposes entries marked `disabled: true` through `/api/model`. T3 then lists those disabled levels in its effort picker. This is separate from T3's initial model discovery race above.

The sync helper detects the installed OpenCode version before rendering its managed provider. OpenCode 1 retains disabled entries to suppress generated defaults. OpenCode 2 receives only enabled variants; known effort levels come from the scoped gateway's `supported_reasoning_levels`, including an explicit empty list. Unknown metadata retains enabled local definitions. Verified compatibility aliases are refreshed from the same canonical route, while unrelated saved routes and user options remain intact. Unsupported versions fail before the catalog transaction.

On October 5, all 73 Personal and 29 Work routes matched the gateway evidence in the stock OpenCode 2 API after applying this repair. T3's refreshed DeepSeek V4.1 Flash picker displayed only Low, Medium and High, matching that CommandCode route's published metadata. The main Codex configuration was untouched. No matching OpenCode issue was found in the issue search; an upstream report should cover V1 disabled-variant import compatibility, not request hardcoded model effort rules.

After a sync, T3 may retain an older model list until its next provider health check. Use **Settings → Providers → Refresh provider status** to refresh it immediately. `deployment/mac/scripts/check_opencode_efforts.py` checks both running Mac services against cached gateway evidence without sending inference requests. Stock T3 and OpenCode do not need patches for this configuration workaround.

## Retired OpenCode V1 prompt loader

The local `cpa-prompt-identity.js` workaround corrected OpenCode 1's substring-based selection of a Codex prompt for ordinary GPT routes containing `codex-oauth`. Its V1 hook function is not a valid OpenCode 2 plugin definition and causes a server plugin error.

OpenCode 2.0.22's [stock OpenAI prompt selector](https://github.com/anomalyco/opencode/blob/v2.0.22/packages/core/src/plugin/optimize.ts) now chooses the GPT or Astra prompt using `gpt` and `astra` in the model ID. The old correction is unnecessary and is retired rather than ported. Native custom-agent prompt handling remains intact.

When installed against stock OpenCode 2, the client installer archives only unchanged owned loaders in the Personal and Work profiles. It also handles the global loader when the global command resolves to the same binary. Loader contents and all imported legacy helper/prompt files must match their ownership fingerprints; customized files, other plugins and V1 installations are retained. Removal participates in the private backup transaction, including concurrent-edit detection and rollback on failed activation. The source workaround remains in the lab for V1 rollback, outside OpenCode's discovery directories.

October 5 validation: the previously failing loader disappeared from the global, Personal and Work server plugin-status APIs. All plugins settled with zero failures at both the home directory and the current workspace; the native OpenAI prompt plugin remained active. The main Codex configuration, gateway authentication and NAS deployment were unchanged. No upstream OpenCode patch is needed for this retirement because the new plugin API is an intentional V2 migration requirement.
