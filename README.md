# Reviewed CPA update channel

This channel keeps reviewed model-catalog and account-routing changes available while their upstream contributions are open. It is a fork distribution, not an official release.

Configure EasyCLIProxyAPI's Reviewed core channel with:

`https://raw.githubusercontent.com/samaluk/CLIProxyAPI/reviewed-channel/core.json`

Add this native plugin store source once:

`https://raw.githubusercontent.com/samaluk/CLIProxyAPI/reviewed-channel/plugins.json`

The manifest pins the core repository, source commit, tag, archive size and SHA-256. The plugin registry uses direct artifacts with exact versions, hashes and sizes. Artifacts are immutable; advancing this branch advertises another tested release. Never replace the bytes of a published version. The GUI keeps configuration/auth/plugins when updating core and restores its previous binary if startup or catalog/plugin health checks fail.

Existing hand-installed plugins need a one-time source migration that preserves their settings and binding state. Do not uninstall the binding plugin to bypass a source conflict. Later updates use the same source identity through the normal plugin store.

Only macOS arm64 is advertised by this channel. Pi uses the stock npm package pinned in `stack.json`. T3 and the harness applications remain on their vendor channels. Main Codex configuration remains separately managed.

The reviewed Easy app currently needs a local build; its existing signature and Gatekeeper requirements remain enabled. Selecting this core channel protects the locally patched app from an accidental official self-update.

## Advancing the channel

Fetch upstream, preserve immutable backup tags, rebase scoped contribution branches, and remove patches superseded by stock releases. Run focused regression tests and independent review. Build from clean commits with honest version metadata. Publish each exact artifact to a new release, verify the downloaded bytes, then update the manifests together. Preserve prior plugin versions for rollback. Record live catalog, account routing, and configuration-preservation checks after installation. A new upstream tag alone does not advance this channel.
