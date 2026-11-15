use super::*;
use pretty_assertions::assert_eq;
use test_case::test_case;

#[derive(Clone, Copy, PartialEq, Eq)]
enum SnapshotSandbox {
    None,
    WorkspaceWrite,
    CloseDescriptors,
}

pub(super) struct StartupProcesses(pub(super) std::path::PathBuf);

impl Drop for StartupProcesses {
    fn drop(&mut self) {
        if let Ok(contents) = std::fs::read_to_string(&self.0) {
            for pid in contents
                .split_whitespace()
                .filter_map(|pid| pid.parse::<i32>().ok())
            {
                if pid > 0 {
                    // SAFETY: these PIDs were written by our startup profile.
                    unsafe { libc::kill(pid, libc::SIGKILL) };
                }
            }
        }
    }
}

#[test_case("bash"; "bash")]
#[cfg_attr(target_os = "macos", test_case("zsh"; "zsh"))]
#[tokio::test]
async fn shell_snapshot_preserves_successful_startup_output_and_services(
    shell: &str,
) -> Result<()> {
    let context = create_process_context(/*use_remote*/ false).await?;
    let home = TempDir::new()?;
    let _service = StartupProcesses(home.path().join("service-pid"));
    std::fs::write(
        home.path().join(format!(".{shell}rc")),
        "printf x >> \"$HOME/captures\"\n/bin/sleep 30 >/dev/null 2>&1 &\nexport SNAPSHOT_SERVICE_PID=$!\nprintf '%s' \"$SNAPSHOT_SERVICE_PID\" > \"$HOME/service-pid\"\nexec > >(/bin/sleep 0.2; /bin/cat)\nprofile_helper() { printf 'captured:%s' \"$1\"; }\n",
    )?;
    for index in 0..2 {
        let started = context
            .backend
            .start(ExecParams {
                metadata: Default::default(),
                process_id: format!("startup-capture-{index}").into(),
                argv: vec![
                    format!("/bin/{shell}"),
                    "-lc".to_string(),
                    format!(
                        "[ \"$SNAPSHOT_SERVICE_PID\" = \"$(/bin/cat \"$HOME/service-pid\")\" ] || exit 41\ncase \"$(/bin/ps -o stat= -p \"$SNAPSHOT_SERVICE_PID\")\" in ''|*Z*) exit 42;; esac\nprofile_helper {index}"
                    ),
                ],
                cwd: PathUri::from_host_native_path(home.path())?,
                env: HashMap::from([
                    (
                        "HOME".to_string(),
                        home.path().to_string_lossy().into_owned(),
                    ),
                    ("PATH".to_string(), "/usr/bin:/bin".to_string()),
                ]),
                env_policy: None,
                shell_snapshot: Some(ShellSnapshotRequest {
                    scope_id: "startup-capture".to_string(),
                    shell: ShellInfo {
                        name: shell.to_string(),
                        path: format!("/bin/{shell}"),
                    },
                }),
                tty: false,
                pipe_stdin: false,
                arg0: Some("codex-linux-sandbox".to_string()),
                sandbox: None,
                enforce_managed_network: false,
                managed_network: None,
                network_proxy: None,
            })
            .await?;
        assert_eq!(
            collect_process_output_from_events(started.process).await?,
            (format!("captured:{index}"), String::new(), Some(0), true)
        );
    }
    assert_eq!(std::fs::read_to_string(home.path().join("captures"))?, "x");
    Ok(())
}

#[test_case("bash", false, SnapshotSandbox::None; "bash")]
#[test_case("bash", true, SnapshotSandbox::None; "bash_tty")]
#[cfg_attr(target_os = "macos", test_case("zsh", false, SnapshotSandbox::None; "zsh"))]
#[cfg_attr(target_os = "macos", test_case("zsh", true, SnapshotSandbox::None; "zsh_tty"))]
#[test_case("bash", false, SnapshotSandbox::CloseDescriptors; "closed_descriptor_transport")]
#[cfg_attr(target_os = "macos", test_case("zsh", false, SnapshotSandbox::CloseDescriptors; "zsh_closed_descriptor_transport"))]
#[cfg_attr(target_os = "macos", test_case("zsh", true, SnapshotSandbox::CloseDescriptors; "zsh_closed_descriptor_transport_tty"))]
#[test_case("bash", false, SnapshotSandbox::WorkspaceWrite; "bash_protected_transport")]
#[test_case("bash", true, SnapshotSandbox::WorkspaceWrite; "bash_protected_transport_tty")]
#[cfg_attr(target_os = "macos", test_case("zsh", false, SnapshotSandbox::WorkspaceWrite; "zsh_protected_transport"))]
#[cfg_attr(target_os = "macos", test_case("zsh", true, SnapshotSandbox::WorkspaceWrite; "zsh_protected_transport_tty"))]
#[serial_test::serial(remote_exec_server)]
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn shell_snapshot_concurrent_replays_keep_independent_readers(
    shell: &str,
    tty: bool,
    sandbox_mode: SnapshotSandbox,
) -> Result<()> {
    let close_descriptors = sandbox_mode == SnapshotSandbox::CloseDescriptors;
    let use_sandbox = sandbox_mode != SnapshotSandbox::None;
    if use_sandbox
        && let Some(warning) = codex_sandboxing::system_bwrap_warning(
            &PermissionProfile::read_only(),
            &std::env::current_dir()?,
        )
    {
        eprintln!("skipping sandbox test: {warning}");
        return Ok(());
    }
    let context = if sandbox_mode == SnapshotSandbox::WorkspaceWrite {
        let (exe, linux_sandbox) = current_test_binary_helper_paths()?;
        let environment = Environment::create(
            /*exec_server_url*/ None,
            codex_exec_server::ExecServerRuntimeOptions::new(exe, linux_sandbox)?,
            codex_http_client::HttpClientFactory::new(
                codex_http_client::OutboundProxyPolicy::ReqwestDefault,
            ),
        )?;
        ProcessContext {
            backend: environment.get_exec_backend(),
            _server: None,
        }
    } else {
        create_process_context(close_descriptors).await?
    };
    let home = TempDir::new()?;
    let cwd = PathUri::from_host_native_path(home.path())?;
    // Keep full-size state in a function, below the 512 KiB state + environment cap.
    // The blocked-path case still exercises the smaller environment fallback.
    let payload_len = if close_descriptors { 1 } else { 480 * 1024 };
    let payload = "x".repeat(payload_len);
    let source = if shell == "bash" {
        "${BASH_SOURCE[0]}"
    } else {
        "${(%):-%x}"
    };
    let source_check = if close_descriptors {
        String::new()
    } else {
        format!("case \"{source}\" in /dev/fd/*) ;; *) return 42 ;; esac; ")
    };
    let aliases = if shell == "zsh" {
        "module_path=()\nsetopt RC_QUOTES\nalias snapshot_quoted=\"printf '%s|' 'one''two'\"\nalias eval='exit 44'\nalias case='exit 45'\n"
    } else {
        ""
    };
    std::fs::write(
        home.path().join(format!(".{shell}rc")),
        format!(
            "printf x >> \"$HOME/captures\"\nprofile_helper() {{ {source_check}local payload='{payload}'; [ \"${{#payload}}\" = {payload_len} ] || return 43; printf 'restored:%s' \"$1\"; }}\nexec() {{ exit 41; }}\nset -u\n{aliases}"
        ),
    )?;
    let shell_path = if close_descriptors {
        // Simulate a launcher that strips inherited readers. Mounting tmpfs on
        // /dev/fd is invalid on Linux because it is a dynamic /proc/self/fd
        // symlink; that fails before snapshot probing can exercise its fallback.
        let wrapper = home.path().join("snapshot-shell");
        codex_utils_cargo_bin::write_executable(
            &wrapper,
            &format!(
                r#"#!/usr/bin/python3
import os
import sys
for descriptor in os.listdir('/dev/fd'):
    try:
        fd = int(descriptor)
        if fd > 2:
            os.close(fd)
    except (OSError, ValueError):
        pass
os.execv('/bin/{shell}', ['/bin/{shell}', *sys.argv[1:]])
"#
            ),
        )?;
        wrapper.to_string_lossy().into_owned()
    } else {
        format!("/bin/{shell}")
    };
    let protected_file =
        tempfile::NamedTempFile::new_in(codex_uds::prepare_shared_daemon_socket_directory()?)?;
    std::fs::write(protected_file.path(), "protected")?;
    let command = if sandbox_mode == SnapshotSandbox::WorkspaceWrite {
        // Broad /tmp grants must not expose the file while it still has a name.
        "if /bin/cat \"$SNAPSHOT_TRANSPORT_PROBE\" >/dev/null 2>&1 || (printf poisoned >> \"$SNAPSHOT_TRANSPORT_PROBE\") 2>/dev/null || /bin/mv \"$SNAPSHOT_TRANSPORT_PROBE\" \"$HOME/stolen\" 2>/dev/null; then exit 44; fi\n"
    } else {
        ""
    };
    let replay_checks = if shell == "zsh" {
        "eval snapshot_quoted\n[[ -o rcquotes ]] || exit 46\n"
    } else {
        ""
    };
    let command =
        format!("{command}IFS= read -r line\n{replay_checks}profile_helper \"$line\"; exit 7");
    let sandbox = if use_sandbox {
        let mut policy = FileSystemSandboxPolicy::read_only();
        policy.entries.push(FileSystemSandboxEntry::new(
            cwd.clone().into(),
            FileSystemAccessMode::Write,
        ));
        if !close_descriptors {
            policy.entries.push(FileSystemSandboxEntry::new(
                PathUri::from_host_native_path(std::fs::canonicalize("/tmp")?)?.into(),
                FileSystemAccessMode::Write,
            ));
        }
        Some(FileSystemSandboxContext::from_permission_profile(
            PermissionProfile::from_runtime_permissions(&policy, NetworkSandboxPolicy::Restricted),
            cwd.clone(),
        ))
    } else {
        None
    };
    let commands = (0..8).map(|index| {
        let backend = &context.backend;
        let cwd = cwd.clone();
        let home = home.path();
        let sandbox = sandbox.clone();
        let command = command.clone();
        let shell_path = shell_path.clone();
        let protected_path = protected_file.path();
        async move {
            let params = ExecParams {
                metadata: Default::default(),
                process_id: format!("parallel-{index}").into(),
                argv: vec![shell_path.clone(), "-lc".to_string(), command],
                cwd,
                env: HashMap::new(),
                env_policy: Some(ExecEnvPolicy {
                    inherit: ShellEnvironmentPolicyInherit::None,
                    ignore_default_excludes: false,
                    exclude: Vec::new(),
                    r#set: HashMap::from([
                        ("HOME".to_string(), home.to_string_lossy().into_owned()),
                        ("PATH".to_string(), "/usr/bin:/bin".to_string()),
                        (
                            "SNAPSHOT_TRANSPORT_PROBE".to_string(),
                            protected_path.to_string_lossy().into_owned(),
                        ),
                    ]),
                    include_only: Vec::new(),
                }),
                shell_snapshot: Some(ShellSnapshotRequest {
                    scope_id: "parallel".to_string(),
                    shell: ShellInfo {
                        name: shell.to_string(),
                        path: shell_path,
                    },
                }),
                tty,
                pipe_stdin: true,
                arg0: None,
                sandbox,
                enforce_managed_network: false,
                managed_network: None,
                network_proxy: None,
            };
            if close_descriptors && index == 0 {
                let mut probe = params.clone();
                probe.process_id = "descriptor-sandbox-probe".into();
                probe.argv[2] = "printf sandbox-ready".to_string();
                probe.shell_snapshot = None;
                probe.pipe_stdin = false;
                let probe = backend.start(probe).await?;
                assert_eq!(
                    collect_process_output_from_events(probe.process).await?,
                    ("sandbox-ready".to_string(), String::new(), Some(0), true),
                    "descriptor stripping must preserve ordinary sandboxed commands",
                );
            }
            let started = backend.start(params).await?;
            started
                .process
                .write(format!("input-{index}\n").into_bytes())
                .await?;
            let (output, errors, status, closed) =
                collect_process_output_from_events(started.process).await?;
            assert!(
                output.ends_with(&format!("restored:input-{index}")),
                "stdout={output:?}, stderr={errors:?}, status={status:?}, closed={closed}"
            );
            if shell == "zsh" {
                assert!(
                    output.ends_with(&format!("one'two|restored:input-{index}")),
                    "{output:?}"
                );
            }
            assert_eq!((errors, status, closed), (String::new(), Some(7), true));
            Ok::<_, anyhow::Error>(())
        }
    });
    for result in futures::future::join_all(commands).await {
        result?;
    }
    assert_eq!(std::fs::read_to_string(home.path().join("captures"))?, "x");
    assert_eq!(std::fs::read_to_string(protected_file.path())?, "protected");
    Ok(())
}
