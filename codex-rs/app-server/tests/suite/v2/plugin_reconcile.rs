//! Account login and client reconciliation must not mutate local plugins or skills.

use std::time::Duration;

use anyhow::Result;
use app_test_support::ChatGptAuthFixture;
use app_test_support::ChatGptIdTokenClaims;
use app_test_support::MockResponsesConfig;
use app_test_support::TestAppServer;
use app_test_support::encode_id_token;
use app_test_support::write_chatgpt_auth;
use codex_app_server_protocol::LoginAccountResponse;
use codex_app_server_protocol::PluginReconcileResponse;
use codex_config::types::AuthCredentialsStoreMode;
use codex_features::Feature;
use pretty_assertions::assert_eq;
use serde_json::json;
use tempfile::TempDir;
use test_case::test_case;
use tokio::time::timeout;
use wiremock::MockServer;

const DEFAULT_TIMEOUT: Duration = Duration::from_secs(30);

#[test_case(false; "remote_features_disabled")]
#[test_case(true; "remote_features_enabled")]
#[tokio::test]
async fn login_and_reconcile_preserve_local_plugins_and_skills(remote_features: bool) -> Result<()> {
    let server = MockServer::start().await;
    let codex_home = TempDir::new()?;
    let mut config = MockResponsesConfig::new(&server.uri())
        .with_root_config(&format!("chatgpt_base_url = '{}/backend-api/'", server.uri()))
        .enable_feature(Feature::Plugins);
    for feature in [Feature::Apps, Feature::RemotePlugin, Feature::PluginSharing] {
        config = if remote_features {
            config.enable_feature(feature)
        } else {
            config.disable_feature(feature)
        };
    }
    config.write(codex_home.path())?;
    write_chatgpt_auth(
        codex_home.path(),
        ChatGptAuthFixture::new("chatgpt-token")
            .account_id("account-original")
            .chatgpt_user_id("user-original")
            .chatgpt_account_id("account-original"),
        AuthCredentialsStoreMode::File,
    )?;
    let skill = codex_home.path().join("skills/local/SKILL.md");
    let plugin = codex_home.path().join("plugins/cache/local/sample/local/.codex-plugin/plugin.json");
    for (file, content) in [(&skill, "local skill"), (&plugin, "{\"name\":\"sample\"}")] {
        std::fs::create_dir_all(file.parent().unwrap())?;
        std::fs::write(file, content)?;
    }
    let original_config = std::fs::read(codex_home.path().join("config.toml"))?;
    let mut app_server = TestAppServer::builder()
        .with_codex_home(codex_home.path())
        .without_managed_config()
        .with_env_overrides(&[("OPENAI_API_KEY", None)])
        .build_initialized_with_timeout(DEFAULT_TIMEOUT)
        .await?;
    for (account, reason) in [("account-one", "startup"), ("account-two", "account_changed")] {
        let token = encode_id_token(
            &ChatGptIdTokenClaims::new()
                .email("local@example.test")
                .plan_type("enterprise")
                .chatgpt_account_id(account),
        )?;
        let login = app_server
            .send_chatgpt_auth_tokens_login_request(token, account.into(), Some("enterprise".into()))
            .await?;
        let _: LoginAccountResponse = timeout(DEFAULT_TIMEOUT, app_server.read_response(login)).await??;
        let reconcile = app_server
            .send_raw_request("plugin/reconcile", Some(json!({"reason": reason})))
            .await?;
        let response: PluginReconcileResponse =
            timeout(DEFAULT_TIMEOUT, app_server.read_response(reconcile)).await??;
        assert_eq!(response, PluginReconcileResponse::default());
        assert_eq!(std::fs::read_to_string(&skill)?, "local skill");
        assert_eq!(std::fs::read_to_string(&plugin)?, "{\"name\":\"sample\"}");
        assert_eq!(std::fs::read(codex_home.path().join("config.toml"))?, original_config);
    }
    assert!(!codex_home.path().join(".tmp/plugins").exists());
    assert!(!codex_home.path().join("plugins/cache/openai-curated-remote").exists());
    assert!(server.received_requests().await.unwrap().iter().all(|request| {
        !request.url.path().contains("/ps/plugins/") && request.url.path() != "/bundle"
    }));
    Ok(())
}
