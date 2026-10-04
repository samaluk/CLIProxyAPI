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

Add `--binary claude=...` or `--binary pi=...` when installed. Pi needs its stock
CPA provider package in the profile and Bun for its installed mapper. Reinstall
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
