# Contributions and deployed forks

All seven source branches were rebased or confirmed current against their original upstream on October 4, 2026. Exact heads and upstream bases are in [stack.lock.json](stack.lock.json). Core targets upstream dev and includes upstream main. All other contributions target upstream main. Existing PR descriptions explain the problem, solution and validation; no closed PR was reopened.

| Component | What remains | Deployed | Review |
| --- | --- | --- | --- |
| CLIProxyAPI | Capability metadata/aliases, effort translation, policy errors, revision guards and finite alias cooldowns | Reviewed core | [Upstream draft #5801](https://github.com/router-for-me/CLIProxyAPI/pull/5801); [fork layers](https://github.com/samaluk/CLIProxyAPI/pulls) |
| EasyCLIProxyAPI | Canonical native catalog/template export, capabilities and speed tiers, monotonic reviewed core/plugin updates | Reviewed Mac app | [Upstream draft #255](https://github.com/router-for-me/EasyCLIProxyAPI/pull/255); [fork layers](https://github.com/samaluk/EasyCLIProxyAPI/pulls) |
| CommandCode | Provider capability metadata | Reviewed plugin, existing build unchanged | [Upstream draft #2](https://github.com/ahoo/cpa-plugin-commandcode/pull/2) |
| OpenCode Go | Catalog import, roles, Claude effort mapping, reasoning replay, version stamping, namespace collision validation | Updated reviewed plugin | [Previous PR #4, closed](https://github.com/massiveits/opencode-go-cliproxyapi/pull/4); six independent branches below |
| Account binding | Scope/source policy and structured errors | Reviewed plugin, existing build unchanged | [Upstream draft #1](https://github.com/FFatTiger/cpa-key-account-bind/pull/1); [fork review #1](https://github.com/samaluk/cpa-key-account-bind/pull/1) |
| Pi provider | Safe integer/capability contribution | Stock npm provider remains installed | [Upstream draft #32](https://github.com/router-for-me/pi-cliproxyapi-provider/pull/32) |
| T3 Code | Custom Codex capability authority and refresh | Stock Nightly remains installed | [Previous PR #11642, closed](https://github.com/pingdotgg/t3code/pull/11642) |

## Simplifications this sync

OpenCode Go upstream now supplies the streaming lifecycle and namespace executor that the fork previously carried. Those duplicate patches were retired. A narrow collision guard remains because distinct tool identities must not collapse to the same wire name. Reasoning replay was adapted to the new upstream event lifecycle.

Core's new Antigravity entitlement filtering, refresh revisions and epoch handling remain upstream-owned. The fork augments their metadata path rather than restoring the old registration lifecycle. A review regression fixed retained suspension deadlines so conditional refresh cannot make finite cooldowns permanent.

CommandCode and account-binding source commits were already current, so their published versions were retained. T3 and Pi forks remain optional. Do not install them just because they are listed in the lock.

## Separate OpenCode Go proposals

Each branch is based directly on upstream main, contains scoped commits and passed its focused adapter/catalog/config suites. These are ready for separate review; the closed aggregate PR is not the submission vehicle.

- [contribution/catalog-file](https://github.com/samaluk/opencode-go-cliproxyapi/tree/contribution/catalog-file)
- [contribution/harness-roles](https://github.com/samaluk/opencode-go-cliproxyapi/tree/contribution/harness-roles)
- [contribution/claude-effort](https://github.com/samaluk/opencode-go-cliproxyapi/tree/contribution/claude-effort)
- [contribution/reasoning-replay](https://github.com/samaluk/opencode-go-cliproxyapi/tree/contribution/reasoning-replay)
- [contribution/release-version](https://github.com/samaluk/opencode-go-cliproxyapi/tree/contribution/release-version)
- [contribution/namespace-collisions](https://github.com/samaluk/opencode-go-cliproxyapi/tree/contribution/namespace-collisions)

## Remaining contributions

1. Provider-first capability provenance and gateway account discovery described in [CAPABILITIES.md](CAPABILITIES.md). The current Mac account adapter should become portable upstream functionality.
2. T3 OpenCode v2 catalog readiness: the stock loader can accept an initial nonempty built-in snapshot before the configured provider loads. Temporary-server acceptance verifies eventual full catalogs, not the absence of this stock UI race. Isolate a small readiness change on current upstream before proposing it.
3. Upstream the remaining core, GUI and plugin behavior before replacing deployed forks with stock releases. Validate each replacement against the preserved regression suite; a newer version alone does not establish equivalence.
4. Remote client refresh for an explicit Tailscale HTTPS origin, preserving redirect rejection and scope keys. This is a NAS cutover prerequisite; the current Mac helper intentionally accepts loopback only.

## Validation and release limits

Core full Go tests, all native plugin tests/race/vet, synthetic core/plugin protocol checks, Easy's 732 passing Rust tests with 6 ignored, frontend typecheck/build, Pi's 179 tests and T3's 67 focused tests passed. Three Easy frontend failures also reproduce on clean upstream and remain recorded. Local passing tests are not a claim of upstream CI approval; the core PR has a maintainer-controlled translator-path guard.

Unique checksum-pinned core and OpenCode Go releases were published, the existing reviewed channel advanced monotonically, and the Mac stack installed and verified. A Linux amd64 image built and loaded all three native plugins in a local container with synthetic credentials. Synology DSM/kernel compatibility and real NAS load remain untested. No NAS migration or main Codex cutover occurred.
