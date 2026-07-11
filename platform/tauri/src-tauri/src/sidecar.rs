use crate::{desktop_config, notifications};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::{
    path::{Path, PathBuf},
    sync::{
        atomic::{AtomicBool, AtomicU64, Ordering},
        Condvar, Mutex, MutexGuard,
    },
    time::{Duration, Instant},
};
use tauri::{AppHandle, Emitter, Manager, Runtime};
use tauri_plugin_shell::{
    process::{Command, CommandChild, CommandEvent},
    ShellExt,
};

const EVENT_PREFIX: &str = "QQMAIL_EVENT ";
const SHUTDOWN_HTTP_TIMEOUT: Duration = Duration::from_secs(1);
const SHUTDOWN_GRACE_PERIOD: Duration = Duration::from_secs(3);

#[derive(Clone, Debug, Serialize)]
pub struct BackendConnection {
    pub base_url: String,
    pub token: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
struct SidecarEvent {
    event: String,
    #[serde(default)]
    payload: Value,
}

pub struct DesktopState {
    connection: Mutex<Option<BackendConnection>>,
    child: Mutex<Option<ManagedChild>>,
    child_stopped: Condvar,
    generation: AtomicU64,
    stopping: AtomicBool,
    restart_attempts: Mutex<u32>,
    started_at: Mutex<Option<Instant>>,
    lifecycle_guard: Mutex<()>,
}

struct ManagedChild {
    generation: u64,
    child: CommandChild,
}

impl Default for DesktopState {
    fn default() -> Self {
        Self {
            connection: Mutex::new(None),
            child: Mutex::new(None),
            child_stopped: Condvar::new(),
            generation: AtomicU64::new(0),
            stopping: AtomicBool::new(false),
            restart_attempts: Mutex::new(0),
            started_at: Mutex::new(None),
            lifecycle_guard: Mutex::new(()),
        }
    }
}

impl DesktopState {
    pub fn connection(&self) -> Option<BackendConnection> {
        self.connection.lock().ok().and_then(|value| value.clone())
    }

    fn set_connection(&self, generation: u64, connection: BackendConnection) {
        if !self.is_current(generation) {
            return;
        }
        if let Ok(mut current) = self.connection.lock() {
            *current = Some(connection);
        }
    }

    fn has_child(&self) -> bool {
        self.child.lock().is_ok_and(|child| child.is_some())
    }

    fn set_child(&self, generation: u64, child: CommandChild) {
        if let Ok(mut current) = self.child.lock() {
            *current = Some(ManagedChild { generation, child });
        }
    }

    fn take_child(&self) -> Option<CommandChild> {
        let child = self
            .child
            .lock()
            .ok()
            .and_then(|mut value| value.take().map(|managed| managed.child));
        self.child_stopped.notify_all();
        child
    }

    fn clear_child(&self, generation: u64) {
        if let Ok(mut current) = self.child.lock() {
            if current
                .as_ref()
                .is_some_and(|managed| managed.generation == generation)
            {
                *current = None;
                self.child_stopped.notify_all();
            }
        }
    }

    fn wait_for_child_exit(&self, timeout: Duration) -> bool {
        let current = self
            .child
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        if current.is_none() {
            return true;
        }
        match self
            .child_stopped
            .wait_timeout_while(current, timeout, |child| child.is_some())
        {
            Ok((current, _)) => current.is_none(),
            Err(poisoned) => poisoned.into_inner().0.is_none(),
        }
    }

    fn lock_lifecycle(&self) -> MutexGuard<'_, ()> {
        self.lifecycle_guard
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
    }

    fn begin_generation(&self) -> u64 {
        self.stopping.store(false, Ordering::SeqCst);
        if let Ok(mut connection) = self.connection.lock() {
            *connection = None;
        }
        if let Ok(mut started_at) = self.started_at.lock() {
            *started_at = Some(Instant::now());
        }
        self.generation.fetch_add(1, Ordering::SeqCst) + 1
    }

    fn is_current(&self, generation: u64) -> bool {
        self.generation.load(Ordering::SeqCst) == generation
            && !self.stopping.load(Ordering::SeqCst)
    }

    fn mark_stopping(&self) {
        self.stopping.store(true, Ordering::SeqCst);
        self.generation.fetch_add(1, Ordering::SeqCst);
        if let Ok(mut connection) = self.connection.lock() {
            *connection = None;
        }
        if let Ok(mut started_at) = self.started_at.lock() {
            *started_at = None;
        }
    }

    fn reset_restart_attempts(&self) {
        if let Ok(mut attempts) = self.restart_attempts.lock() {
            *attempts = 0;
        }
    }

    fn restart_after_termination(&self, generation: u64) -> Option<(u32, Duration)> {
        self.clear_child(generation);
        if !self.is_current(generation) {
            return None;
        }
        let uptime = self
            .started_at
            .lock()
            .ok()
            .and_then(|mut started_at| started_at.take())
            .map(|started_at| started_at.elapsed())
            .unwrap_or_default();
        if let Ok(mut connection) = self.connection.lock() {
            *connection = None;
        }

        let mut attempts = self.restart_attempts.lock().ok()?;
        if uptime >= Duration::from_secs(60) {
            *attempts = 0;
        }
        if *attempts >= 5 {
            return None;
        }
        *attempts += 1;
        let delay_seconds = match *attempts {
            1 => 2,
            2 => 5,
            3 => 15,
            4 => 30,
            _ => 60,
        };
        Some((*attempts, Duration::from_secs(delay_seconds)))
    }
}

fn project_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .ancestors()
        .nth(3)
        .expect("Tauri project must remain inside platform/tauri/src-tauri")
        .to_path_buf()
}

fn build_command<R: Runtime>(
    app: &AppHandle<R>,
    token: &str,
    data_dir: &Path,
) -> Result<Command, String> {
    let mut command = if cfg!(debug_assertions) {
        let root = project_root();
        app.shell()
            .command("python")
            .arg("-m")
            .arg("qq_mail_agent_cli.desktop_worker")
            .env("PYTHONPATH", root.join("src"))
            .current_dir(root)
    } else {
        app.shell()
            .sidecar("qq-mail-agent-worker")
            .map_err(|error| format!("无法定位桌面 sidecar：{error}"))?
    };

    command = command
        .arg("--host")
        .arg("127.0.0.1")
        .arg("--port")
        .arg("0")
        .arg("--data-dir")
        .arg(data_dir)
        .arg("--parent-pid")
        .arg(std::process::id().to_string())
        .env("QQ_MAIL_AGENT_SESSION_TOKEN", token);
    for (key, value) in desktop_config::sidecar_environment(app)? {
        command = command.env(key, value);
    }
    Ok(command)
}

fn allowed_base_url(value: &str) -> bool {
    value
        .strip_prefix("http://127.0.0.1:")
        .and_then(|port| port.parse::<u16>().ok())
        .is_some_and(|port| port > 0)
}

fn post_json<R: Runtime>(app: &AppHandle<R>, path: &str, body: &Value) -> Result<(), String> {
    let connection = app
        .state::<DesktopState>()
        .connection()
        .ok_or_else(|| "desktop backend is not connected".to_string())?;
    post_json_to(&connection, path, body)
}

fn post_json_to(connection: &BackendConnection, path: &str, body: &Value) -> Result<(), String> {
    post_json_to_with_timeout(connection, path, body, Duration::from_secs(3))
}

fn post_json_to_with_timeout(
    connection: &BackendConnection,
    path: &str,
    body: &Value,
    timeout: Duration,
) -> Result<(), String> {
    if !allowed_base_url(&connection.base_url) || !path.starts_with('/') {
        return Err("desktop backend address is invalid".to_string());
    }
    let authorization = format!("Bearer {}", connection.token);
    ureq::post(&format!("{}{}", connection.base_url, path))
        .timeout(timeout)
        .set("Authorization", &authorization)
        .send_json(body)
        .map(|_| ())
        .map_err(|_| "desktop backend acknowledgement failed".to_string())
}

fn spawn_ack<R: Runtime>(app: &AppHandle<R>, path: String, body: Value) {
    let app = app.clone();
    std::thread::spawn(move || {
        let retry_delays = [
            Duration::ZERO,
            Duration::from_millis(250),
            Duration::from_secs(1),
        ];
        for delay in retry_delays {
            if !delay.is_zero() {
                std::thread::sleep(delay);
            }
            if post_json(&app, &path, &body).is_ok() {
                return;
            }
        }
        let _ = app.emit(
            "qq-mail-event",
            serde_json::json!({
                "event": "watcher_status",
                "payload": { "status": "notification_ack_failed" }
            }),
        );
    });
}

pub fn acknowledge_notification<R: Runtime>(
    app: &AppHandle<R>,
    mail_key: String,
    status: &'static str,
) {
    spawn_ack(
        app,
        "/api/desktop/notification-status".to_string(),
        serde_json::json!({ "mail_key": mail_key, "status": status }),
    );
}

pub fn acknowledge_startup_summary<R: Runtime>(app: &AppHandle<R>, id: String) {
    if id.is_empty()
        || !id
            .chars()
            .all(|character| character.is_ascii_alphanumeric() || matches!(character, '-' | '_'))
    {
        return;
    }
    spawn_ack(
        app,
        format!("/api/desktop/startup-summary/{id}/ack"),
        serde_json::json!({}),
    );
}

fn handle_stdout<R: Runtime>(app: &AppHandle<R>, generation: u64, token: &str, bytes: &[u8]) {
    if !app.state::<DesktopState>().is_current(generation) {
        return;
    }
    let line = String::from_utf8_lossy(bytes);
    let Some(json) = line.trim().strip_prefix(EVENT_PREFIX) else {
        return;
    };
    let Ok(event) = serde_json::from_str::<SidecarEvent>(json) else {
        return;
    };
    if event.event == "ready" {
        if let Some(base_url) = event.payload.get("base_url").and_then(Value::as_str) {
            if !allowed_base_url(base_url) {
                let _ = app.emit(
                    "qq-mail-event",
                    serde_json::json!({
                        "event": "watcher_status",
                        "payload": { "status": "invalid_sidecar_address" }
                    }),
                );
                return;
            }
            let connection = BackendConnection {
                base_url: base_url.to_string(),
                token: token.to_string(),
            };
            app.state::<DesktopState>()
                .set_connection(generation, connection.clone());
            let _ = app.emit("desktop-backend-ready", connection);
        }
    }
    notifications::handle_sidecar_event(app, &event.event, &event.payload);
    let _ = app.emit("qq-mail-event", event);
}

fn supervise<R: Runtime>(
    app: AppHandle<R>,
    generation: u64,
    token: String,
    mut events: tauri::async_runtime::Receiver<CommandEvent>,
) {
    tauri::async_runtime::spawn(async move {
        while let Some(event) = events.recv().await {
            match event {
                CommandEvent::Stdout(bytes) => {
                    handle_stdout(&app, generation, &token, &bytes);
                }
                CommandEvent::Stderr(_) => {
                    // Provider failures can contain message content. Raw stderr is drained but
                    // intentionally never copied into Tauri logs or frontend events.
                }
                CommandEvent::Error(_) => {
                    let _ = app.emit(
                        "qq-mail-event",
                        serde_json::json!({
                            "event": "watcher_status",
                            "payload": { "status": "sidecar_io_error" }
                        }),
                    );
                }
                CommandEvent::Terminated(payload) => {
                    let state = app.state::<DesktopState>();
                    let restart = state.restart_after_termination(generation);
                    let _ = app.emit(
                        "qq-mail-event",
                        serde_json::json!({
                            "event": "watcher_status",
                            "payload": {
                                "status": "sidecar_stopped",
                                "exit_code": payload.code
                            }
                        }),
                    );
                    if let Some((attempt, delay)) = restart {
                        let _ = app.emit(
                            "qq-mail-event",
                            serde_json::json!({
                                "event": "watcher_status",
                                "payload": {
                                    "status": "sidecar_restarting",
                                    "attempt": attempt,
                                    "delay_seconds": delay.as_secs()
                                }
                            }),
                        );
                        let app_for_restart = app.clone();
                        std::thread::spawn(move || {
                            std::thread::sleep(delay);
                            if app_for_restart
                                .state::<DesktopState>()
                                .is_current(generation)
                                && start(&app_for_restart).is_err()
                            {
                                let _ = app_for_restart.emit(
                                    "qq-mail-event",
                                    serde_json::json!({
                                        "event": "watcher_status",
                                        "payload": { "status": "sidecar_restart_failed" }
                                    }),
                                );
                            }
                        });
                    } else if state.is_current(generation) {
                        let _ = app.emit(
                            "qq-mail-event",
                            serde_json::json!({
                                "event": "watcher_status",
                                "payload": { "status": "sidecar_restart_exhausted" }
                            }),
                        );
                    }
                    break;
                }
                _ => {}
            }
        }
    });
}

fn watch_ready_timeout<R: Runtime>(app: AppHandle<R>, generation: u64) {
    std::thread::spawn(move || {
        std::thread::sleep(Duration::from_secs(15));
        let state = app.state::<DesktopState>();
        if !state.is_current(generation) || state.connection().is_some() {
            return;
        }
        let _ = app.emit(
            "qq-mail-event",
            serde_json::json!({
                "event": "watcher_status",
                "payload": { "status": "sidecar_ready_timeout" }
            }),
        );
        if let Some(child) = state.take_child() {
            let _ = child.kill();
        }
    });
}

fn start_managed<R: Runtime>(app: &AppHandle<R>) -> Result<(), String> {
    let state = app.state::<DesktopState>();
    if state.has_child() {
        return Ok(());
    }
    let data_dir = desktop_config::resolved_data_dir(app)?;
    std::fs::create_dir_all(&data_dir).map_err(|error| error.to_string())?;
    let token = uuid::Uuid::new_v4().simple().to_string();
    let (events, child) = build_command(app, &token, &data_dir)?
        .spawn()
        .map_err(|error| format!("failed to start Python sidecar: {error}"))?;
    let generation = state.begin_generation();
    state.set_child(generation, child);
    supervise(app.clone(), generation, token, events);
    watch_ready_timeout(app.clone(), generation);
    Ok(())
}

pub fn start<R: Runtime>(app: &AppHandle<R>) -> Result<(), String> {
    let state = app.state::<DesktopState>();
    let _lifecycle_guard = state.lock_lifecycle();
    start_managed(app)
}

fn stop_managed<R: Runtime>(app: &AppHandle<R>) {
    let state = app.state::<DesktopState>();
    let connection = state.connection();
    state.mark_stopping();
    let graceful_shutdown_requested = connection.is_some_and(|connection| {
        post_json_to_with_timeout(
            &connection,
            "/api/desktop/shutdown",
            &serde_json::json!({}),
            SHUTDOWN_HTTP_TIMEOUT,
        )
        .is_ok()
    });
    if graceful_shutdown_requested && state.wait_for_child_exit(SHUTDOWN_GRACE_PERIOD) {
        return;
    }
    if let Some(child) = state.take_child() {
        let _ = child.kill();
    }
}

pub fn stop<R: Runtime>(app: &AppHandle<R>) {
    let state = app.state::<DesktopState>();
    let _lifecycle_guard = state.lock_lifecycle();
    stop_managed(app);
}

pub fn restart<R: Runtime>(app: &AppHandle<R>) -> Result<(), String> {
    let state = app.state::<DesktopState>();
    let _lifecycle_guard = state.lock_lifecycle();
    stop_managed(app);
    state.reset_restart_attempts();
    start_managed(app)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn accepts_only_loopback_dynamic_http_urls() {
        assert!(allowed_base_url("http://127.0.0.1:49152"));
        assert!(!allowed_base_url("http://localhost:49152"));
        assert!(!allowed_base_url("http://0.0.0.0:49152"));
        assert!(!allowed_base_url("https://127.0.0.1:49152"));
        assert!(!allowed_base_url("http://127.0.0.1:0"));
        assert!(!allowed_base_url("http://127.0.0.1:49152/path"));
    }
}
