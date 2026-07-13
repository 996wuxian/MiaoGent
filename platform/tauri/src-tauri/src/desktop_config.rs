use serde::{Deserialize, Serialize};
use std::{
    collections::{BTreeSet, HashMap},
    fs,
    path::{Component, Path, PathBuf},
};
use tauri::{AppHandle, Manager, Runtime};

const CONFIG_FILE: &str = "desktop-config.json";
const CREDENTIAL_SERVICE: &str = "com.wuxian.qqmailagent";
const MAIL_AUTH_CREDENTIAL: &str = "qq-mail-auth-code";
const DEEPSEEK_CREDENTIAL: &str = "deepseek-api-key";
const APP_DIR_NAME: &str = "com.wuxian.qqmailagent";
const CUSTOM_STORAGE_DIR_NAME: &str = "MiaoGent";
const CUSTOM_DATA_DIR_NAME: &str = "data";
const CUSTOM_WEBVIEW_DIR_NAME: &str = "webview";
const STATE_DB_FILE: &str = "state.sqlite3";

#[derive(Clone, Copy, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum MailProvider {
    Qq,
    #[serde(rename = "netease_163")]
    Netease163,
}

impl Default for MailProvider {
    fn default() -> Self {
        Self::Qq
    }
}

impl MailProvider {
    fn address_label(self) -> &'static str {
        match self {
            Self::Qq => "QQ 邮箱地址",
            Self::Netease163 => "163 邮箱地址",
        }
    }

    fn auth_code_label(self) -> &'static str {
        match self {
            Self::Qq => "QQ 授权码",
            Self::Netease163 => "163 授权码",
        }
    }

    fn default_imap_host(self) -> &'static str {
        match self {
            Self::Qq => "imap.qq.com",
            Self::Netease163 => "imap.163.com",
        }
    }

    fn default_smtp_host(self) -> &'static str {
        match self {
            Self::Qq => "smtp.qq.com",
            Self::Netease163 => "smtp.163.com",
        }
    }
}

fn default_mail_provider() -> MailProvider {
    MailProvider::default()
}

fn default_imap_host() -> String {
    MailProvider::default().default_imap_host().to_string()
}

fn default_imap_port() -> u16 {
    993
}

fn default_smtp_host() -> String {
    MailProvider::default().default_smtp_host().to_string()
}

fn default_smtp_port() -> u16 {
    465
}

fn default_deepseek_base_url() -> String {
    "https://api.deepseek.com".to_string()
}

fn default_deepseek_model() -> String {
    "deepseek-chat".to_string()
}

fn default_deepseek_timeout() -> u16 {
    45
}

fn default_privacy_protection_enabled() -> bool {
    true
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(default, rename_all = "camelCase")]
struct StoredDesktopConfig {
    #[serde(default = "default_mail_provider")]
    mail_provider: MailProvider,
    mail_address: String,
    #[serde(default = "default_imap_host")]
    imap_host: String,
    #[serde(default = "default_imap_port")]
    imap_port: u16,
    #[serde(default = "default_smtp_host")]
    smtp_host: String,
    #[serde(default = "default_smtp_port")]
    smtp_port: u16,
    #[serde(default = "default_deepseek_base_url")]
    deepseek_base_url: String,
    #[serde(default = "default_deepseek_model")]
    deepseek_model: String,
    #[serde(default = "default_deepseek_timeout")]
    deepseek_timeout_seconds: u16,
    #[serde(default = "default_privacy_protection_enabled")]
    privacy_protection_enabled: bool,
    #[serde(default)]
    data_root: Option<PathBuf>,
    #[serde(default)]
    webview_data_root: Option<PathBuf>,
}

impl Default for StoredDesktopConfig {
    fn default() -> Self {
        Self {
            mail_provider: default_mail_provider(),
            mail_address: String::new(),
            imap_host: default_imap_host(),
            imap_port: default_imap_port(),
            smtp_host: default_smtp_host(),
            smtp_port: default_smtp_port(),
            deepseek_base_url: default_deepseek_base_url(),
            deepseek_model: default_deepseek_model(),
            deepseek_timeout_seconds: default_deepseek_timeout(),
            privacy_protection_enabled: default_privacy_protection_enabled(),
            data_root: None,
            webview_data_root: None,
        }
    }
}

#[derive(Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct DesktopConfigInput {
    mail_provider: MailProvider,
    mail_address: String,
    imap_host: String,
    imap_port: u16,
    smtp_host: String,
    smtp_port: u16,
    deepseek_base_url: String,
    deepseek_model: String,
    deepseek_timeout_seconds: u16,
    #[serde(default = "default_privacy_protection_enabled")]
    privacy_protection_enabled: bool,
    mail_auth_code: Option<String>,
    deepseek_api_key: Option<String>,
    #[serde(default)]
    clear_mail_auth_code: bool,
    #[serde(default)]
    clear_deepseek_api_key: bool,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DesktopConfigView {
    mail_provider: MailProvider,
    mail_address: String,
    imap_host: String,
    imap_port: u16,
    smtp_host: String,
    smtp_port: u16,
    deepseek_base_url: String,
    deepseek_model: String,
    deepseek_timeout_seconds: u16,
    privacy_protection_enabled: bool,
    has_mail_auth_code: bool,
    has_deepseek_api_key: bool,
    secret_storage: &'static str,
    data_directory: String,
    data_directory_root: Option<String>,
    is_default_data_directory: bool,
    webview_data_directory: String,
    webview_data_directory_root: Option<String>,
    is_default_webview_data_directory: bool,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct UserDataCleanupReport {
    removed_paths: Vec<String>,
    missing_paths: Vec<String>,
    failed_paths: Vec<UserDataCleanupFailure>,
    cleared_credentials: bool,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct UserDataCleanupFailure {
    path: String,
    error: String,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct StorageRootInput {
    root: String,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct StorageLocations {
    data_directory: String,
    data_directory_root: Option<String>,
    default_data_directory: String,
    is_default_data_directory: bool,
    webview_data_directory: String,
    webview_data_directory_root: Option<String>,
    default_webview_data_directory: String,
    is_default_webview_data_directory: bool,
    webview_change_requires_restart: bool,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DataDirectoryMigrationReport {
    previous_directory: String,
    current_directory: String,
    copied_files: Vec<String>,
    skipped_files: Vec<String>,
}

fn config_path<R: Runtime>(app: &AppHandle<R>) -> Result<PathBuf, String> {
    app.path()
        .app_config_dir()
        .map(|directory| directory.join(CONFIG_FILE))
        .map_err(|error| format!("无法定位桌面配置目录：{error}"))
}

fn load_stored<R: Runtime>(app: &AppHandle<R>) -> Result<StoredDesktopConfig, String> {
    let path = config_path(app)?;
    if !path.exists() {
        return Ok(StoredDesktopConfig::default());
    }
    let bytes = fs::read(&path).map_err(|error| format!("无法读取桌面配置：{error}"))?;
    serde_json::from_slice(&bytes).map_err(|error| format!("桌面配置格式无效：{error}"))
}

fn save_stored<R: Runtime>(app: &AppHandle<R>, config: &StoredDesktopConfig) -> Result<(), String> {
    let path = config_path(app)?;
    let parent = path
        .parent()
        .ok_or_else(|| "桌面配置路径无父目录".to_string())?;
    fs::create_dir_all(parent).map_err(|error| format!("无法创建桌面配置目录：{error}"))?;
    let bytes = serde_json::to_vec_pretty(config)
        .map_err(|error| format!("无法序列化桌面配置：{error}"))?;
    fs::write(path, bytes).map_err(|error| format!("无法保存桌面配置：{error}"))
}

fn validate(config: &StoredDesktopConfig) -> Result<(), String> {
    let address = config.mail_address.trim();
    if !address.is_empty() && (!address.contains('@') || address.chars().any(char::is_whitespace)) {
        return Err(format!(
            "{}格式不正确",
            config.mail_provider.address_label()
        ));
    }
    if config.imap_host.trim().is_empty() || config.smtp_host.trim().is_empty() {
        return Err("IMAP/SMTP 主机不能为空".to_string());
    }
    if config.imap_port == 0 || config.smtp_port == 0 {
        return Err("IMAP/SMTP 端口必须大于 0".to_string());
    }
    if !config.deepseek_base_url.starts_with("https://") {
        return Err("DeepSeek 地址必须使用 https://".to_string());
    }
    if config.deepseek_model.trim().is_empty() {
        return Err("DeepSeek 模型不能为空".to_string());
    }
    if !(5..=300).contains(&config.deepseek_timeout_seconds) {
        return Err("DeepSeek 超时必须在 5 到 300 秒之间".to_string());
    }
    Ok(())
}

#[cfg(windows)]
fn credential(name: &str) -> Result<keyring::Entry, String> {
    keyring::Entry::new(CREDENTIAL_SERVICE, name)
        .map_err(|error| format!("无法访问 Windows 凭据管理器：{error}"))
}

#[cfg(windows)]
fn read_secret(name: &str) -> Result<Option<String>, String> {
    match credential(name)?.get_password() {
        Ok(value) => Ok(Some(value)),
        Err(keyring::Error::NoEntry) => Ok(None),
        Err(error) => Err(format!("无法读取 Windows 凭据：{error}")),
    }
}

#[cfg(not(windows))]
fn read_secret(_name: &str) -> Result<Option<String>, String> {
    Ok(None)
}

#[cfg(windows)]
fn set_secret(name: &str, value: &str) -> Result<(), String> {
    credential(name)?
        .set_password(value)
        .map_err(|error| format!("无法保存 Windows 凭据：{error}"))
}

#[cfg(not(windows))]
fn set_secret(_name: &str, _value: &str) -> Result<(), String> {
    Err("桌面密钥存储当前仅支持 Windows".to_string())
}

#[cfg(windows)]
fn clear_secret(name: &str) -> Result<(), String> {
    match credential(name)?.delete_credential() {
        Ok(()) | Err(keyring::Error::NoEntry) => Ok(()),
        Err(error) => Err(format!("无法清除 Windows 凭据：{error}")),
    }
}

#[cfg(not(windows))]
fn clear_secret(_name: &str) -> Result<(), String> {
    Err("桌面密钥存储当前仅支持 Windows".to_string())
}

pub fn clear_secrets() -> Result<(), String> {
    clear_secret(MAIL_AUTH_CREDENTIAL)?;
    clear_secret(DEEPSEEK_CREDENTIAL)
}

fn view<R: Runtime>(
    app: &AppHandle<R>,
    config: StoredDesktopConfig,
) -> Result<DesktopConfigView, String> {
    let locations = locations_from_config(app, &config)?;
    Ok(DesktopConfigView {
        mail_provider: config.mail_provider,
        mail_address: config.mail_address,
        imap_host: config.imap_host,
        imap_port: config.imap_port,
        smtp_host: config.smtp_host,
        smtp_port: config.smtp_port,
        deepseek_base_url: config.deepseek_base_url,
        deepseek_model: config.deepseek_model,
        deepseek_timeout_seconds: config.deepseek_timeout_seconds,
        privacy_protection_enabled: config.privacy_protection_enabled,
        has_mail_auth_code: read_secret(MAIL_AUTH_CREDENTIAL)?.is_some(),
        has_deepseek_api_key: read_secret(DEEPSEEK_CREDENTIAL)?.is_some(),
        secret_storage: "windows_credential_manager",
        data_directory: locations.data_directory,
        data_directory_root: locations.data_directory_root,
        is_default_data_directory: locations.is_default_data_directory,
        webview_data_directory: locations.webview_data_directory,
        webview_data_directory_root: locations.webview_data_directory_root,
        is_default_webview_data_directory: locations.is_default_webview_data_directory,
    })
}

pub fn get<R: Runtime>(app: &AppHandle<R>) -> Result<DesktopConfigView, String> {
    view(app, load_stored(app)?)
}

pub fn save<R: Runtime>(
    app: &AppHandle<R>,
    input: DesktopConfigInput,
) -> Result<DesktopConfigView, String> {
    if input.clear_mail_auth_code && input.mail_auth_code.is_some() {
        return Err(format!(
            "不能同时更新和清除{}",
            input.mail_provider.auth_code_label()
        ));
    }
    if input.clear_deepseek_api_key && input.deepseek_api_key.is_some() {
        return Err("不能同时更新和清除 DeepSeek API Key".to_string());
    }

    let current = load_stored(app)?;
    let config = StoredDesktopConfig {
        mail_provider: input.mail_provider,
        mail_address: input.mail_address.trim().to_string(),
        imap_host: input.imap_host.trim().to_string(),
        imap_port: input.imap_port,
        smtp_host: input.smtp_host.trim().to_string(),
        smtp_port: input.smtp_port,
        deepseek_base_url: input.deepseek_base_url.trim_end_matches('/').to_string(),
        deepseek_model: input.deepseek_model.trim().to_string(),
        deepseek_timeout_seconds: input.deepseek_timeout_seconds,
        privacy_protection_enabled: input.privacy_protection_enabled,
        data_root: current.data_root,
        webview_data_root: current.webview_data_root,
    };
    validate(&config)?;

    if input.clear_mail_auth_code {
        clear_secret(MAIL_AUTH_CREDENTIAL)?;
    } else if let Some(value) = input.mail_auth_code {
        let value = value.trim();
        if value.is_empty() {
            return Err(format!(
                "{}不能为空",
                config.mail_provider.auth_code_label()
            ));
        }
        set_secret(MAIL_AUTH_CREDENTIAL, value)?;
    }
    if input.clear_deepseek_api_key {
        clear_secret(DEEPSEEK_CREDENTIAL)?;
    } else if let Some(value) = input.deepseek_api_key {
        let value = value.trim();
        if value.is_empty() {
            return Err("DeepSeek API Key 不能为空".to_string());
        }
        set_secret(DEEPSEEK_CREDENTIAL, value)?;
    }

    save_stored(app, &config)?;
    view(app, config)
}

pub fn sidecar_environment<R: Runtime>(
    app: &AppHandle<R>,
) -> Result<HashMap<String, String>, String> {
    let config = load_stored(app)?;
    validate(&config)?;
    let mut environment = HashMap::from([
        ("QQ_MAIL_IMAP_HOST".to_string(), config.imap_host),
        (
            "QQ_MAIL_IMAP_PORT".to_string(),
            config.imap_port.to_string(),
        ),
        ("QQ_MAIL_SMTP_HOST".to_string(), config.smtp_host),
        (
            "QQ_MAIL_SMTP_PORT".to_string(),
            config.smtp_port.to_string(),
        ),
        ("DEEPSEEK_BASE_URL".to_string(), config.deepseek_base_url),
        ("DEEPSEEK_MODEL".to_string(), config.deepseek_model),
        (
            "DEEPSEEK_TIMEOUT_SECONDS".to_string(),
            config.deepseek_timeout_seconds.to_string(),
        ),
        (
            "MIAOGENT_PRIVACY_PROTECTION_ENABLED".to_string(),
            if config.privacy_protection_enabled {
                "1".to_string()
            } else {
                "0".to_string()
            },
        ),
    ]);
    if !config.mail_address.is_empty() {
        environment.insert("QQ_MAIL_ADDRESS".to_string(), config.mail_address);
    }
    if let Some(value) = read_secret(MAIL_AUTH_CREDENTIAL)? {
        environment.insert("QQ_MAIL_AUTH_CODE".to_string(), value);
    }
    if let Some(value) = read_secret(DEEPSEEK_CREDENTIAL)? {
        environment.insert("DEEPSEEK_API_KEY".to_string(), value);
    }
    Ok(environment)
}

pub fn resolved_data_dir<R: Runtime>(app: &AppHandle<R>) -> Result<PathBuf, String> {
    let config = load_stored(app)?;
    resolve_data_dir_from_config(app, &config)
}

pub fn resolved_webview_data_dir<R: Runtime>(app: &AppHandle<R>) -> Result<PathBuf, String> {
    let config = load_stored(app)?;
    resolve_webview_data_dir_from_config(app, &config)
}

pub fn storage_locations<R: Runtime>(app: &AppHandle<R>) -> Result<StorageLocations, String> {
    let config = load_stored(app)?;
    locations_from_config(app, &config)
}

pub fn choose_storage_root<R: Runtime>(app: &AppHandle<R>) -> Result<Option<String>, String> {
    use tauri_plugin_dialog::DialogExt;
    let folder = app
        .dialog()
        .file()
        .blocking_pick_folder()
        .map(|path| {
            path.into_path()
                .map_err(|error| format!("无法读取所选目录：{error}"))
        })
        .transpose()?;
    folder
        .map(|path| normalize_root(&path).map(|value| display_path(&value)))
        .transpose()
}

pub fn migrate_data_directory<R: Runtime>(
    app: &AppHandle<R>,
    input: StorageRootInput,
) -> Result<DataDirectoryMigrationReport, String> {
    let mut config = load_stored(app)?;
    let previous_directory = resolve_data_dir_from_config(app, &config)?;
    let new_root = validate_custom_root(&PathBuf::from(input.root.trim()), app)?;
    let next_directory = custom_data_dir(&new_root);
    if same_path(&previous_directory, &next_directory) {
        config.data_root = Some(new_root);
        save_stored(app, &config)?;
        return Ok(DataDirectoryMigrationReport {
            previous_directory: display_path(&previous_directory),
            current_directory: display_path(&next_directory),
            copied_files: Vec::new(),
            skipped_files: Vec::new(),
        });
    }

    fs::create_dir_all(&next_directory)
        .map_err(|error| format!("无法创建新的业务数据目录：{error}"))?;
    ensure_storage_target(&next_directory, CUSTOM_DATA_DIR_NAME)?;
    let (copied_files, skipped_files) = copy_data_files(&previous_directory, &next_directory)?;
    config.data_root = Some(new_root);
    save_stored(app, &config)?;
    Ok(DataDirectoryMigrationReport {
        previous_directory: display_path(&previous_directory),
        current_directory: display_path(&next_directory),
        copied_files,
        skipped_files,
    })
}

pub fn reset_data_directory<R: Runtime>(
    app: &AppHandle<R>,
) -> Result<DataDirectoryMigrationReport, String> {
    let mut config = load_stored(app)?;
    let previous_directory = resolve_data_dir_from_config(app, &config)?;
    config.data_root = None;
    let next_directory = resolve_data_dir_from_config(app, &config)?;
    if same_path(&previous_directory, &next_directory) {
        save_stored(app, &config)?;
        return Ok(DataDirectoryMigrationReport {
            previous_directory: display_path(&previous_directory),
            current_directory: display_path(&next_directory),
            copied_files: Vec::new(),
            skipped_files: Vec::new(),
        });
    }
    fs::create_dir_all(&next_directory)
        .map_err(|error| format!("无法创建默认业务数据目录：{error}"))?;
    let (copied_files, skipped_files) = copy_data_files(&previous_directory, &next_directory)?;
    save_stored(app, &config)?;
    Ok(DataDirectoryMigrationReport {
        previous_directory: display_path(&previous_directory),
        current_directory: display_path(&next_directory),
        copied_files,
        skipped_files,
    })
}

pub fn set_webview_data_directory<R: Runtime>(
    app: &AppHandle<R>,
    input: StorageRootInput,
) -> Result<StorageLocations, String> {
    let mut config = load_stored(app)?;
    let root = validate_custom_root(&PathBuf::from(input.root.trim()), app)?;
    fs::create_dir_all(custom_webview_data_dir(&root))
        .map_err(|error| format!("无法创建 WebView 缓存目录：{error}"))?;
    config.webview_data_root = Some(root);
    save_stored(app, &config)?;
    locations_from_config(app, &config)
}

pub fn reset_webview_data_directory<R: Runtime>(
    app: &AppHandle<R>,
) -> Result<StorageLocations, String> {
    let mut config = load_stored(app)?;
    config.webview_data_root = None;
    save_stored(app, &config)?;
    locations_from_config(app, &config)
}

pub fn open_directory(path: String) -> Result<(), String> {
    let directory = normalize_root(&PathBuf::from(path.trim()))?;
    if !directory.exists() {
        return Err("目录不存在".to_string());
    }
    if !directory.is_dir() {
        return Err("目标不是目录".to_string());
    }
    #[cfg(windows)]
    {
        std::process::Command::new("explorer.exe")
            .arg(&directory)
            .spawn()
            .map(|_| ())
            .map_err(|error| format!("无法打开目录：{error}"))
    }
    #[cfg(not(windows))]
    {
        let _ = directory;
        Err("打开目录当前仅支持 Windows 桌面端".to_string())
    }
}

fn locations_from_config<R: Runtime>(
    app: &AppHandle<R>,
    config: &StoredDesktopConfig,
) -> Result<StorageLocations, String> {
    let default_data_directory = default_data_dir(app)?;
    let data_directory = resolve_data_dir_from_config(app, config)?;
    let default_webview_data_directory = default_webview_data_dir(app)?;
    let webview_data_directory = resolve_webview_data_dir_from_config(app, config)?;
    Ok(StorageLocations {
        data_directory: display_path(&data_directory),
        data_directory_root: config.data_root.as_ref().map(|path| display_path(path)),
        default_data_directory: display_path(&default_data_directory),
        is_default_data_directory: config.data_root.is_none(),
        webview_data_directory: display_path(&webview_data_directory),
        webview_data_directory_root: config
            .webview_data_root
            .as_ref()
            .map(|path| display_path(path)),
        default_webview_data_directory: display_path(&default_webview_data_directory),
        is_default_webview_data_directory: config.webview_data_root.is_none(),
        webview_change_requires_restart: true,
    })
}

fn resolve_data_dir_from_config<R: Runtime>(
    app: &AppHandle<R>,
    config: &StoredDesktopConfig,
) -> Result<PathBuf, String> {
    match &config.data_root {
        Some(root) => Ok(custom_data_dir(&normalize_root(root)?)),
        None => default_data_dir(app),
    }
}

fn resolve_webview_data_dir_from_config<R: Runtime>(
    app: &AppHandle<R>,
    config: &StoredDesktopConfig,
) -> Result<PathBuf, String> {
    match &config.webview_data_root {
        Some(root) => Ok(custom_webview_data_dir(&normalize_root(root)?)),
        None => default_webview_data_dir(app),
    }
}

fn default_data_dir<R: Runtime>(app: &AppHandle<R>) -> Result<PathBuf, String> {
    app.path().app_data_dir().map_err(|error| error.to_string())
}

fn default_webview_data_dir<R: Runtime>(app: &AppHandle<R>) -> Result<PathBuf, String> {
    app.path()
        .app_local_data_dir()
        .map_err(|error| error.to_string())
}

fn custom_data_dir(root: &Path) -> PathBuf {
    root.join(CUSTOM_STORAGE_DIR_NAME)
        .join(CUSTOM_DATA_DIR_NAME)
}

fn custom_webview_data_dir(root: &Path) -> PathBuf {
    root.join(CUSTOM_STORAGE_DIR_NAME)
        .join(CUSTOM_WEBVIEW_DIR_NAME)
}

fn validate_custom_root<R: Runtime>(root: &Path, app: &AppHandle<R>) -> Result<PathBuf, String> {
    let root = normalize_root(root)?;
    validate_custom_root_without_app(&root)?;

    let executable = app
        .path()
        .executable_dir()
        .map_err(|error| format!("无法定位安装目录：{error}"))?;
    if path_contains(&executable, &root) || path_contains(&root, &executable) {
        return Err("存储位置不能选择应用安装目录或其父目录".to_string());
    }
    Ok(root)
}

fn validate_custom_root_without_app(root: &Path) -> Result<(), String> {
    if !root.is_absolute() {
        return Err("存储位置必须是绝对路径".to_string());
    }
    if root.parent().is_none() {
        return Err("存储位置不能是磁盘根目录".to_string());
    }
    let text = root.to_string_lossy().to_ascii_lowercase();
    for blocked in [
        r"c:\windows",
        r"c:\program files",
        r"c:\program files (x86)",
    ] {
        if text == blocked || text.starts_with(&format!("{blocked}\\")) {
            return Err("存储位置不能选择 Windows 或 Program Files 系统目录".to_string());
        }
    }
    if root
        .components()
        .any(|component| matches!(component, Component::ParentDir))
    {
        return Err("存储位置不能包含上级目录片段".to_string());
    }
    Ok(())
}

fn ensure_storage_target(path: &Path, expected_leaf: &str) -> Result<(), String> {
    let leaf = path
        .file_name()
        .and_then(|value| value.to_str())
        .ok_or_else(|| "存储目标缺少目录名".to_string())?;
    if leaf != expected_leaf {
        return Err(format!("存储目标必须是 {expected_leaf} 目录"));
    }
    let parent = path
        .parent()
        .and_then(|value| value.file_name())
        .and_then(|value| value.to_str())
        .ok_or_else(|| "存储目标缺少 MiaoGent 父目录".to_string())?;
    if parent != CUSTOM_STORAGE_DIR_NAME {
        return Err(format!("存储目标必须位于 {CUSTOM_STORAGE_DIR_NAME} 目录下"));
    }
    Ok(())
}

fn copy_data_files(from: &Path, to: &Path) -> Result<(Vec<String>, Vec<String>), String> {
    ensure_storage_target(to, CUSTOM_DATA_DIR_NAME)?;
    let mut copied = Vec::new();
    let mut skipped = Vec::new();
    if !from.exists() {
        return Ok((copied, skipped));
    }
    if !from.is_dir() {
        return Err("原业务数据位置不是目录".to_string());
    }
    for entry in fs::read_dir(from).map_err(|error| format!("无法读取原业务数据目录：{error}"))?
    {
        let entry = entry.map_err(|error| format!("无法读取原业务数据项：{error}"))?;
        let file_type = entry
            .file_type()
            .map_err(|error| format!("无法读取原业务数据项类型：{error}"))?;
        if !file_type.is_file() {
            continue;
        }
        let name = entry.file_name();
        let name_text = name.to_string_lossy();
        let should_copy = name_text == STATE_DB_FILE
            || (name_text.starts_with(&format!("{STATE_DB_FILE}.pre-v"))
                && name_text.ends_with(".backup"));
        if !should_copy {
            continue;
        }
        let target = to.join(&name);
        if target.exists() {
            skipped.push(display_path(&target));
            continue;
        }
        fs::copy(entry.path(), &target)
            .map_err(|error| format!("无法复制 {name_text}：{error}"))?;
        copied.push(display_path(&target));
    }
    Ok((copied, skipped))
}

fn normalize_root(path: &Path) -> Result<PathBuf, String> {
    if path.as_os_str().is_empty() {
        return Err("目录不能为空".to_string());
    }
    Ok(path.canonicalize().unwrap_or_else(|_| path.to_path_buf()))
}

fn same_path(left: &Path, right: &Path) -> bool {
    normalize_for_compare(left) == normalize_for_compare(right)
}

fn path_contains(parent: &Path, child: &Path) -> bool {
    let parent = normalize_for_compare(parent);
    let child = normalize_for_compare(child);
    child == parent || child.starts_with(&format!("{parent}\\"))
}

fn normalize_for_compare(path: &Path) -> String {
    path.to_string_lossy()
        .replace('/', "\\")
        .trim_end_matches('\\')
        .to_ascii_lowercase()
}

pub fn clear_user_data<R: Runtime>(app: &AppHandle<R>) -> Result<UserDataCleanupReport, String> {
    clear_secrets()?;
    let config = load_stored(app).unwrap_or_default();
    let mut targets = BTreeSet::new();
    targets.insert(
        app.path()
            .app_config_dir()
            .map_err(|error| format!("无法定位桌面配置目录：{error}"))?,
    );
    targets.insert(
        app.path()
            .app_data_dir()
            .map_err(|error| format!("无法定位桌面数据目录：{error}"))?,
    );
    if let Some(local_app_data) = std::env::var_os("LOCALAPPDATA") {
        targets.insert(PathBuf::from(local_app_data).join(APP_DIR_NAME));
    }
    if let Ok(data_dir) = resolve_data_dir_from_config(app, &config) {
        targets.insert(data_dir);
    }
    if let Ok(webview_dir) = resolve_webview_data_dir_from_config(app, &config) {
        targets.insert(webview_dir);
    }

    let mut report = UserDataCleanupReport {
        removed_paths: Vec::new(),
        missing_paths: Vec::new(),
        failed_paths: Vec::new(),
        cleared_credentials: true,
    };
    for target in targets {
        match remove_app_directory(&target) {
            Ok(RemoveDirectoryOutcome::Removed) => report.removed_paths.push(display_path(&target)),
            Ok(RemoveDirectoryOutcome::Missing) => report.missing_paths.push(display_path(&target)),
            Err(error) => report.failed_paths.push(UserDataCleanupFailure {
                path: display_path(&target),
                error,
            }),
        }
    }
    Ok(report)
}

enum RemoveDirectoryOutcome {
    Removed,
    Missing,
}

fn remove_app_directory(path: &Path) -> Result<RemoveDirectoryOutcome, String> {
    validate_app_directory(path)?;
    if !path.exists() {
        return Ok(RemoveDirectoryOutcome::Missing);
    }
    if !path.is_dir() {
        return Err("目标不是目录，已拒绝清理".to_string());
    }
    fs::remove_dir_all(path).map_err(|error| format!("删除失败：{error}"))?;
    Ok(RemoveDirectoryOutcome::Removed)
}

fn validate_app_directory(path: &Path) -> Result<(), String> {
    let leaf = path
        .file_name()
        .and_then(|value| value.to_str())
        .ok_or_else(|| "清理路径缺少目录名".to_string())?;
    if leaf == APP_DIR_NAME {
        if path.parent().is_none() {
            return Err("清理路径不能是磁盘根目录".to_string());
        }
        return Ok(());
    }
    if matches!(leaf, CUSTOM_DATA_DIR_NAME | CUSTOM_WEBVIEW_DIR_NAME) {
        ensure_storage_target(path, leaf)?;
        return Ok(());
    }
    Err(format!(
        "清理路径必须指向 {APP_DIR_NAME}、{CUSTOM_DATA_DIR_NAME} 或 {CUSTOM_WEBVIEW_DIR_NAME} 目录"
    ))
}

fn display_path(path: &Path) -> String {
    path.display().to_string()
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;

    #[test]
    fn validates_mail_and_provider_boundaries() {
        let mut config = StoredDesktopConfig::default();
        config.mail_address = "not-an-address".to_string();
        assert_eq!(validate(&config).unwrap_err(), "QQ 邮箱地址格式不正确");

        config.mail_address = "me@qq.com".to_string();
        config.deepseek_base_url = "http://api.deepseek.com".to_string();
        assert_eq!(
            validate(&config).unwrap_err(),
            "DeepSeek 地址必须使用 https://"
        );
    }

    #[test]
    fn stored_config_contains_no_secret_fields() {
        let value = serde_json::to_value(StoredDesktopConfig::default()).unwrap();
        let text = value.to_string();
        assert!(!text.contains("authCode"));
        assert!(!text.contains("apiKey"));
    }

    #[test]
    fn mail_provider_defaults_to_qq_and_serializes_netease_163() {
        let legacy: StoredDesktopConfig =
            serde_json::from_value(serde_json::json!({ "mailAddress": "me@qq.com" })).unwrap();
        assert_eq!(legacy.mail_provider, MailProvider::Qq);
        assert!(legacy.privacy_protection_enabled);

        let mut config = StoredDesktopConfig::default();
        config.mail_provider = MailProvider::Netease163;
        let value = serde_json::to_value(config).unwrap();
        assert_eq!(value["mailProvider"], "netease_163");
        assert_eq!(value["privacyProtectionEnabled"], true);
    }

    #[test]
    fn cleanup_path_must_target_only_the_app_directory() {
        assert!(
            validate_app_directory(&PathBuf::from(r"D:\MiaoGentData\com.wuxian.qqmailagent"))
                .is_ok()
        );
        assert!(validate_app_directory(&PathBuf::from(r"D:\MiaoGentData")).is_err());
        assert!(validate_app_directory(&PathBuf::from(r"D:\")).is_err());
    }

    #[test]
    fn remove_app_directory_reports_missing_without_creating_path() {
        let target = std::env::temp_dir().join(format!("miaogent-missing-{}", std::process::id()));
        let target = target.join(APP_DIR_NAME);
        assert!(matches!(
            remove_app_directory(&target).unwrap(),
            RemoveDirectoryOutcome::Missing
        ));
        assert!(!target.exists());
    }

    #[test]
    fn custom_storage_root_rejects_unsafe_locations() {
        assert!(validate_custom_root_without_app(&PathBuf::from(r"D:\MailAgent")).is_ok());
        assert!(validate_custom_root_without_app(&PathBuf::from(r"C:\")).is_err());
        assert!(validate_custom_root_without_app(&PathBuf::from(r"C:\Windows\Temp")).is_err());
        assert!(validate_custom_root_without_app(&PathBuf::from(r"relative\path")).is_err());
    }

    #[test]
    fn data_migration_copies_only_state_files_without_overwriting() {
        let base = std::env::temp_dir().join(format!(
            "miaogent-copy-test-{}-{}",
            std::process::id(),
            uuid::Uuid::new_v4().simple()
        ));
        let from = base.join("from");
        let to = base
            .join(CUSTOM_STORAGE_DIR_NAME)
            .join(CUSTOM_DATA_DIR_NAME);
        fs::create_dir_all(&from).unwrap();
        fs::create_dir_all(&to).unwrap();
        fs::write(from.join(STATE_DB_FILE), b"db").unwrap();
        fs::write(
            from.join(format!("{STATE_DB_FILE}.pre-v1-20260711.backup")),
            b"backup",
        )
        .unwrap();
        fs::write(from.join("desktop-config.json"), b"config").unwrap();

        let (copied, skipped) = copy_data_files(&from, &to).unwrap();
        assert_eq!(copied.len(), 2);
        assert!(skipped.is_empty());
        assert!(to.join(STATE_DB_FILE).exists());
        assert!(to
            .join(format!("{STATE_DB_FILE}.pre-v1-20260711.backup"))
            .exists());
        assert!(!to.join("desktop-config.json").exists());

        let (copied_again, skipped_again) = copy_data_files(&from, &to).unwrap();
        assert!(copied_again.is_empty());
        assert_eq!(skipped_again.len(), 2);

        fs::remove_dir_all(base).unwrap();
    }
}
