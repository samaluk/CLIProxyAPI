# Repeatable sync

Use this prompt:

> Update my CPA stack using `samaluk/CLIProxyAPI` branch `deployment/gateway-stack` as the entry point. Read its deployment guide and lock. Inventory the running binaries and all source branches; preserve private state and create immutable backup refs. Fetch each original upstream, rebase the scoped contribution branches, resolve conflicts by preserving intent, and retire patches only when upstream behavior passes the regression tests. Core targets upstream dev and must contain the latest default main; all other repos target main. Keep contribution commits scoped and independent where possible. Review the final branches, fix findings, push with explicit old-head leases, and update existing PR descriptions using problem → solution → validation. Do not reopen closed PRs automatically. Build exact clean heads, publish unique checksum-pinned artifacts and advance existing reviewed channels with increasing revisions. Install through the existing reviewed management path while requests are idle, preserve accounts/bindings/aliases, verify catalogs and tool continuations for both scopes, and refresh the lock, contribution map and report with actual results. Do not change or restart my main Codex setup. Keep T3/Pi stock unless a demonstrated blocker requires a separately explained change. Base every capability decision on provider evidence, preferring authenticated account metadata. Ultrafast availability follows the account response; never add a hardcoded subscription rule. Report fallback fields and missing metadata explicitly. Leave the next NAS deployment reproducible from this fork without moving it now.

## Release gates

- Require clean source trees and record full commits, upstream refs, build tool versions and artifact hashes.
- Test core with `go test ./...`; compile `./cmd/server`. Run changed registry/auth/plugin packages with race detection where appropriate.
- OpenCode Go: `go test -tags debug ./...`, race, vet and release-mode C-shared build. Validate its C ABI registration/version and real core protocol fixtures. The other native plugins require Go tests, race, vet and C ABI registration.
- Easy: frozen frontend dependencies, typecheck/build, relevant frontend tests, Rust suite and a complete app build/signature check. Record reproducible upstream failures separately; never call a partially failing suite all-green.
- Pi: `npm ci && npm run check`. T3: frozen pnpm installation and focused Codex provider/registry tests. These are optional contribution verification, not instructions to replace stock apps.
- Keep stable registry source IDs. Keep old versions for rollback. Do not overwrite tags/assets or lower release revisions.
- Update software binaries without restoring old auth/session state. Rolling back credentials can invalidate newer refresh tokens and bindings.
- Compare capabilities by route, not catalog length alone. A provider outage or revoked auth must be reported separately from a binary regression.
- Keep the main Codex app, CLI, configuration and active catalog untouched throughout this task.

## Migration from the local lab

The Mac currently also has operational/client scripts under `~/dev/personal/cpa-capability-lab/scripts` and wrappers under `~/Library/Application Support/Agent Profiles`. Those are client-side state and tooling, not NAS runtime dependencies. Preserve the launchers and catalogs during NAS preparation. Their future endpoint cutover must explicitly support the chosen HTTPS Tailscale origin while keeping redirects disabled and scope-specific keys. The existing refresh helper accepts loopback origins only; do not claim a remote client cutover is ready until that validation is updated and tested.
