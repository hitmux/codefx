// Release builds exceed rustc's default query depth when laying out the async
// MessageProcessor::handle_initialized_client_request future.
#![recursion_limit = "256"]

//! Entry-point for the `codex-exec` binary.
//!
//! When this CLI is invoked normally, it parses the standard `codex-exec` CLI
//! options and launches the non-interactive Codex agent. However, if it is
//! invoked with arg0 as `codex-linux-sandbox`, we instead treat the invocation
//! as a request to run the logic for the standalone `codex-linux-sandbox`
//! executable (i.e., parse any -s args and then run a *sandboxed* command under
//! Landlock + seccomp.
//!
//! This allows us to ship a completely separate set of functionality as part
//! of the `codex-exec` binary.
use clap::CommandFactory;
use clap::Parser;
use codex_arg0::Arg0DispatchPaths;
use codex_arg0::arg0_dispatch_or_else;
use codex_exec::Cli;
use codex_exec::run_main;
use codex_utils_cli::CliConfigOverrides;
use codex_utils_cli::collect_config_overrides;
use std::ffi::OsString;

#[derive(Parser, Debug)]
struct TopCli {
    #[clap(flatten)]
    config_overrides: CliConfigOverrides,

    #[clap(flatten)]
    inner: Cli,
}

fn main() -> anyhow::Result<()> {
    arg0_dispatch_or_else(|arg0_paths: Arg0DispatchPaths| async move {
        let inner = parse_cli_from(std::env::args_os()).unwrap_or_else(|error| error.exit());
        run_main(inner, arg0_paths).await?;
        Ok(())
    })
}

fn parse_cli_from(
    args: impl IntoIterator<Item = impl Into<OsString> + Clone>,
) -> Result<Cli, clap::Error> {
    let args: Vec<OsString> = args.into_iter().map(Into::into).collect();
    let mut top_cli = TopCli::try_parse_from(&args)?;
    // As in the main CLI, preserve overrides on both sides of a subcommand.
    // Clap's global append arguments otherwise retain only the deepest scope.
    top_cli.config_overrides = collect_config_overrides(TopCli::command(), args)?;
    let mut inner = top_cli.inner;
    inner.config_overrides.prepend_root_overrides(top_cli.config_overrides);
    Ok(inner)
}

#[cfg(test)]
#[path = "main_tests.rs"]
mod tests;
