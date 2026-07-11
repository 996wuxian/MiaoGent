import { configureDesktopApi } from '../api';
import type { DesktopBackendConnection, DesktopEvent } from '../types';

export type DesktopTarget = { kind: 'summary' } | { kind: 'mail'; uid: string };

export type DesktopConfigView = {
  mailAddress: string;
  imapHost: string;
  imapPort: number;
  smtpHost: string;
  smtpPort: number;
  deepseekBaseUrl: string;
  deepseekModel: string;
  deepseekTimeoutSeconds: number;
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

export function desktopConfigChecks(config: DesktopConfigView) {
  return [
    { key: 'mailAddress', label: 'QQ 邮箱地址', done: Boolean(config.mailAddress.trim()) },
    { key: 'mailAuthCode', label: 'QQ 授权码', done: config.hasMailAuthCode },
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

export async function getAutostartStatus() {
  return invokeDesktop<{ enabled: boolean }>('autostart_status');
}

export async function setAutostartEnabled(enabled: boolean) {
  return invokeDesktop<{ enabled: boolean }>('set_autostart', { enabled });
}

export async function openDevtools(password: string) {
  return invokeDesktop<void>('open_devtools', { password });
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
