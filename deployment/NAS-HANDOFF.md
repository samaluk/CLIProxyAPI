# Synology agent handoff

## Scope and known host facts

The user has installed and logged into Tailscale on the NAS. Verify its actual address, MagicDNS name and ACL reachability rather than assuming them. The previously inspected machine is a DS916+ family host, Intel Pentium N3710 amd64, about 8 GB RAM, DSM 7.1.1, kernel 3.10.108, Docker 20.10.3 and Compose 1.28.5. It already runs the containers in `~/dev/personal/homelab` through Komodo. It had substantial swap and I/O pressure. Recheck current headroom and installed versions.

Use generic amd64 (`GOAMD64=v1`); no AVX. Build elsewhere. A provisional 512 MiB runtime limit must be measured under concurrent streams, plugin loading and auth refresh. Do not assume modern Linux build success proves compatibility with this old DSM kernel.

## Prepare without a cutover

1. Read the homelab repository instructions and its Synology/Komodo skills. Use the existing per-service compose/secret conventions. Do not deploy the unrelated infrastructure or run unsupported Komodo Actions on the old NAS kernel.
2. Run `python3 deployment/prepare_sources.py`, then build the image on a supported Docker build host:

   ```sh
   docker build --platform linux/amd64 -t cpa-reviewed:20261004 -f deployment/Dockerfile deployment
   ```

   Transfer the resulting image privately or publish it to an authorized registry with a fixed digest. Record the digest in the homelab compose file. Do not let a generic image updater advance this assembled stack independently of the reviewed release process.
3. Copy `deployment/compose.yaml` into the homelab's new CPA service folder. Set the image reference and persistent data path there. Do not start it before importing a valid config and state.
4. Make a private, permission-restricted backup of the Mac's effective core configuration, OAuth auth directory, account-binding state, local model definition files and plugin store provenance. Resolve every configured file reference. Typical Mac root: `~/Library/Application Support/com.cpa.gui/cpa-core`; profile keys/catalogs live under `~/Library/Application Support/Agent Profiles`. Never add these to git or the public report.
5. Create the persistent auth/state/catalog directories with private permissions and import a staged copy under the NAS service's persistent data directory. Preserve scope/source key bindings and existing session records. Rewrite only host-specific paths: auth to `/data/auth`, account state to `/data/state`, local catalogs to `/data/catalogs`, plugin directory to `/opt/cpa/plugins`. Keep provider URLs, model IDs, aliases and credential values. Do not copy macOS dylibs into Linux. Remove or rewrite only platform-specific store selections that would select a macOS library; retain their private provenance for rollback. This container intentionally updates its bundled Linux plugins through the image lock, not by mutable in-container plugin installs.
6. Use the upstream v8 configuration schema (see root `config.example.yaml`): `server.host: 0.0.0.0`, `server.port: 8317`, `oauth.auth-dir: /data/auth`, `plugins.dir: /opt/cpa/plugins`. Legacy files still load; avoid simultaneous conflicting old/new keys. Keep request logging off or bounded. Do not reset missing provider auth automatically.

## Network and acceptance

- The compose port is bound to NAS loopback. Publish it only over the tailnet using the NAS's supported Tailscale Serve configuration or an equivalent tailnet-only reverse proxy. Keep TLS verification on. Do not open a router/WAN port.
- Restrict tailnet reachability and management access. Management still requires a separate secret; a downstream model key is not a management key. Do not send secrets to redirected origins. Desktop Easy's local core lifecycle does not automatically become a remote NAS lifecycle manager: use the remote management UI/API for NAS config and homelab/Komodo for image updates.
- Staging the imported OAuth files must not create two simultaneous refresh owners. Keep the staged service stopped, or use synthetic/API-only validation until the old gateway is quiesced for final credential transfer.
- Confirm health, all three Linux plugin registrations, each scope's catalog, rejection of unauthorized cross-scope requests, and a streamed tool-call continuation. Check declared context/output limits, effort mappings, native prompt identity and labels. Speed tiers, including ultrafast, must match the authenticated account response. Never copy a plan-based deny rule.
- Exercise OAuth refresh and temporary upstream failures without switching account/source. Measure RAM, CPU, swap and storage during several concurrent streams on DSM.

## Cutover and rollback

Only after acceptance, quiesce the Mac gateway, take a final private auth/binding snapshot, transfer it, and start the NAS gateway as the sole owner. Update one scoped client at a time to the verified HTTPS origin. Preserve the old local binaries/configuration for rollback, but never restore stale auth or binding state over newer state. Main Codex cutover is a separate user action; do not edit it while its coordinating agent is running.

The public fork cannot contain the account credentials. Successful deployment requires the private import and real NAS runtime acceptance above; the source lock and image build alone do not establish that these have passed.
