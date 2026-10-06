# Continue the gateway work in T3 Code

Reviewed October 6, 2026, America/Santiago. This is the entry point for a fresh conversation. The gateway is already deployed; continue maintenance rather than repeating the migration.

## Read these first

1. This handoff and README for the current architecture and constraints.
2. OPERATIONS for catalog updates, account recovery and cache behavior.
3. ACTIVE-STACK for the deployed inventory and dated evidence.
4. SYNC-RUNBOOK and UPSTREAM-CONTRIBUTIONS before a software update or PR.

Local canonical documents are in `~/dev/personal/cpa-capability-lab`. The lab is not a Git repository. The published guide is https://reports.malukzedan.synology.me/v/tg7uj5zuoueqhq4lb7fj5y3ec4/#handoff. Raw state and native prompts under `private/` are confidential.

## What runs where

The DS916+ NAS owns provider OAuth credentials, refresh tokens and account/session bindings. Tailscale Serve exposes `https://malukzedansyngy.tailcb5930.ts.net` to the tailnet. The homelab `easy-cli-proxy` Komodo stack runs two containers from the same pinned image:

- `easy-cli-proxy-core` routes inference and loads CommandCode, OpenCode Go and account-binding native plugins.
- `easy-cli-proxy-catalog` serves authenticated, scoped `/catalog/v1` and forwards HTTP, streaming and WebSocket traffic.

Both use `ghcr.io/samaluk/cpa-gateway:20261004-tailnet-1@sha256:0720c169031e11609fd3adf85d719b6cc498525e090c17480541e267d5955506`. Their private bind directory is `/volume1/docker/easy-cli-proxy/data`. Core can write credentials and bindings; the catalog mounts it read-only. Only the catalog publishes `127.0.0.1:8317`. Do not add public ports or Funnel.

The Mac Easy app/core is stopped for rollback, with automatic core startup disabled. Homebrew Caddy and launch agent `me.cpa.gateway-relay` relay old Mac `127.0.0.1:8317` connections to NAS HTTPS. Keep the relay. It owns no OAuth tokens.

Managed Mac profiles live in `~/Library/Application Support/Agent Profiles`. Debian dev profiles live in `~/.config/cpa/profiles`, reached through the existing `debian-dev` SSH alias. Profile keys are at `<scope>/keys/downstream.key`; a management key is a separate credential, not an inference key. Read keys in memory and never print or publish them.

All client executables remain stock. T3 has enabled Personal and Work instances for Codex, Claude Code, OpenCode and Pi. Stock OpenCode background services on Mac ports 49374 and 49375 avoid T3's initial catalog race. Native Pi definitions are scoped; the old combined-discovery extension and OpenCode V1 prompt loader are retired from managed profiles. The stock Pi mapper package remains installed for conversion. Cursor and Antigravity retain native T3 integrations and do not consume the CPA catalog.

## Source branches and ownership

The current client/deployment clone is `~/dev/personal/cpa-plugin-reviews/CLIProxyAPI-gateway-stack`, branch `deployment/litellm-catalog-labels`. Original client change `f5aca091` and repeated Pi label fix `7259f731` are included. Inspect the current branch head; later documentation commits do not change installed Python code. Fork draft #15 is based on `deployment/catalog-sync-diagnostics`, and depends on client drafts #9 through #14. Do not flatten or discard those layers while rebasing.

`deployment/gateway-stack` is an older integration branch and lacks the current remote installer and client fixes. It is not the fresh-clone entry point. `deployment/stack.lock.json` pins the seven reviewed component sources for the October 4 binary release, independently of the client-helper head. The last upstream rebase audit was October 4, not this documentation review. Recheck upstream before another release.

The other six clean review clones are under `~/dev/personal/cpa-plugin-reviews`. Historical `cpa-capability-lab/repos` trees are not authoritative build sources. T3 and Pi forks are optional contributions and are not deployed executable dependencies.

Homelab's current primary checkout may be on unrelated work and lack the `easy-cli-proxy` directory. Inspect `git worktree list` and remote main first. The CPA worktree is `~/dev/personal/homelab-worktrees/easy-cli-proxy`; deployed Compose is on homelab main. Never reset or switch an unrelated working tree. Read homelab AGENTS and Synology/Komodo skills before runtime work. Source image updates reach main through a PR, then Komodo deploys. Easy's desktop update button cannot update the NAS image.

## Current catalogs and capability policy

Live October 6 discovery returned 73 Personal and 44 Work routes. Work includes 25 LiteLLM deployments. The October 5 update added 17 and explicitly retired Luna Pro and DeepSeek V4 Flash 0731. OpenCode, native Pi and T3 Claude contain all 25 LiteLLM routes. Scoped Codex has 20.

Five LiteLLM routes lack exact trusted Codex prompt templates:

- `work/litellm/haiku-4.5`
- `work/litellm/sonnet-4.6`
- `work/litellm/deepseek-v4-pro`
- `work/litellm/deepseek-v4.1-flash`
- `work/litellm/deepseek-4.1-beta-test`

`work/claude-sonnet-5-5` separately lacks a template. Personal image routes `gpt-image-1.5` and `gpt-image-2` are deferred because native account discovery does not expose them. Do not invent templates or borrow another model's native instructions to force entries.

Routing IDs identify scope/source and stay stable. Labels use `P` or `W`, then `CX`, `CL`, `LL`, `GO` or `CC`, followed by a readable model. LiteLLM deployment names can conceal a changed backend. Several Claude-named routes now target GPT-6 Luna. The existing `work/litellm/gpt-5.6-luna` route remains addressable, but displays `W/LL · 6 Luna · via 5.6 Luna`. Its scoped Codex prompt was explicitly migrated to the exact trusted GPT-6 Luna prompt on October 5. Label refresh alone never rewrites prompts.

Use authenticated deployment/account metadata first. Exact backend metadata can supplement declared fields. Unknown fields remain reported fallbacks; explicitly empty effort/tier lists must remain empty. LiteLLM context/output limits and image support came from authenticated `/model/info`. Named reasoning efforts also require the accepted parameter and exact backend's published effort set. Qwen3 Coder has no declared reasoning. Generic speed-tier fields on Work LiteLLM are fallback evidence, not verified entitlement. Ultrafast support follows account discovery, never a hardcoded price or plan rule.

## How updates propagate

The NAS serves account-scoped snapshots. Mac launchd `me.cpa.catalog-sync` and Debian systemd user `me.cpa.catalog-sync.timer` apply them every five minutes. They retain the configured origin, separate keys and client schema conventions. `cpa-catalog-sync` previews; `cpa-catalog-sync --apply` applies. `cpa-catalog-refresh` is an installed alias. Inspect `sync-state/status.json`, not just command exit status.

Data refresh does not install helper code or client executables. Reinstall updated helpers from the reviewed branch with the existing origin/profile root and retain binary mappings. The installer remembers `pi_selector`, `t3_opencode_services`, `t3_pi_profiles`, `pi_native_catalog` and `t3_claude_profiles` opt-ins. T3 Claude menus refresh only for existing instances with the expected driver and scoped wrapper path. Pi inherits generated names on every later update; deliberate distinct custom names and other overrides remain intact.

The current NAS does not automatically poll LiteLLM `/model/info` and rewrite its configured source list. A team provider change requires authenticated upstream reconciliation in NAS config first, then downstream sync. Confirmed removals require private backup and explicit retirement on each client. Ordinary missing discovery retains saved IDs because it can be a temporary outage. Do not silently reroute retired IDs to a different source/model.

OpenCode services reload changed definitions without terminating existing sessions. T3 may need Settings, Providers, Refresh provider status to update its picker. Other running clients can require an idle reload or new session. Do not kill live threads for a catalog update.

## First checks in a new conversation

Start read-only. Do not run a full rebase, deployment or restart just because this handoff was opened.

- Check source branch/head, worktree changes and the October 4 lock.
- Preview `cpa-catalog-sync` with the installed stable Python 3.11+ wrapper. On Mac use `/opt/homebrew/bin/python3` for source scripts, not the old system interpreter missing `tomllib`.
- Check scoped status receipts, sync age, missing templates and private `sync-state/diagnostics/*-failure.json`. Successful status is retained after a failure, so also inspect newer diagnostic timestamps. Never print arbitrary exception bodies or credentials.
- Run `deployment/mac/scripts/check_opencode_efforts.py` from the current clone to compare the two running Mac services without inference.
- Check NAS Docker health through the Synology skill. Use Komodo for restarts or releases. Reuse existing SSH configuration; inspect the active Tailscale address before using an old address.
- Read PRs through `pr-cockpit owner/repo#N`. If progress depends on CI, comments or reviews changing, use `pr-cockpit listen`; cached October snapshots are not current approval. Do not reopen closed PRs automatically.

## Review result and acceptance limits

The October 6 Standards review found no actionable documented-standard breaches. The behavioral review found one repeated Pi label bug, fixed in `7259f731` and rereviewed. All 43 focused helper tests passed. Mac and Debian helpers were reinstalled. Runtime modules matched reviewed source, both NAS containers were healthy, all 117 OpenCode effort sets matched gateway evidence, and native Pi registrations contained no foreign routes. Eight scoped T3 instances were enabled. Scheduled sync remained active.

October 5, not this handoff review, provides the latest Work Sol 6.1 and Qwen3 tool continuations, successful stock Codex/Claude CLI requests and Work-key-to-Personal HTTP 403 check. The NAS cutover and previous model tests are dated evidence. This review sent no new inference and did not visually retest the phone or all saved threads. No latest-upstream rebase or new container release occurred.

Keep the user's current main Codex app, CLI, configuration and active catalog untouched, even after moving this discussion to T3. Main config has changed since the October 5 backup outside this refresh history; never restore an older receipt over current user state. Installed helpers separately guard main Codex. This handoff does not authorize a main Codex cutover.

## Remaining work, in priority order

1. Work Claude OAuth still needs reauthentication after `invalid_grant`. The remote browser callback uses the management page's Callback URL field, because localhost:54545 is on the browser machine. Verify Work binding on the new auth file before inference.
2. Obtain exact trusted prompts for deferred Codex models, or explicitly keep them unavailable. Preserve native prompt identity.
3. Automate authenticated LiteLLM source reconciliation and explicit retirement distribution, with preview, scoped backup and rollback. The current downstream timer alone does not cover this step.
4. Fix core atomic-file replacement reload upstream. The October 5 atomic config write changed the inode and the watcher missed it. A controlled Komodo core-only restart loaded it. Use the management configuration flow or plan an idle core reload until parent-directory reattachment is implemented.
5. Track provider capability provenance per field, especially Work speed-tier fallbacks and ambiguous shared accounts. Do not claim full same-user filesystem, plugin endpoint or subagent isolation from the scope checks alone.
6. Upstream the generic client/schema changes and remaining core/plugin contributions. Keep NAS packaging and personal account configuration separate. The closed aggregate Go and T3 PRs need separately scoped proposals, not automatic reopening.
7. Migrate and accept offline Omarchy/Windows/xinetraider64lt clients. Native Windows scheduling is not implemented; WSL is supported. Verify mobile saved-thread UI and concurrent NAS load.
8. Historical intermittent catalog ValueErrors remain unproven. Use new private diagnostics on recurrence rather than assigning a cause to an old generic log line.

## Paste into the new T3 Code thread

```text
Continue maintenance of my shared CPA gateway setup. First read ~/dev/personal/cpa-capability-lab/docs/THREAD-HANDOFF.md, then its README, ACTIVE-STACK.md, docs/OPERATIONS.md and UPSTREAM-CONTRIBUTIONS.md. The current source clone is ~/dev/personal/cpa-plugin-reviews/CLIProxyAPI-gateway-stack on deployment/litellm-catalog-labels, including repeated Pi label fix 7259f731. Read deployment/THREAD-HANDOFF.md there if the lab is unavailable. Start with read-only validation and report any drift before changing things. The single NAS gateway is already deployed, managed clients refresh every five minutes, and all client executables stay stock. Preserve Personal/Work keys, homes, native prompts, route IDs, bindings and the Mac localhost Caddy relay. Keep the NAS as the sole OAuth refresh owner. Do not change or restart my main Codex app, CLI, configuration or catalog, and do not restore old credential snapshots. Base capabilities on provider evidence. Keep confirmed model retirement separate from transient outages. Read PR state using PR Cockpit and wait with pr-cockpit listen when required. Continue from the documented open work or my next instruction; opening this handoff alone is not a request to redeploy or rebase the stack.
```
