# Reviewed CPA update channel

This channel keeps reviewed model-catalog and account-routing changes available while their upstream contributions are open. It is a fork distribution, not an official release.

Configure EasyCLIProxyAPI's Reviewed core channel with:

`https://raw.githubusercontent.com/samaluk/CLIProxyAPI/reviewed-channel/core.json`

Add this native plugin store source once:

`https://raw.githubusercontent.com/samaluk/CLIProxyAPI/reviewed-channel/plugins.json`

The manifest pins the core repository, source commit, tag, archive size and SHA-256. The plugin registry uses direct artifacts with exact versions, hashes and sizes. Every build has a unique version. GitHub does not enforce release immutability here, so never replace the bytes of a published version. Advancing this branch advertises another tested release. The GUI keeps configuration/auth/plugins when updating core and restores its previous binary if startup or catalog/plugin health checks fail.

The matching reviewed GUI and core enforce release ordering. Core manifests and direct plugin releases include positive `revision` values. A changed automatic update must have a strictly newer revision; a stale or unproven candidate is rejected. The GUI sends `upgrade_only: true` for plugin updates. Explicit management installs without that flag retain rollback behavior. A same-version reinstall may seed a missing plugin revision only when its source and platform artifact checksum match the installed release. This setup has completed that migration.

Existing hand-installed plugins need a one-time source migration that preserves their settings and binding state. Do not uninstall the binding plugin to bypass a source conflict. Later updates use the same source identity through the normal plugin store.

Only macOS arm64 is advertised by this channel. Pi uses the stock npm package pinned in `stack.json`. T3 and the harness applications remain on their vendor channels. Main Codex configuration remains separately managed.

The reviewed Easy app currently needs a local build; its existing signature and Gatekeeper requirements remain enabled. Selecting this core channel protects the locally patched app from an accidental official self-update.

## Advancing the channel

Fetch upstream, preserve immutable backup tags, rebase scoped contribution branches, and remove patches superseded by stock releases. Run focused regression tests and independent review. Build from clean commits with honest version metadata. Publish each exact artifact to a new release, verify the downloaded bytes, then update the manifests together. Give each changed release a strictly increasing revision, no larger than 9007199254740991. This channel uses release publication timestamps in seconds. Preserve prior plugin versions for explicit rollback. Record live catalog, account routing, and configuration-preservation checks after installation. A new upstream tag alone does not advance this channel.
