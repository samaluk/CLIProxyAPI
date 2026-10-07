# Proxy-only clients and shared settings

The gateway is the model source and the owner of upstream subscription/API credentials. Managed harnesses receive only their scoped downstream gateway key. Successful catalog snapshots remove saved routes that the proxy no longer advertises. Failed refreshes retain the last proxy catalog. These are configuration controls for ordinary launches, not an OS sandbox.

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

Codex uses file-based API authentication with `requires_openai_auth = true` and `forced_login_method = "api"`. The file contains the gateway key, not an upstream OpenAI key. This lets T3 identify the API-backed account and report native ChatGPT quota reads as unsupported instead of a failed native subscription probe. The provider URL and model catalog still point exclusively to the gateway.

## T3 HOME paths

T3's Codex `homePath` selects `CODEX_HOME`; Claude's selects `CLAUDE_CONFIG_DIR`. Keep these pointed at the corresponding existing scoped homes. They select configuration and history locations; they do not synchronize the contents. The installed Pi/OpenCode provider forms do not expose a comparable HOME field. Scoped wrappers still set their profile directories, sanitize inherited provider credentials and preserve child account routing. Do not replace a thread's home or history directory merely to change a display label.

## Shared settings and differences

`client-settings.json` is the reviewable, credential-free policy. Clients download data only and validate its fixed schema. The five-minute catalog job projects it into the existing native configuration formats and updates default homes. A failed or invalid policy download uses the last validated policy without preventing model exclusions from propagating.

`cpa-harness-settings` prints the policy and each harness's configured values and file location. Its report deliberately excludes credentials, arbitrary environment values, commands and prompts. The active cache is `<profiles>/shared-settings.json`; edit the canonical source, rather than that generated cache, when automatic remote sync is enabled. Review the JSON diff, commit it and update the selected data source. No harness binary reinstall is needed for a settings change.

The policy has a separate baseline for each harness. Comparison is **the same harness across machines and profiles**, not unlike controls between harnesses. Initial values preserve the existing main preferences: Codex/Claude effort is medium; Pi thinking is high with thinking hidden and automatic compaction disabled; Claude automatic compaction is disabled; OpenCode retains manual permissions, disabled sharing and manual updates. Account/model selection and machine-local paths remain scoped exceptions.

`cpa-harness-settings --ssh debian-dev` groups the local and remote Personal/Work configurations under each harness. Exported reports can also be combined with `--compare /path/to/report.json`. Differences from a harness's own baseline are listed as drift. Reports include configured values, not a claim about project/session overrides or runtime-equivalent behavior.

Codex's `agents.max_threads` is `null` in the baseline, preserving its current capacity choice. Set an integer from 1 to 64 to sync that Codex control across its profiles and machines. The installed Codex accepts that legacy alias; newer documentation names it `max_concurrent_threads_per_session`. Its initial `max_depth` is `2`, matching the pre-existing default-home preference. Native subagent limits and T3-owned delegated task limits are separate. Other harnesses retain their own settings schema and may gain additional reviewed settings later.

Permission grants, hooks, prompts and tools remain outside this narrow policy. A broader T3 UI should distinguish shared intent, verified per-version mappings, explicit overrides, project overrides and unsupported controls. Copying raw JSON/TOML values between harnesses is not evidence of equivalent behavior.

The policy adapter is covered by regression checks for removals, schema validation, failed fetches, credential/environment isolation and preservation of unrelated native settings. Offline machines still require the installer; native Windows scheduling remains a separate adapter or WSL installation.
