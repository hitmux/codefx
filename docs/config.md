# Configuration

For basic configuration instructions, see [this documentation](https://developers.openai.com/codex/config-basic).

For advanced configuration instructions, see [this documentation](https://developers.openai.com/codex/config-advanced).

For a full configuration reference, see [this documentation](https://developers.openai.com/codex/config-reference).

## Codefx account integrations

Codefx defaults to `apps = false`, `remote_plugin = false`, and
`plugin_sharing = false` under `[features]`. Each integration requires an explicit
setting to enable its interactive operations.

Signing in to an OpenAI account does not synchronize plugins or skills. Startup,
discovery, plugin listing, and account changes do not install, replace, remove, or
upgrade local plugin bundles or skills. This applies even when all three features
are enabled. The `plugin/reconcile` compatibility endpoint returns an empty result
without fetching account state or changing local files.

Install, remove, and upgrade plugins through explicit plugin commands or actions.
Configured local plugins and skills remain available without remote account sync.

## Lifecycle hooks

Admins can set top-level `allow_managed_hooks_only = true` in
`requirements.toml` to ignore user, project, and session hook configs while
still allowing managed hooks from requirements and managed config layers. This
setting is only supported in `requirements.toml`; putting it in `config.toml`
does not enable managed-hooks-only mode.
