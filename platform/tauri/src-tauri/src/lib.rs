use serde::{Deserialize, Serialize};
use std::{fs, sync::Mutex};
use tauri::{
    menu::{Menu, MenuItem},
    tray::TrayIconBuilder,
    AppHandle, Emitter, Manager, Runtime, WebviewUrl, WebviewWindowBuilder,
};
use tauri_plugin_autostart::{MacosLauncher, ManagerExt};

mod desktop_config;
mod notifications;
mod sidecar;

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub(crate) enum NavigationTarget {
    Summary,
    Mail { uid: String },
}

#[derive(Default)]
struct NavigationState(Mutex<Option<NavigationTarget>>);

impl NavigationState {
    fn set(&self, target: NavigationTarget) {
        if let Ok(mut pending) = self.0.lock() {
            *pending = Some(target);
        }
    }

    fn take(&self) -> Option<NavigationTarget> {
        self.0.lock().ok().and_then(|mut pending| pending.take())
    }
}

fn reveal_main_window<R: Runtime>(app: &AppHandle<R>, uid: Option<String>) -> Result<(), String> {
    let window = app
        .get_webview_window("main")
        .ok_or_else(|| "main window is unavailable".to_string())?;
    window.show().map_err(|error| error.to_string())?;
    window.unminimize().map_err(|error| error.to_string())?;
    window.set_focus().map_err(|error| error.to_string())?;
    if let Some(uid) = uid {
        navigate_main_window(app, NavigationTarget::Mail { uid })?;
    }
    Ok(())
}

pub(crate) fn navigate_main_window<R: Runtime>(
    app: &AppHandle<R>,
    target: NavigationTarget,
) -> Result<(), String> {
    app.state::<NavigationState>().set(target);
    let window = app
        .get_webview_window("main")
        .ok_or_else(|| "main window is unavailable".to_string())?;
    window.show().map_err(|error| error.to_string())?;
    window.unminimize().map_err(|error| error.to_string())?;
    window.set_focus().map_err(|error| error.to_string())?;
    app.emit("desktop-navigation", ())
        .map_err(|error| error.to_string())
}

#[tauri::command]
fn show_main_window(app: AppHandle, uid: Option<String>) -> Result<(), String> {
    reveal_main_window(&app, uid)
}

#[tauri::command]
fn take_pending_navigation(state: tauri::State<'_, NavigationState>) -> Option<NavigationTarget> {
    state.take()
}

#[tauri::command]
fn request_desktop_sync(app: AppHandle) -> Result<(), String> {
    app.emit("desktop-request-sync", ())
        .map_err(|error| error.to_string())
}

#[tauri::command]
fn backend_connection(
    state: tauri::State<'_, sidecar::DesktopState>,
) -> Option<sidecar::BackendConnection> {
    state.connection()
}

#[tauri::command]
fn desktop_config(app: AppHandle) -> Result<desktop_config::DesktopConfigView, String> {
    desktop_config::get(&app)
}

#[tauri::command]
fn save_desktop_config(
    app: AppHandle,
    input: desktop_config::DesktopConfigInput,
) -> Result<desktop_config::DesktopConfigView, String> {
    let view = desktop_config::save(&app, input)?;
    sidecar::restart(&app).map_err(|error| format!("配置已保存，但后台重启失败：{error}"))?;
    Ok(view)
}

#[tauri::command]
fn clear_desktop_user_data(
    app: AppHandle,
) -> Result<desktop_config::UserDataCleanupReport, String> {
    sidecar::stop(&app);
    let _ = app.autolaunch().disable();
    let report = desktop_config::clear_user_data(&app)?;
    app.emit(
        "qq-mail-event",
        serde_json::json!({
            "event": "watcher_status",
            "payload": { "status": "user_data_cleared" }
        }),
    )
    .map_err(|error| error.to_string())?;
    Ok(report)
}

#[tauri::command]
fn desktop_storage_locations(app: AppHandle) -> Result<desktop_config::StorageLocations, String> {
    desktop_config::storage_locations(&app)
}

#[tauri::command]
fn choose_storage_directory(app: AppHandle) -> Result<Option<String>, String> {
    desktop_config::choose_storage_root(&app)
}

#[tauri::command]
fn migrate_desktop_data_directory(
    app: AppHandle,
    input: desktop_config::StorageRootInput,
) -> Result<desktop_config::DataDirectoryMigrationReport, String> {
    sidecar::stop(&app);
    let report = desktop_config::migrate_data_directory(&app, input)?;
    sidecar::restart(&app).map_err(|error| format!("数据目录已切换，但后台重启失败：{error}"))?;
    Ok(report)
}

#[tauri::command]
fn reset_desktop_data_directory(
    app: AppHandle,
) -> Result<desktop_config::DataDirectoryMigrationReport, String> {
    sidecar::stop(&app);
    let report = desktop_config::reset_data_directory(&app)?;
    sidecar::restart(&app)
        .map_err(|error| format!("数据目录已恢复默认，但后台重启失败：{error}"))?;
    Ok(report)
}

#[tauri::command]
fn set_webview_data_directory(
    app: AppHandle,
    input: desktop_config::StorageRootInput,
) -> Result<desktop_config::StorageLocations, String> {
    desktop_config::set_webview_data_directory(&app, input)
}

#[tauri::command]
fn reset_webview_data_directory(
    app: AppHandle,
) -> Result<desktop_config::StorageLocations, String> {
    desktop_config::reset_webview_data_directory(&app)
}

#[tauri::command]
fn open_storage_directory(path: String) -> Result<(), String> {
    desktop_config::open_directory(path)
}

#[tauri::command]
fn restart_backend(app: AppHandle) -> Result<(), String> {
    sidecar::restart(&app)
}

#[tauri::command]
fn open_devtools(app: AppHandle, password: String) -> Result<(), String> {
    if password != "iopp" {
        return Err("开发者控制台密码不正确".to_string());
    }
    let window = app
        .get_webview_window("main")
        .ok_or_else(|| "main window is unavailable".to_string())?;
    window.open_devtools();
    Ok(())
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct AutostartStatus {
    enabled: bool,
}

#[tauri::command]
fn autostart_status(app: AppHandle) -> Result<AutostartStatus, String> {
    app.autolaunch()
        .is_enabled()
        .map(|enabled| AutostartStatus { enabled })
        .map_err(|error| error.to_string())
}

#[tauri::command]
fn set_autostart(app: AppHandle, enabled: bool) -> Result<AutostartStatus, String> {
    if enabled {
        app.autolaunch()
            .enable()
            .map_err(|error| error.to_string())?;
    } else {
        app.autolaunch()
            .disable()
            .map_err(|error| error.to_string())?;
    }
    Ok(AutostartStatus { enabled })
}

fn enable_autostart_once<R: Runtime>(app: &AppHandle<R>) -> Result<(), String> {
    let config_dir = app
        .path()
        .app_config_dir()
        .map_err(|error| error.to_string())?;
    let marker = config_dir.join("autostart-initialized");
    if marker.exists() {
        return Ok(());
    }
    if !app
        .autolaunch()
        .is_enabled()
        .map_err(|error| error.to_string())?
    {
        app.autolaunch()
            .enable()
            .map_err(|error| error.to_string())?;
    }
    fs::create_dir_all(config_dir).map_err(|error| error.to_string())?;
    fs::write(marker, b"enabled-by-default\n").map_err(|error| error.to_string())
}

fn create_tray<R: Runtime>(app: &AppHandle<R>) -> tauri::Result<()> {
    let open = MenuItem::with_id(app, "open", "打开 MiaoGent", true, None::<&str>)?;
    let sync = MenuItem::with_id(app, "sync", "立即同步", true, None::<&str>)?;
    let quit = MenuItem::with_id(app, "quit", "退出", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&open, &sync, &quit])?;

    let mut builder = TrayIconBuilder::with_id("qq-mail-agent-tray")
        .menu(&menu)
        .tooltip("MiaoGent")
        .on_menu_event(|app, event| match event.id.as_ref() {
            "open" => {
                let _ = reveal_main_window(app, None);
            }
            "sync" => {
                let _ = app.emit("desktop-request-sync", ());
            }
            "quit" => {
                sidecar::stop(app);
                app.exit(0);
            }
            _ => {}
        });

    if let Some(icon) = app.default_window_icon() {
        builder = builder.icon(icon.clone());
    }
    builder.build(app)?;
    Ok(())
}

fn show_on_manual_launch<R: Runtime>(app: &AppHandle<R>) -> Result<(), Box<dyn std::error::Error>> {
    let launched_by_autostart = std::env::args().any(|argument| argument == "--autostart");
    if !launched_by_autostart {
        reveal_main_window(app, None)?;
    }
    Ok(())
}

fn create_main_window<R: Runtime>(app: &AppHandle<R>) -> tauri::Result<()> {
    let mut builder = WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
        .title("MiaoGent")
        .inner_size(1440.0, 900.0)
        .min_inner_size(1080.0, 720.0)
        .center()
        .visible(false)
        .resizable(true)
        .fullscreen(false);

    match desktop_config::resolved_webview_data_dir(app) {
        Ok(path) => {
            if let Err(error) = fs::create_dir_all(&path) {
                let _ = app.emit(
                    "qq-mail-event",
                    serde_json::json!({
                        "event": "watcher_status",
                        "payload": { "status": "webview_data_dir_failed", "error": error.to_string() }
                    }),
                );
            } else {
                builder = builder.data_directory(path);
            }
        }
        Err(error) => {
            let _ = app.emit(
                "qq-mail-event",
                serde_json::json!({
                    "event": "watcher_status",
                    "payload": { "status": "webview_data_dir_failed", "error": error }
                }),
            );
        }
    }

    builder.build().map(|_| ())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .manage(sidecar::DesktopState::default())
        .manage(NavigationState::default())
        .manage(notifications::NotificationState::default())
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            let _ = reveal_main_window(app, None);
        }))
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_process::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_autostart::init(
            MacosLauncher::LaunchAgent,
            Some(vec!["--autostart"]),
        ))
        .plugin(tauri_plugin_log::Builder::default().build())
        .invoke_handler(tauri::generate_handler![
            show_main_window,
            take_pending_navigation,
            request_desktop_sync,
            backend_connection,
            desktop_config,
            save_desktop_config,
            clear_desktop_user_data,
            desktop_storage_locations,
            choose_storage_directory,
            migrate_desktop_data_directory,
            reset_desktop_data_directory,
            set_webview_data_directory,
            reset_webview_data_directory,
            open_storage_directory,
            restart_backend,
            open_devtools,
            autostart_status,
            set_autostart
        ])
        .setup(|app| {
            create_main_window(app.handle())?;
            create_tray(app.handle())?;
            if let Err(error) = enable_autostart_once(app.handle()) {
                let _ = app.emit(
                    "qq-mail-event",
                    serde_json::json!({
                        "event": "watcher_status",
                        "payload": { "status": "autostart_setup_failed", "error": error }
                    }),
                );
            }
            show_on_manual_launch(app.handle())?;
            if let Err(error) = sidecar::start(app.handle()) {
                let _ = app.emit(
                    "qq-mail-event",
                    serde_json::json!({
                        "event": "watcher_status",
                        "payload": { "status": "sidecar_start_failed", "error": error }
                    }),
                );
            }
            Ok(())
        })
        .on_window_event(|window, event| {
            if window.label() != "main" {
                return;
            }
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let _ = window.hide();
            }
        })
        .build(tauri::generate_context!())
        .expect("error while building MiaoGent desktop application");

    app.run(|app, event| {
        if matches!(
            event,
            tauri::RunEvent::Exit | tauri::RunEvent::ExitRequested { .. }
        ) {
            sidecar::stop(app);
        }
    });
}
