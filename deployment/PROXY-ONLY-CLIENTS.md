# Proxy-only clients and shared settings

The gateway is the model source and owns the credentials used for proxy inference. Managed model requests use scoped downstream gateway keys. Personal Codex can retain a separate native ChatGPT login for subscription usage displays. Successful catalog snapshots remove saved routes that the proxy no longer advertises. Failed refreshes retain the last proxy catalog. These are configuration controls for ordinary launches, not an OS sandbox.

## Install the native tools

Run from a reviewed checkout on each Mac or Linux machine with mise and Python 3.11+ installed. Install Codex, Claude Code, Pi and Cursor Agent through the shared mise manifest. Install OpenCode 2 through its official bare installer, pinned to the stable version used by the T3 services. Install Antigravity through T3's provider setup.

```sh
mkdir -p ~/.config/mise/conf.d
cp deployment/harnesses.mise.toml ~/.config/mise/conf.d/cpa-harnesses.toml
mise trust ~/.config/mise/conf.d/cpa-harnesses.toml
mise install codex@0.160.1 claude-code@2.1.292 pi@1.0.4 \
  cursor-agent@2026.10.01-e373342
curl -fsSL https://opencode.ai/v2/install -o /tmp/cpa-opencode2-install.sh
bash /tmp/cpa-opencode2-install.sh --version 2.0.24 --no-modify-path
~/.opencode/bin/opencode --version
```

The result must be `opencode v2.0.24`. The `/install` URL and mise's `opencode` entry install OpenCode 1. The old `@opencode-ai/cli` prerelease lacks the service `reload` command required here. Do not select it for these profiles. Existing unused installations can remain while a process still owns them.

Antigravity's standalone mise installation passed protocol initialization but failed practical use in T3. Keep its Binary path empty and use T3's Install and Sign in controls. The user's working Debian T3 installation replaces the retired mise copy. Native Antigravity account configuration remains a private, machine-local exception.

On an existing CPA client, seed any missing harness configurations and register the installed native paths. This requires the machine's existing Personal/Work downstream keys. It does not copy upstream credentials or histories.

```sh
profiles=/absolute/path/to/profiles
endpoint=https://YOUR-GATEWAY.YOUR-TAILNET.ts.net
codex_native="$(mise where codex@0.160.1)/bin/codex"
claude_native="$(mise where claude-code@2.1.292)/claude"
pi_native="$(mise where pi@1.0.4)/pi/pi"
python3 deployment/mac/scripts/provision_harness_profiles.py \
  --profiles "$profiles" --endpoint "$endpoint" --apply \
  --binary "codex=$codex_native" --binary "claude=$claude_native" \
  --binary "pi=$pi_native" --binary "opencode=$HOME/.opencode/bin/opencode"
python3 deployment/mac/scripts/install_remote_sync.py \
  --profiles "$profiles" --endpoint "$endpoint" --proxy-only \
  --binary "codex=$codex_native" --binary "claude=$claude_native" \
  --binary "pi=$pi_native" --binary "opencode=$HOME/.opencode/bin/opencode" \
  --shared-settings-url https://raw.githubusercontent.com/samaluk/CLIProxyAPI/deployment/proxy-authoritative-clients/deployment/client-settings.json
cpa-catalog-sync --apply
```

Mac uses `/Users/smaluk/Library/Application Support/Agent Profiles`; Debian uses `/home/smaluk/.config/cpa/profiles`. Keep the proxy command directory `~/.config/cpa/bin` first on PATH. `--no-modify-path` prevents the bare installer from placing its native binary ahead of those commands. Native Cursor and Antigravity keep their own account authentication. Registering a new T3 provider instance is separate from installing its CLI.

The same procedure is ready for offline Mac/Linux clients when they return. Native Windows still needs a scheduling adapter; the current proxy client installer works inside WSL.

## Register T3 providers

After the proxy client has created both scoped wrappers, register Personal/Work instances for Codex, Claude, OpenCode and Pi. Existing scoped homes and instance customizations are preserved. An unexpected wrapper or HOME stops the operation rather than moving histories. The helper enables native Cursor and T3-managed Antigravity as the agreed exceptions, without copying OAuth tokens or credentials into the shared policy.

```sh
python3 deployment/mac/scripts/configure_t3_providers.py \
  --profiles "$profiles" \
  --cursor-binary "$(mise where cursor-agent@2026.10.01-e373342)/dist-package/cursor-agent" \
  --t3-antigravity --apply
python3 deployment/mac/scripts/install_remote_sync.py \
  --profiles "$profiles" --endpoint "$endpoint" --proxy-only \
  --t3-pi-profiles --t3-opencode-services
cpa-catalog-sync --apply
```

T3's file watcher loads the instance definitions. Its provider model caches require an explicit provider refresh after replacing a binary behind an unchanged wrapper. Refresh the affected provider in T3 before reviewing its model menu. OpenCode's service connections are loopback-only and retain their existing passwords. Claude custom menus update with the scheduled scoped catalog job. Existing T3 userdata symlinks resolve to their current storage target, while writes retain ownership and concurrent-edit checks.

Use T3's native login for Cursor and Personal Antigravity on each machine. Native Work Antigravity uses its Agent Platform configuration. During the October 7 setup, Debian received the user's existing Work API configuration privately over SSH. Those credentials are excluded from shared settings and comparison reports. Cursor inside Pi remains Personal-only on the Mac that already owns its SDK login; no Cursor login is copied to Work Pi or to a new machine.

## Update an existing proxy client

Install on an existing managed Mac or Linux client with its real profile root and gateway origin:

```sh
python3 deployment/mac/scripts/install_remote_sync.py \
  --profiles /absolute/path/to/profiles \
  --endpoint https://YOUR-GATEWAY.YOUR-TAILNET.ts.net \
  --proxy-only \
  --shared-settings-url https://YOUR-REVIEWED-DATA-SOURCE/client-settings.json
cpa-catalog-sync --apply
```

Existing binary paths and opt-ins are retained. On a Mac that already has the Cursor SDK installed for Pi, add `--cursor-pi-personal`. Cursor remains available in Personal Pi only; Work Pi has neither its credential nor its extension. Native Cursor and Antigravity instances are unchanged.

Ordinary `codex`, `claude`, `opencode` and `pi` commands use Personal. Explicit `*-work` commands use Work. Children inherit their parent's `AGENT_PROFILE`. No account question is shown. The installer updates default homes as well as scoped homes, preserving histories, hooks and unrelated settings. Old auth/config files are privately backed up; provider access keys in active harness auth files are replaced by gateway keys. On macOS the native Claude keychain login is also privately archived before retirement, with a second read to guard against concurrent refresh. Nothing revokes an upstream account or restores an old OAuth refresh token.

API-only Codex profiles use file-based API authentication with `requires_openai_auth = true` and `forced_login_method = "api"`. Their auth file contains the gateway key. This lets T3 identify the API-backed account and report native ChatGPT quota reads as unsupported. The provider URL and model catalog point exclusively to the gateway.

## Native Codex subscription usage

The API-only migration removed native ChatGPT OAuth from the default and scoped Codex homes. That also removed the subscription identity required by Codex Desktop, T3's native Codex quota probe and CodexBar's OAuth source. A downstream gateway key cannot provide that native account identity.

On a machine needing native Personal usage, add `--codex-native-usage` to the proxy-only installer. The opt-in persists in that machine's private `gateway.json`. It stops replacing the default Personal and scoped Personal `auth.json` files, removes forced API login, and stores the scoped gateway bearer on the selected CPA model provider. `requires_openai_auth` stays true so Codex exposes its native account to usage clients. Inference still goes to the gateway using its key. Work and other harnesses retain their existing proxy-only authentication.

Sign in freshly for the default Codex Desktop home and run `codex-personal login` for T3's existing Personal home. Each home owns its own native login; OAuth refresh tokens are not copied between homes, machines or the NAS. T3 keeps its existing-instance mode and scoped launcher. Its separate managed token-sharing setup selects its own OpenAI provider, so use the scoped CLI for this proxy-backed instance. CodexBar normally reads the default `~/.codex` login, unless its process has an explicit `CODEX_HOME`. Archived OAuth tokens remain retired. The NAS keeps its current upstream login and inference remains proxied.

Native usage credentials remain private and outside shared settings or Git. The opt-in permits Personal `codex login` for this purpose. Subscription quota is distinct from gateway request/token usage, and it belongs to the signed-in ChatGPT account even when the proxy can route to additional accounts or providers.

## T3 HOME paths

T3's Codex `homePath` selects `CODEX_HOME`; Claude's selects `CLAUDE_CONFIG_DIR`. Keep these pointed at the corresponding existing scoped homes. They select configuration and history locations; they do not synchronize the contents. The installed Pi/OpenCode provider forms do not expose a comparable HOME field. Scoped wrappers still set their profile directories, sanitize inherited provider credentials and preserve child account routing. Do not replace a thread's home or history directory merely to change a display label.

## Shared settings and differences

`client-settings.json` is the reviewable, credential-free policy. Clients download data only and validate its fixed schema. The five-minute catalog job projects it into the existing native configuration formats and updates default homes. A failed or invalid policy download uses the last validated policy without preventing model exclusions from propagating.

`cpa-harness-settings` prints the policy and each harness's configured values and file location. Its report deliberately excludes credentials, arbitrary environment values, commands and prompts. The active cache is `<profiles>/shared-settings.json`; edit the canonical source, rather than that generated cache, when automatic remote sync is enabled. Review the JSON diff, commit it and update the selected data source. No harness binary reinstall is needed for a settings change.

The policy has a separate baseline for each harness. Comparison is **the same harness across machines and profiles**, not unlike controls between harnesses. Initial values preserve the existing main preferences: Codex/Claude effort is medium; Pi thinking is high with thinking hidden and automatic compaction disabled; Claude automatic compaction is disabled; OpenCode retains manual permissions, disabled sharing and manual updates. Account/model selection and machine-local paths remain scoped exceptions.

`cpa-harness-settings --ssh debian-dev` groups the local and remote Personal/Work configurations under each harness. Exported reports can also be combined with `--compare /path/to/report.json`. Differences from a harness's own baseline are listed as drift. Reports include configured values, not a claim about project/session overrides or runtime-equivalent behavior.

Codex's `agents.max_concurrent_threads_per_session` is `15` in the baseline. This allows fifteen concurrent native subagents per session, excluding the primary agent. Set an integer from 1 to 64 to sync that Codex control across its profiles and machines. `max_threads` is a legacy alias for the same field. Writing both makes Codex Desktop reject the configuration; the adapter migrates older policies and removes that alias from managed configs. Its `max_depth` is `2`, matching the pre-existing default-home preference. Native subagent limits and T3-owned delegated task limits are separate. Other harnesses retain their own settings schema and may gain additional reviewed settings later.

For this deployment, edit `deployment/client-settings.json` on branch `deployment/proxy-authoritative-clients` in `samaluk/CLIProxyAPI`. Review the diff, commit and push that file. Every managed client fetches its raw JSON URL every five minutes. Run `cpa-catalog-sync --apply` on a client to apply it immediately. Native config files and `<profiles>/shared-settings.json` are generated copies; edits to their managed fields will be replaced by the next sync. Start a new native session to load a changed capacity limit.

Permission grants, hooks, prompts and tools remain outside this narrow policy. A broader T3 UI should distinguish shared intent, verified per-version mappings, explicit overrides, project overrides and unsupported controls. Copying raw JSON/TOML values between harnesses is not evidence of equivalent behavior.

The policy adapter is covered by regression checks for removals, schema validation, failed fetches, credential/environment isolation and preservation of unrelated native settings. Offline machines still require the installer; native Windows scheduling remains a separate adapter or WSL installation.
