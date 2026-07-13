import { configureDesktopApi } from '../api';
import type { DesktopBackendConnection, DesktopEvent } from '../types';

export type DesktopTarget = { kind: 'summary' } | { kind: 'mail'; uid: string };
export type MailProvider = 'qq' | 'netease_163';

export type DesktopConfigView = {
  mailProvider: MailProvider;
  mailAddress: string;
  imapHost: string;
  imapPort: number;
  smtpHost: string;
  smtpPort: number;
  deepseekBaseUrl: string;
  deepseekModel: string;
  deepseekTimeoutSeconds: number;
  privacyProtectionEnabled: boolean;
  hasMailAuthCode: boolean;
  hasDeepseekApiKey: boolean;
  secretStorage: 'windows_credential_manager';
  dataDirectory: string;
  dataDirectoryRoot: string | null;
  isDefaultDataDirectory: boolean;
  webviewDataDirectory: string;
  webviewDataDirectoryRoot: string | null;
  isDefaultWebviewDataDirectory: boolean;
};

export type DesktopConfigInput = Omit<
  DesktopConfigView,
  | 'hasMailAuthCode'
  | 'hasDeepseekApiKey'
  | 'secretStorage'
  | 'dataDirectory'
  | 'dataDirectoryRoot'
  | 'isDefaultDataDirectory'
  | 'webviewDataDirectory'
  | 'webviewDataDirectoryRoot'
  | 'isDefaultWebviewDataDirectory'
> & {
  mailAuthCode?: string;
  deepseekApiKey?: string;
  clearMailAuthCode?: boolean;
  clearDeepseekApiKey?: boolean;
};

const mailProviderLabels: Record<MailProvider, { address: string; authCode: string; title: string }> = {
  qq: { address: 'QQ 邮箱地址', authCode: 'QQ 授权码', title: 'QQ 邮箱' },
  netease_163: { address: '163 邮箱地址', authCode: '163 授权码', title: '163 邮箱' },
};

export function mailProviderLabel(provider: MailProvider) {
  return mailProviderLabels[provider].title;
}

export function mailProviderAuthCodeLabel(provider: MailProvider) {
  return mailProviderLabels[provider].authCode;
}

export type UserDataCleanupReport = {
  removedPaths: string[];
  missingPaths: string[];
  failedPaths: Array<{ path: string; error: string }>;
  clearedCredentials: boolean;
};

export type StorageLocations = {
  dataDirectory: string;
  dataDirectoryRoot: string | null;
  defaultDataDirectory: string;
  isDefaultDataDirectory: boolean;
  webviewDataDirectory: string;
  webviewDataDirectoryRoot: string | null;
  defaultWebviewDataDirectory: string;
  isDefaultWebviewDataDirectory: boolean;
  webviewChangeRequiresRestart: boolean;
};

export type DataDirectoryMigrationReport = {
  previousDirectory: string;
  currentDirectory: string;
  copiedFiles: string[];
  skippedFiles: string[];
};

export type DesktopUpdateInfo = {
  available: boolean;
  version: string | null;
  currentVersion: string | null;
  date: string | null;
  body: string | null;
  releaseUrl?: string | null;
  checkedAt?: string | null;
  source?: 'github' | 'tauri' | 'cache';
  error?: string | null;
};

const GITHUB_LATEST_RELEASE_API = 'https://api.github.com/repos/996wuxian/MiaoGent/releases/latest';
const GITHUB_LATEST_RELEASE_PAGE = 'https://github.com/996wuxian/MiaoGent/releases/latest';
const UPDATE_CACHE_KEY = 'miaogent:last-successful-update-check';

type GitHubReleaseResponse = {
  tag_name?: string;
  name?: string | null;
  body?: string | null;
  published_at?: string | null;
  html_url?: string | null;
  draft?: boolean;
  prerelease?: boolean;
};

export function desktopConfigChecks(config: DesktopConfigView) {
  const labels = mailProviderLabels[config.mailProvider];
  return [
    { key: 'mailAddress', label: labels.address, done: Boolean(config.mailAddress.trim()) },
    { key: 'mailAuthCode', label: labels.authCode, done: config.hasMailAuthCode },
    { key: 'deepseekApiKey', label: 'DeepSeek API Key', done: config.hasDeepseekApiKey },
    {
      key: 'connection',
      label: '连接参数',
      done: Boolean(
        config.imapHost.trim() &&
          config.imapPort > 0 &&
          config.smtpHost.trim() &&
          config.smtpPort > 0 &&
          config.deepseekBaseUrl.trim() &&
          config.deepseekModel.trim() &&
          config.deepseekTimeoutSeconds > 0,
      ),
    },
  ];
}

export function isDesktopConfigComplete(config: DesktopConfigView) {
  return desktopConfigChecks(config).every((item) => item.done);
}

export type DesktopBridgeCallbacks = {
  onBackendReady?: (connection: DesktopBackendConnection) => void;
  onEvent?: (event: DesktopEvent) => void;
  onNavigate?: (target: DesktopTarget) => void;
  onSyncRequest?: () => void;
};

export function shouldRefreshDesktopData(event: DesktopEvent) {
  return [
    'startup_summary',
    'sync_summary',
    'important_mail',
    'mail_processed',
    'attention_required',
  ].includes(event.event);
}

export function isTauriRuntime() {
  return typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window;
}

export function createNavigationGate(onNavigate?: (target: DesktopTarget) => void) {
  let backendReady = false;
  return {
    deliver(target: DesktopTarget) {
      if (!backendReady) return false;
      onNavigate?.(target);
      return true;
    },
    setBackendReady() {
      backendReady = true;
    },
    setBackendUnavailable() {
      backendReady = false;
    },
    isBackendReady() {
      return backendReady;
    },
  };
}

async function invokeDesktop<T>(command: string, args?: Record<string, unknown>) {
  if (!isTauriRuntime()) throw new Error('桌面设置只能在 Tauri 应用中使用');
  const { invoke } = await import('@tauri-apps/api/core');
  return invoke<T>(command, args);
}

export function getDesktopConfig() {
  return invokeDesktop<DesktopConfigView>('desktop_config');
}

export function saveDesktopConfig(input: DesktopConfigInput) {
  return invokeDesktop<DesktopConfigView>('save_desktop_config', { input });
}

export function clearDesktopUserData() {
  return invokeDesktop<UserDataCleanupReport>('clear_desktop_user_data');
}

export function getDesktopStorageLocations() {
  return invokeDesktop<StorageLocations>('desktop_storage_locations');
}

export function chooseStorageDirectory() {
  return invokeDesktop<string | null>('choose_storage_directory');
}

export function migrateDesktopDataDirectory(root: string) {
  return invokeDesktop<DataDirectoryMigrationReport>('migrate_desktop_data_directory', {
    input: { root },
  });
}

export function resetDesktopDataDirectory() {
  return invokeDesktop<DataDirectoryMigrationReport>('reset_desktop_data_directory');
}

export function setWebviewDataDirectory(root: string) {
  return invokeDesktop<StorageLocations>('set_webview_data_directory', {
    input: { root },
  });
}

export function resetWebviewDataDirectory() {
  return invokeDesktop<StorageLocations>('reset_webview_data_directory');
}

export function openStorageDirectory(path: string) {
  return invokeDesktop<void>('open_storage_directory', { path });
}

export function getDesktopAppVersion() {
  return invokeDesktop<string>('desktop_app_version');
}

export function openDesktopReleasePage() {
  return invokeDesktop<void>('open_release_page');
}

export async function getAutostartStatus() {
  return invokeDesktop<{ enabled: boolean }>('autostart_status');
}

export async function setAutostartEnabled(enabled: boolean) {
  return invokeDesktop<{ enabled: boolean }>('set_autostart', { enabled });
}

export async function openDevtools(password: string) {
  return invokeDesktop<void>('open_devtools', { password });
}

export async function prepareDesktopUpdate() {
  return invokeDesktop<void>('prepare_desktop_update');
}

export async function restartDesktopBackend() {
  return invokeDesktop<void>('restart_backend');
}

export async function checkDesktopUpdate(): Promise<DesktopUpdateInfo> {
  if (!isTauriRuntime()) throw new Error('应用更新只能在 Tauri 应用中使用');
  const currentVersion = await getDesktopAppVersion().catch(() => null);
  try {
    const update = await checkGitHubLatestRelease(currentVersion);
    writeUpdateCache(update);
    return update;
  } catch (githubError) {
    try {
      const update = await checkTauriUpdater(currentVersion);
      writeUpdateCache(update);
      return update;
    } catch (tauriError) {
      const cached = readUpdateCache(currentVersion);
      if (cached) {
        return {
          ...cached,
          source: 'cache',
          error: `GitHub API: ${errorMessage(githubError)}；Tauri updater: ${errorMessage(tauriError)}`,
        };
      }
      throw new Error(`GitHub API: ${errorMessage(githubError)}；Tauri updater: ${errorMessage(tauriError)}`);
    }
  }
}

async function checkGitHubLatestRelease(currentVersion: string | null): Promise<DesktopUpdateInfo> {
  const response = await fetch(GITHUB_LATEST_RELEASE_API, {
    method: 'GET',
    cache: 'no-store',
    headers: {
      Accept: 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
    },
  });
  if (!response.ok) {
    throw new Error(`GitHub Releases API 返回 ${response.status}`);
  }
  const release = (await response.json()) as GitHubReleaseResponse;
  const latestVersion = normalizeVersion(release.tag_name || release.name || '');
  if (!latestVersion) throw new Error('GitHub Release 没有可识别的版本号');
  return {
    available: isNewerVersion(latestVersion, currentVersion),
    version: latestVersion,
    currentVersion,
    date: release.published_at ?? null,
    body: release.body ?? null,
    releaseUrl: release.html_url ?? GITHUB_LATEST_RELEASE_PAGE,
    checkedAt: new Date().toISOString(),
    source: 'github',
    error: null,
  };
}

async function checkTauriUpdater(currentVersion: string | null): Promise<DesktopUpdateInfo> {
  const { check } = await import('@tauri-apps/plugin-updater');
  const update = await check();
  if (!update) {
    return {
      available: false,
      version: null,
      currentVersion,
      date: null,
      body: null,
      releaseUrl: GITHUB_LATEST_RELEASE_PAGE,
      checkedAt: new Date().toISOString(),
      source: 'tauri',
      error: null,
    };
  }
  return {
    available: true,
    version: normalizeVersion(update.version),
    currentVersion: update.currentVersion ?? currentVersion,
    date: update.date ?? null,
    body: update.body ?? null,
    releaseUrl: GITHUB_LATEST_RELEASE_PAGE,
    checkedAt: new Date().toISOString(),
    source: 'tauri',
    error: null,
  };
}

function normalizeVersion(value: string | null | undefined) {
  return String(value ?? '').trim().replace(/^v/i, '');
}

function isNewerVersion(latestVersion: string, currentVersion: string | null) {
  if (!currentVersion) return true;
  const latest = parseVersionParts(latestVersion);
  const current = parseVersionParts(currentVersion);
  if (!latest || !current) return normalizeVersion(latestVersion) !== normalizeVersion(currentVersion);
  const length = Math.max(latest.length, current.length);
  for (let index = 0; index < length; index += 1) {
    const left = latest[index] ?? 0;
    const right = current[index] ?? 0;
    if (left > right) return true;
    if (left < right) return false;
  }
  return false;
}

function parseVersionParts(value: string | null | undefined) {
  const normalized = normalizeVersion(value).split(/[+-]/)[0];
  if (!/^\d+(\.\d+)*$/.test(normalized)) return null;
  return normalized.split('.').map((part) => Number(part));
}

function writeUpdateCache(update: DesktopUpdateInfo) {
  if (update.source === 'cache') return;
  try {
    window.localStorage.setItem(UPDATE_CACHE_KEY, JSON.stringify(update));
  } catch {
    // Cache is best-effort only; update installation still relies on signed Tauri updater metadata.
  }
}

function readUpdateCache(currentVersion: string | null): DesktopUpdateInfo | null {
  try {
    const raw = window.localStorage.getItem(UPDATE_CACHE_KEY);
    if (!raw) return null;
    const cached = JSON.parse(raw) as DesktopUpdateInfo;
    if (!cached || typeof cached !== 'object') return null;
    const version = typeof cached.version === 'string' ? normalizeVersion(cached.version) : null;
    if (!version) return null;
    return {
      available: isNewerVersion(version, currentVersion ?? cached.currentVersion),
      version,
      currentVersion: currentVersion ?? cached.currentVersion ?? null,
      date: typeof cached.date === 'string' ? cached.date : null,
      body: typeof cached.body === 'string' ? cached.body : null,
      releaseUrl: typeof cached.releaseUrl === 'string' ? cached.releaseUrl : GITHUB_LATEST_RELEASE_PAGE,
      checkedAt: typeof cached.checkedAt === 'string' ? cached.checkedAt : null,
      source: 'cache',
      error: null,
    };
  } catch {
    return null;
  }
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : String(error);
}

export async function installDesktopUpdate() {
  if (!isTauriRuntime()) throw new Error('应用更新只能在 Tauri 应用中使用');
  const [{ check }, { relaunch }] = await Promise.all([
    import('@tauri-apps/plugin-updater'),
    import('@tauri-apps/plugin-process'),
  ]);
  const update = await check();
  if (!update) throw new Error('当前没有可安装的新版本。');
  await prepareDesktopUpdate();
  try {
    await update.downloadAndInstall();
  } catch (error) {
    try {
      await restartDesktopBackend();
    } catch {
      // Keep the original updater failure visible; backend restart failures are surfaced by desktop events.
    }
    throw error;
  }
  await relaunch();
}

async function consumePendingNavigation(
  invoke: <T>(command: string, args?: Record<string, unknown>) => Promise<T>,
  onNavigate?: (target: DesktopTarget) => void,
) {
  try {
    const target = await invoke<DesktopTarget | null>('take_pending_navigation');
    if (target) onNavigate?.(target);
  } catch {
    // Navigation is retained by Rust until a later bridge initialization can consume it.
  }
}

export async function initializeDesktopBridge(callbacks: DesktopBridgeCallbacks = {}) {
  if (!isTauriRuntime()) return () => undefined;

  const [{ invoke }, { listen }] = await Promise.all([
    import('@tauri-apps/api/core'),
    import('@tauri-apps/api/event'),
  ]);

  const unlisten: Array<() => void | Promise<void>> = [];
  const navigationGate = createNavigationGate(callbacks.onNavigate);
  const consumeNavigationWhenReady = () => {
    if (!navigationGate.isBackendReady()) return;
    void consumePendingNavigation(invoke, navigationGate.deliver);
  };
  unlisten.push(
    await listen<DesktopBackendConnection>('desktop-backend-ready', ({ payload }) => {
      configureDesktopApi(payload);
      callbacks.onBackendReady?.(payload);
      navigationGate.setBackendReady();
      consumeNavigationWhenReady();
    }),
  );
  unlisten.push(
    await listen<DesktopEvent>('qq-mail-event', ({ payload }) => {
      if (
        payload.event === 'watcher_status' &&
        ['sidecar_stopped', 'sidecar_ready_timeout', 'sidecar_restart_failed', 'sidecar_restart_exhausted'].includes(
          String(payload.payload.status ?? ''),
        )
      ) {
        configureDesktopApi(null);
        navigationGate.setBackendUnavailable();
      }
      callbacks.onEvent?.(payload);
    }),
  );
  unlisten.push(
    await listen('desktop-navigation', consumeNavigationWhenReady),
  );
  unlisten.push(await listen('desktop-request-sync', () => callbacks.onSyncRequest?.()));

  try {
    const connection = await invoke<DesktopBackendConnection | null>('backend_connection');
    if (connection) {
      configureDesktopApi(connection);
      callbacks.onBackendReady?.(connection);
      navigationGate.setBackendReady();
    }
  } catch {
    // The sidecar can still publish desktop-backend-ready after its startup handshake.
  }

  consumeNavigationWhenReady();

  return () => {
    for (const stop of unlisten) void stop();
  };
}
