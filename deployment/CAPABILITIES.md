# Provider-first capabilities

Every base capability decision starts with what the provider actually offers on the configured route. This includes context and output limits, input/output types, reasoning levels and defaults, tool support, and service tiers. Keep routing identity separate from display labels and trusted harness prompts.

## Precedence

1. Fresh authenticated metadata for the actual provider account and model deployment.
2. Provider-published metadata for that exact deployment/model, when it does not claim account-specific access.
3. Previously verified values retained during missing discovery, labeled as stale/fallback. An explicit empty capability list overrides an old nonempty list. Missing data does not mean an empty list.
4. Harness defaults only when its schema requires them, explicitly reported as defaults. Never advertise a capability or entitlement merely because a similar model supports it.

Local configuration can impose a restriction, but cannot grant upstream capability. A documented manual deployment mapping may fill missing facts; it must retain its evidence and cannot override a newer authoritative value silently. Translating provider names such as priority into a harness's fast selector is a mapping, not an entitlement decision.

## Implemented in this deployment

The scoped refresh helper consumes rich proxy route metadata before projecting it to Codex, OpenCode and stock Pi. For the matching native Codex account it additionally calls authenticated model discovery, checks account identity against the gateway credential, maps only explicit account aliases, and overrides the capabilities that response declares. Remote prose and prompts are excluded. Context/output and input aliases cannot let older generic values outrank the account response. Removed reasoning levels cannot leave an invalid default.

The fork understands both fast and ultrafast. The October 4 account response reported fast only; this is an observation, not a permanent rule. A future response containing ultrafast will enable it at refresh. There is no subscription-price check or deny list.

Unverified Codex routes are deferred individually, leaving existing entries available for saved threads. Missing Personal discovery does not prevent Work refresh. A custom main Codex provider does not disable read-only client-version discovery, but its cache is never imported as a trusted native prompt source.

## Limits and upstream work

The proxy's rich metadata is not proof that every upstream field was discovered live. Some configured routes still use saved catalogs or reviewed manual mappings, including metadata that an upstream account does not expose. The refresh report identifies authenticated fields separately from proxy metadata, but older gateway records do not carry per-field origin/freshness through the whole pipeline. Treat those as fallback evidence, not a claim of account verification.

The next upstream contribution should preserve per-field source, account/deployment identity, observation time and explicit absence through provider discovery, registry aliases, API export and client projection. Each provider adapter should prefer its authenticated discovery where available, while reporting unavailable fields instead of inventing values. Codex account discovery should move to the gateway so remote clients and the NAS share the same verified data without reading Mac credential files.

Tool support and some output modalities are not configurable in every harness schema. Report those limitations rather than inventing unsupported configuration fields. Prompt selection remains based on trusted native canonical templates; capability discovery must not overwrite harness system prompts.
