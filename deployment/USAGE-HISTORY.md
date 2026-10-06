# Usage history after the NAS migration

Easy's Mac GUI persisted usage in `~/Library/Application Support/com.cpa.gui/usage-records/usage.db`. The core did not own that SQLite database, so moving provider configuration and OAuth files to the NAS did not migrate the GUI's history.

The October 6 recovery created a consistent private SQLite backup, checked integrity and copied all 39,007 original events to `/volume1/docker/easy-cli-proxy/data/usage-history/archive/mac-20261004-usage.sqlite`. A SHA256 comparison verified the NAS archive matches the backup exactly. The source database remains unchanged. Private manifests and the local backup are under `cpa-capability-lab/private/usage-recovery-20261006`. The archive covers September 7 through October 4. Preserve every original row.

The current NAS image has no durable usage database or history-import API. Its core keeps a short memory queue with 60-second configured retention; a restart also discards it. The current management UI cannot read the archived Easy SQLite store. This recovery therefore preserves history on the NAS but does not merge it into the dashboard. NAS events already expired from the queue cannot be reconstructed from the retained configuration or bindings.

## Avoid losing more data

Do not read `/v0/management/v8/observability/usage/queue` to inspect it casually. GET destructively pops records. Do not run two collectors. A future collector must save each received batch privately before normalization, use restrictive permissions and stop on storage failures. Even then, this queue can lose a batch if the server pops it before a response or client commit fails.

The NAS host has Python and SQLite available, so a small managed collector is possible. It needs a homelab deployment contribution with private management-key provisioning, a single-consumer lock, bounded logs and a persistent volume. This recovery pass did not deploy a collector, consume the live queue or restart the core.

Reliable history needs a durable acknowledged spool in the proxy, plus history read/import APIs and UI support. Import keys should use source database checksum plus original row ID. `request_id` or Easy's `event_key` repeats legitimately across retries; treating it as unique would discard 1,038 original records. Keep the recovered archive immutable and perform imports into a new store with private backup and repeatable validation.
