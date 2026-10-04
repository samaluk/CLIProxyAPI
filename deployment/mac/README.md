# Mac client and update helpers

These are the maintained operational helpers previously kept only in the local capability lab. They require Python 3.12+ and the existing private Agent Profiles layout; they do not create or publish credentials. Use an explicit compatible interpreter if the shell's `python3` is older.

Their reports and private backups default to `~/.local/state/cpa-stack`; set `CPA_STATE_DIR` to an existing lab directory to preserve its history. Before first use, create `artifacts/update-2026-09-20` and `private` beneath that state directory with private permissions. The historical default report subdirectory is retained for compatibility.

- `scripts/refresh_scoped_catalogs.py` previews, then `--apply` updates scoped catalogs. `--standardize-names` also reconciles local labels. Main Codex configuration and its active catalog are protected. The helper currently accepts loopback gateway origins; NAS HTTPS client cutover is a separate adaptation/test step.
- `scripts/standardize_model_names.py` changes names only, preserving routing and capabilities.
- `scripts/check_t3_opencode.py` checks authenticated temporary OpenCode v2 servers through the existing scoped wrappers. It does not create conversations or send model prompts.
- `scripts/deploy_reviewed_stack.py --help` stages/verifies a Mac app/core pair and defaults to a plan. Supply all required hashes/heads and `--app-source`. `--execute` checks for active requests, backs up privately and restores previous binaries if validation fails, without restoring stale auth/session state.
- `scripts/install_reviewed_plugins.py --help` installs pinned versions serially through the management plugin store and checks scope bindings/configuration remain unchanged.

The refresh helper authenticates read-only model discovery with the existing native Codex account, verifies its account ID against the gateway credential, and applies structured capabilities only to its explicitly mapped routes. It never refreshes tokens or modifies native Codex state. Account metadata overrides generic proxy fields; missing discovery defers that account's routes while preserving saved entries. Other scopes can still refresh. The report lists authenticated fields, proxy fields and deferred routes. No local plan, price or ultrafast deny policy is used.

This adapter currently needs the Mac GUI credential layout and a matching native Codex login. A NAS deployment must supply equivalent account-bound discovery at the gateway; copying this Mac helper alone does not implement remote discovery. See [CAPABILITIES.md](../CAPABILITIES.md).

Run helper regressions with `python3 -m unittest discover -s deployment/mac/scripts -p 'test_*.py'`. Some imported historical tests expect their original lab fixtures; record any missing fixture separately from a product failure.
