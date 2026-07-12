import { useCallback, useEffect, useState, type FormEvent } from 'react';
import {
  chooseStorageDirectory,
  checkDesktopUpdate,
  clearDesktopUserData,
  desktopConfigChecks,
  getDesktopAppVersion,
  getDesktopStorageLocations,
  getAutostartStatus,
  getDesktopConfig,
  installDesktopUpdate,
  migrateDesktopDataDirectory,
  openStorageDirectory,
  resetDesktopDataDirectory,
  resetWebviewDataDirectory,
  saveDesktopConfig,
  setAutostartEnabled,
  setWebviewDataDirectory,
  type DesktopConfigView,
  type DesktopUpdateInfo,
  type StorageLocations,
  type UserDataCleanupReport,
} from '../desktop/desktopBridge';
import { useDialogFocus } from '../hooks/useDialogFocus';
import { ConfirmDialog } from './Dialogs';
import { Badge, IconButton, InlineError, LoadingLine } from './ui';

type FormState = {
  mailAddress: string;
  mailAuthCode: string;
  imapHost: string;
  imapPort: string;
  smtpHost: string;
  smtpPort: string;
  deepseekApiKey: string;
  deepseekBaseUrl: string;
  deepseekModel: string;
  deepseekTimeoutSeconds: string;
  clearMailAuthCode: boolean;
  clearDeepseekApiKey: boolean;
};

type SettingsNotifyKind = 'success' | 'error' | 'loading';
type SettingsNotifyOptions = {
  persist?: boolean;
  durationMs?: number;
  actionLabel?: string;
  onAction?: () => void;
};

const emptyForm: FormState = {
  mailAddress: '',
  mailAuthCode: '',
  imapHost: 'imap.qq.com',
  imapPort: '993',
  smtpHost: 'smtp.qq.com',
  smtpPort: '465',
  deepseekApiKey: '',
  deepseekBaseUrl: 'https://api.deepseek.com',
  deepseekModel: 'deepseek-chat',
  deepseekTimeoutSeconds: '45',
  clearMailAuthCode: false,
  clearDeepseekApiKey: false,
};

function formFromConfig(config: DesktopConfigView): FormState {
  return {
    ...emptyForm,
    mailAddress: config.mailAddress,
    imapHost: config.imapHost,
    imapPort: String(config.imapPort),
    smtpHost: config.smtpHost,
    smtpPort: String(config.smtpPort),
    deepseekBaseUrl: config.deepseekBaseUrl,
    deepseekModel: config.deepseekModel,
    deepseekTimeoutSeconds: String(config.deepseekTimeoutSeconds),
  };
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : String(error);
}

function updateErrorMessage(error: unknown) {
  const message = errorMessage(error);
  const lower = message.toLowerCase();
  const looksLikeNetworkError = [
    'error sending request for url',
    'operation timed out',
    'connection reset',
    'connection refused',
    'dns',
    'tls',
    'certificate',
    'network',
  ].some((pattern) => lower.includes(pattern));
  if (!looksLikeNetworkError) return message;
  return `无法连接 GitHub 更新源。请检查网络、代理/VPN 是否对桌面应用生效，或稍后重试。原始错误：${message}`;
}

export function DesktopSettings({
  open,
  onClose,
  onSaved,
  onCleared,
  onNotify,
  onOpenReleasePage,
  mode = 'settings',
}: {
  open: boolean;
  onClose: () => void;
  onSaved: () => void;
  onCleared?: (report: UserDataCleanupReport) => void;
  onNotify?: (kind: SettingsNotifyKind, message: string, options?: SettingsNotifyOptions) => void;
  onOpenReleasePage?: () => void;
  mode?: 'settings' | 'onboarding';
}) {
  const close = useCallback(() => onClose(), [onClose]);
  const ref = useDialogFocus(open, close);
  const [config, setConfig] = useState<DesktopConfigView | null>(null);
  const [form, setForm] = useState<FormState>(emptyForm);
  const [autostart, setAutostart] = useState(false);
  const [appVersion, setAppVersion] = useState('');
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [clearConfirmOpen, setClearConfirmOpen] = useState(false);
  const [storageLocations, setStorageLocations] = useState<StorageLocations | null>(null);
  const [dataRootDraft, setDataRootDraft] = useState('');
  const [webviewRootDraft, setWebviewRootDraft] = useState('');
  const [storageBusy, setStorageBusy] = useState<'data' | 'webview' | null>(null);
  const [dataMigrationConfirmOpen, setDataMigrationConfirmOpen] = useState(false);
  const [dataResetConfirmOpen, setDataResetConfirmOpen] = useState(false);
  const [autostartSaving, setAutostartSaving] = useState(false);
  const [updateChecking, setUpdateChecking] = useState(false);
  const [updateInstalling, setUpdateInstalling] = useState(false);
  const [updateStatus, setUpdateStatus] = useState('');
  const [availableUpdate, setAvailableUpdate] = useState<DesktopUpdateInfo | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!open) return;
    let disposed = false;
    setLoading(true);
    setError('');
    void Promise.all([getDesktopConfig(), getAutostartStatus(), getDesktopStorageLocations(), getDesktopAppVersion()])
      .then(([nextConfig, startup, locations, version]) => {
        if (disposed) return;
        setConfig(nextConfig);
        setForm(formFromConfig(nextConfig));
        setAutostart(startup.enabled);
        setAppVersion(version);
        setStorageLocations(locations);
        setDataRootDraft(locations.dataDirectoryRoot ?? '');
        setWebviewRootDraft(locations.webviewDataDirectoryRoot ?? '');
      })
      .catch((loadError) => {
        if (!disposed) setError(errorMessage(loadError));
      })
      .finally(() => {
        if (!disposed) setLoading(false);
      });
    return () => {
      disposed = true;
    };
  }, [open]);

  if (!open) return null;
  const checks = config ? desktopConfigChecks(config) : [];
  const completedChecks = checks.filter((item) => item.done).length;
  const isOnboarding = mode === 'onboarding';

  function setField<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  function notifyUpdateError(message: string) {
    if (onNotify) {
      onNotify('error', message, {
        persist: true,
        ...(onOpenReleasePage ? { actionLabel: '去官网下载', onAction: onOpenReleasePage } : {}),
      });
      return;
    }
    setError(message);
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    if (saving) return;
    setSaving(true);
    setError('');
    try {
      const nextConfig = await saveDesktopConfig({
        mailAddress: form.mailAddress,
        imapHost: form.imapHost,
        imapPort: Number(form.imapPort),
        smtpHost: form.smtpHost,
        smtpPort: Number(form.smtpPort),
        deepseekBaseUrl: form.deepseekBaseUrl,
        deepseekModel: form.deepseekModel,
        deepseekTimeoutSeconds: Number(form.deepseekTimeoutSeconds),
        ...(!form.clearMailAuthCode && form.mailAuthCode.trim() ? { mailAuthCode: form.mailAuthCode.trim() } : {}),
        ...(!form.clearDeepseekApiKey && form.deepseekApiKey.trim() ? { deepseekApiKey: form.deepseekApiKey.trim() } : {}),
        clearMailAuthCode: form.clearMailAuthCode,
        clearDeepseekApiKey: form.clearDeepseekApiKey,
      });
      setConfig(nextConfig);
      setForm(formFromConfig(nextConfig));
      onSaved();
    } catch (saveError) {
      setError(errorMessage(saveError));
    } finally {
      setSaving(false);
    }
  }

  async function changeAutostart(enabled: boolean) {
    if (autostartSaving) return;
    setAutostartSaving(true);
    setError('');
    try {
      const status = await setAutostartEnabled(enabled);
      setAutostart(status.enabled);
    } catch (autostartError) {
      setError(errorMessage(autostartError));
    } finally {
      setAutostartSaving(false);
    }
  }

  async function checkForUpdate() {
    if (updateChecking || updateInstalling) return;
    setUpdateChecking(true);
    setError('');
    setUpdateStatus('');
    setAvailableUpdate(null);
    try {
      const update = await checkDesktopUpdate();
      if (!update.available) {
        setUpdateStatus('当前已经是最新版本。');
        return;
      }
      setAvailableUpdate(update);
    } catch (updateError) {
      notifyUpdateError(`检查更新失败：${updateErrorMessage(updateError)}`);
    } finally {
      setUpdateChecking(false);
    }
  }

  async function confirmInstallUpdate() {
    if (updateInstalling) return;
    setUpdateInstalling(true);
    setError('');
    setUpdateStatus('安装中，稍后将自动进入安装状态…');
    setAvailableUpdate(null);
    try {
      await installDesktopUpdate();
    } catch (updateError) {
      notifyUpdateError(`安装更新失败：${errorMessage(updateError)}`);
      setUpdateStatus('');
      setUpdateInstalling(false);
      setAvailableUpdate(null);
    }
  }

  async function confirmClearUserData() {
    if (clearing) return;
    setClearing(true);
    setError('');
    try {
      const report = await clearDesktopUserData();
      setConfig(null);
      setForm(emptyForm);
      setAutostart(false);
      setClearConfirmOpen(false);
      onCleared?.(report);
    } catch (clearError) {
      setError(errorMessage(clearError));
    } finally {
      setClearing(false);
    }
  }

  function setLocations(next: StorageLocations) {
    setStorageLocations(next);
    setDataRootDraft(next.dataDirectoryRoot ?? '');
    setWebviewRootDraft(next.webviewDataDirectoryRoot ?? '');
  }

  async function refreshStorageLocations() {
    const next = await getDesktopStorageLocations();
    setLocations(next);
    return next;
  }

  async function chooseDataRoot() {
    if (storageBusy) return;
    setStorageBusy('data');
    setError('');
    try {
      const selected = await chooseStorageDirectory();
      if (selected) setDataRootDraft(selected);
    } catch (chooseError) {
      setError(errorMessage(chooseError));
    } finally {
      setStorageBusy(null);
    }
  }

  async function chooseWebviewRoot() {
    if (storageBusy) return;
    setStorageBusy('webview');
    setError('');
    try {
      const selected = await chooseStorageDirectory();
      if (selected) setWebviewRootDraft(selected);
    } catch (chooseError) {
      setError(errorMessage(chooseError));
    } finally {
      setStorageBusy(null);
    }
  }

  async function confirmMigrateDataDirectory() {
    if (storageBusy || !dataRootDraft.trim()) return;
    setStorageBusy('data');
    setError('');
    try {
      await migrateDesktopDataDirectory(dataRootDraft.trim());
      await refreshStorageLocations();
      setDataMigrationConfirmOpen(false);
      onSaved();
    } catch (migrateError) {
      setError(errorMessage(migrateError));
    } finally {
      setStorageBusy(null);
    }
  }

  async function confirmResetDataDirectory() {
    if (storageBusy) return;
    setStorageBusy('data');
    setError('');
    try {
      await resetDesktopDataDirectory();
      await refreshStorageLocations();
      setDataResetConfirmOpen(false);
      onSaved();
    } catch (resetError) {
      setError(errorMessage(resetError));
    } finally {
      setStorageBusy(null);
    }
  }

  async function saveWebviewDirectory() {
    if (storageBusy || !webviewRootDraft.trim()) return;
    setStorageBusy('webview');
    setError('');
    try {
      const next = await setWebviewDataDirectory(webviewRootDraft.trim());
      setLocations(next);
    } catch (webviewError) {
      setError(errorMessage(webviewError));
    } finally {
      setStorageBusy(null);
    }
  }

  async function resetWebviewDirectory() {
    if (storageBusy) return;
    setStorageBusy('webview');
    setError('');
    try {
      const next = await resetWebviewDataDirectory();
      setLocations(next);
    } catch (webviewError) {
      setError(errorMessage(webviewError));
    } finally {
      setStorageBusy(null);
    }
  }

  async function openDirectory(path?: string) {
    if (!path) return;
    setError('');
    try {
      await openStorageDirectory(path);
    } catch (openError) {
      setError(errorMessage(openError));
    }
  }

  return (
    <>
      <div className="drawer-backdrop" role="presentation" onMouseDown={onClose}>
        <aside
          ref={ref}
          className={`health-drawer desktop-settings-drawer ${isOnboarding ? 'desktop-onboarding-drawer' : ''}`}
          role="dialog"
          aria-modal="true"
          aria-labelledby="desktop-settings-title"
          onMouseDown={(event) => event.stopPropagation()}
        >
          <div className="drawer-header">
            <div>
              <span className="eyebrow">DESKTOP AGENT</span>
              <h2 id="desktop-settings-title">{isOnboarding ? '首次配置 MiaoGent' : '桌面 Agent 设置'}</h2>
              <p>
                {isOnboarding
                  ? '完成 QQ 邮箱、授权码和 DeepSeek 配置后，MiaoGent 才能静默巡检、判断重要邮件并准备草稿。'
                  : '授权码和 API Key 只写入 Windows 凭据管理器，不会写入 SQLite、日志或普通配置文件。'}
              </p>
            </div>
            <IconButton icon="close-circle-outline" label="关闭桌面设置" onClick={onClose} />
          </div>
          <LoadingLine active={loading} />
          <form className="desktop-settings-form" onSubmit={(event) => void save(event)}>
            <div className="drawer-body scroll-area">
              {error && <InlineError message={error} />}
              {isOnboarding && (
              <section className="settings-section onboarding-progress-card">
                <div className="section-heading">
                  <div>
                    <h3>配置进度</h3>
                    <p>未完成时仍可进入工作台，但后台同步和 AI 处理会受限。</p>
                  </div>
                  <Badge tone={completedChecks === checks.length && checks.length > 0 ? 'success' : 'warning'}>
                    已完成 {completedChecks} / {checks.length || 4} 项
                  </Badge>
                </div>
                <div className="onboarding-check-grid">
                  {(checks.length ? checks : [
                    { key: 'mailAddress', label: 'QQ 邮箱地址', done: false },
                    { key: 'mailAuthCode', label: 'QQ 授权码', done: false },
                    { key: 'deepseekApiKey', label: 'DeepSeek API Key', done: false },
                    { key: 'connection', label: '连接参数', done: false },
                  ]).map((item) => (
                    <span key={item.key} className={`onboarding-check ${item.done ? 'is-done' : ''}`}>
                      {item.done ? '✓' : '·'} {item.label}
                    </span>
                  ))}
                </div>
              </section>
              )}

            <section className="settings-section">
              <div className="section-heading">
                <div>
                  <h3>QQ 邮箱</h3>
                  <p>使用 QQ 邮箱设置中生成的客户端授权码，不是登录密码。</p>
                </div>
                <Badge tone={config?.hasMailAuthCode ? 'success' : 'warning'}>
                  {config?.hasMailAuthCode ? '授权码已保存' : '待配置'}
                </Badge>
              </div>
              <label className="settings-field">
                <span>邮箱地址</span>
                <input
                  className="field"
                  type="email"
                  required
                  value={form.mailAddress}
                  onChange={(event) => setField('mailAddress', event.target.value)}
                  placeholder="name@qq.com"
                />
              </label>
              <label className="settings-field">
                <span>客户端授权码</span>
                <input
                  className="field"
                  type="password"
                  autoComplete="new-password"
                  required={!config?.hasMailAuthCode && !form.clearMailAuthCode}
                  disabled={form.clearMailAuthCode}
                  value={form.mailAuthCode}
                  onChange={(event) => setField('mailAuthCode', event.target.value)}
                  placeholder={config?.hasMailAuthCode ? '已安全保存；留空保持不变' : '请输入授权码'}
                />
              </label>
              {config?.hasMailAuthCode && (
                <label className="settings-check">
                  <input
                    type="checkbox"
                    checked={form.clearMailAuthCode}
                    onChange={(event) => setField('clearMailAuthCode', event.target.checked)}
                  />
                  <span>保存时清除现有 QQ 邮箱授权码</span>
                </label>
              )}
            </section>

            <section className="settings-section">
              <div className="section-heading">
                <div>
                  <h3>DeepSeek</h3>
                  <p>用于邮件摘要、重要性判断和草稿生成；邮件正文会发送给该模型。</p>
                </div>
                <Badge tone={config?.hasDeepseekApiKey ? 'success' : 'warning'}>
                  {config?.hasDeepseekApiKey ? 'API Key 已保存' : '待配置'}
                </Badge>
              </div>
              <label className="settings-field">
                <span>API Key</span>
                <input
                  className="field"
                  type="password"
                  autoComplete="new-password"
                  required={!config?.hasDeepseekApiKey && !form.clearDeepseekApiKey}
                  disabled={form.clearDeepseekApiKey}
                  value={form.deepseekApiKey}
                  onChange={(event) => setField('deepseekApiKey', event.target.value)}
                  placeholder={config?.hasDeepseekApiKey ? '已安全保存；留空保持不变' : '请输入 API Key'}
                />
              </label>
              {config?.hasDeepseekApiKey && (
                <label className="settings-check">
                  <input
                    type="checkbox"
                    checked={form.clearDeepseekApiKey}
                    onChange={(event) => setField('clearDeepseekApiKey', event.target.checked)}
                  />
                  <span>保存时清除现有 DeepSeek API Key</span>
                </label>
              )}
            </section>

            <section className="settings-section">
              <div className="section-heading">
                <div>
                  <h3>后台运行</h3>
                  <p>关闭主窗口只会缩到托盘；只有托盘“退出”才停止 Agent。</p>
                </div>
              </div>
              <label className="settings-switch">
                <span>
                  <strong>登录 Windows 后静默启动</strong>
                  <small>启动后先整理离线期间的新邮件，再进入 IMAP IDLE。</small>
                </span>
                <input
                  type="checkbox"
                  checked={autostart}
                  disabled={autostartSaving}
                  onChange={(event) => void changeAutostart(event.target.checked)}
                />
              </label>
            </section>

            <section className="settings-section settings-update-section">
              <div className="section-heading">
                <div>
                  <h3>应用更新</h3>
                  <p>从 GitHub Release 检查新版本；发现更新后会先确认，再下载安装并重启。</p>
                </div>
                <Badge tone="info">{appVersion ? `当前版本 v${appVersion}` : '当前版本读取中'}</Badge>
              </div>
              <div className="settings-inline-actions">
                <button
                  className="btn btn-secondary"
                  type="button"
                  disabled={updateChecking || updateInstalling}
                  onClick={() => void checkForUpdate()}
                >
                  {updateChecking ? '检查中…' : updateInstalling ? '安装中…' : '检查更新'}
                </button>
                {updateStatus && <span className="settings-inline-status">{updateStatus}</span>}
              </div>
              <p className="settings-help">
                0.1.12 及更早版本没有内置更新器，需要手动安装一次新版；之后才能应用内更新。
              </p>
            </section>

            <section className="settings-section settings-storage-section">
              <div className="section-heading">
                <div>
                  <h3>存储位置</h3>
                  <p>业务数据可以迁移到自定义目录；密钥仍由 Windows 凭据管理器保存。</p>
                </div>
                <Badge tone={storageLocations?.isDefaultDataDirectory ? 'info' : 'success'}>
                  {storageLocations?.isDefaultDataDirectory ? '默认位置' : '自定义业务数据'}
                </Badge>
              </div>

              <div className="storage-location-card">
                <div className="storage-location-header">
                  <div>
                    <strong>业务数据目录</strong>
                    <small>包含 SQLite、本地草稿、AI 分类结果、队列状态和启动摘要。</small>
                  </div>
                  <Badge tone="warning">迁移会重启后台</Badge>
                </div>
                <code className="storage-path">{storageLocations?.dataDirectory ?? '正在读取…'}</code>
                <div className="storage-root-row">
                  <input
                    className="field"
                    value={dataRootDraft}
                    onChange={(event) => setDataRootDraft(event.target.value)}
                    placeholder="选择或粘贴目标根目录，例如 D:\\MiaoGentData"
                  />
                  <button
                    className="btn btn-secondary"
                    type="button"
                    disabled={Boolean(storageBusy)}
                    onClick={() => void chooseDataRoot()}
                  >
                    选择位置
                  </button>
                </div>
                <p className="storage-help">
                  实际数据会写入 <strong>所选目录\MiaoGent\data</strong>。迁移成功后才切换配置，不会删除旧目录。
                </p>
                <div className="storage-actions">
                  <button
                    className="btn btn-primary"
                    type="button"
                    disabled={Boolean(storageBusy) || !dataRootDraft.trim()}
                    onClick={() => setDataMigrationConfirmOpen(true)}
                  >
                    {storageBusy === 'data' ? '处理中…' : '迁移现有数据'}
                  </button>
                  <button
                    className="btn btn-secondary"
                    type="button"
                    disabled={Boolean(storageBusy) || storageLocations?.isDefaultDataDirectory}
                    onClick={() => setDataResetConfirmOpen(true)}
                  >
                    恢复默认位置
                  </button>
                  <button
                    className="btn btn-secondary"
                    type="button"
                    disabled={!storageLocations?.dataDirectory}
                    onClick={() => void openDirectory(storageLocations?.dataDirectory)}
                  >
                    打开目录
                  </button>
                </div>
              </div>

              <div className="storage-location-card">
                <div className="storage-location-header">
                  <div>
                    <strong>WebView 缓存目录（高级）</strong>
                    <small>包含 WebView2 缓存和本地 WebView 数据；修改后需重启 MiaoGent 生效。</small>
                  </div>
                  <Badge tone={storageLocations?.isDefaultWebviewDataDirectory ? 'info' : 'success'}>
                    {storageLocations?.isDefaultWebviewDataDirectory ? '默认缓存' : '自定义缓存'}
                  </Badge>
                </div>
                <code className="storage-path">{storageLocations?.webviewDataDirectory ?? '正在读取…'}</code>
                <div className="storage-root-row">
                  <input
                    className="field"
                    value={webviewRootDraft}
                    onChange={(event) => setWebviewRootDraft(event.target.value)}
                    placeholder="选择或粘贴目标根目录，例如 D:\\MiaoGentCache"
                  />
                  <button
                    className="btn btn-secondary"
                    type="button"
                    disabled={Boolean(storageBusy)}
                    onClick={() => void chooseWebviewRoot()}
                  >
                    选择位置
                  </button>
                </div>
                <p className="storage-help">
                  实际缓存会写入 <strong>所选目录\MiaoGent\webview</strong>。保存后请从托盘退出并重新打开应用。
                </p>
                <div className="storage-actions">
                  <button
                    className="btn btn-primary"
                    type="button"
                    disabled={Boolean(storageBusy) || !webviewRootDraft.trim()}
                    onClick={() => void saveWebviewDirectory()}
                  >
                    {storageBusy === 'webview' ? '保存中…' : '保存缓存位置'}
                  </button>
                  <button
                    className="btn btn-secondary"
                    type="button"
                    disabled={Boolean(storageBusy) || storageLocations?.isDefaultWebviewDataDirectory}
                    onClick={() => void resetWebviewDirectory()}
                  >
                    恢复默认缓存
                  </button>
                  <button
                    className="btn btn-secondary"
                    type="button"
                    disabled={!storageLocations?.webviewDataDirectory}
                    onClick={() => void openDirectory(storageLocations?.webviewDataDirectory)}
                  >
                    打开目录
                  </button>
                </div>
              </div>
            </section>

              <details className="settings-advanced">
              <summary>
                <span>高级连接设置</span>
                <span className="settings-advanced-chevron" aria-hidden="true" />
              </summary>
              <div className="settings-grid">
                <label className="settings-field">
                  <span>IMAP 主机</span>
                  <input className="field" required value={form.imapHost} onChange={(event) => setField('imapHost', event.target.value)} />
                </label>
                <label className="settings-field">
                  <span>IMAP 端口</span>
                  <input className="field" type="number" min="1" max="65535" required value={form.imapPort} onChange={(event) => setField('imapPort', event.target.value)} />
                </label>
                <label className="settings-field">
                  <span>SMTP 主机</span>
                  <input className="field" required value={form.smtpHost} onChange={(event) => setField('smtpHost', event.target.value)} />
                </label>
                <label className="settings-field">
                  <span>SMTP 端口</span>
                  <input className="field" type="number" min="1" max="65535" required value={form.smtpPort} onChange={(event) => setField('smtpPort', event.target.value)} />
                </label>
                <label className="settings-field settings-grid-wide">
                  <span>DeepSeek 地址</span>
                  <input className="field" type="url" required value={form.deepseekBaseUrl} onChange={(event) => setField('deepseekBaseUrl', event.target.value)} />
                </label>
                <label className="settings-field">
                  <span>模型</span>
                  <input className="field" required value={form.deepseekModel} onChange={(event) => setField('deepseekModel', event.target.value)} />
                </label>
                <label className="settings-field">
                  <span>超时（秒）</span>
                  <input className="field" type="number" min="5" max="300" required value={form.deepseekTimeoutSeconds} onChange={(event) => setField('deepseekTimeoutSeconds', event.target.value)} />
                </label>
              </div>
              </details>

              <section className="settings-section settings-danger-section">
                <div className="section-heading">
                  <div>
                    <h3>危险操作</h3>
                    <p>清除本机保存的授权、配置、草稿、AI 结果、反馈、缓存和日志。不会删除 QQ 邮箱服务器上的邮件。</p>
                  </div>
                </div>
                <button
                  className="btn btn-danger-outline"
                  type="button"
                  disabled={loading || saving || clearing}
                  onClick={() => setClearConfirmOpen(true)}
                >
                  {clearing ? '正在清除…' : '清除密钥和本地数据'}
                </button>
              </section>
            </div>
            <div className="drawer-footer">
              <button className="btn btn-secondary" type="button" onClick={onClose}>{isOnboarding ? '稍后配置' : '取消'}</button>
              <button className="btn btn-primary" type="submit" disabled={loading || saving || clearing}>
                {saving ? '保存并重启 Agent…' : isOnboarding ? '保存并启动巡检' : '保存并重启 Agent'}
              </button>
            </div>
          </form>
        </aside>
      </div>
      <ConfirmDialog
        state={availableUpdate ? {
          title: '新版本准备就绪',
          message: `发现 MiaoGent ${availableUpdate.version ?? ''}，是否现在安装？安装前会先暂停后台 Agent，安装完成后应用会自动重启。`,
          confirmLabel: updateInstalling ? '安装中…' : '现在安装',
          tone: 'warning',
          details: (
            <div className="cleanup-confirm-detail">
              {availableUpdate.currentVersion && <p>当前版本：{availableUpdate.currentVersion}</p>}
              {availableUpdate.version && <p>新版本：{availableUpdate.version}</p>}
              {availableUpdate.body && <p>{availableUpdate.body}</p>}
            </div>
          ),
        } : null}
        onCancel={() => {
          if (updateInstalling) return;
          setAvailableUpdate(null);
          setUpdateStatus('已取消安装更新。');
        }}
        onConfirm={() => void confirmInstallUpdate()}
      />
      <ConfirmDialog
        state={clearConfirmOpen ? {
          title: '清除 MiaoGent 本机数据',
          message: '确认后会停止后台 Agent，并删除本机草稿、AI 结果、反馈、配置、日志、缓存、QQ 授权码和 DeepSeek Key。QQ 邮箱服务器上的邮件不会被删除。',
          confirmLabel: clearing ? '清除中…' : '确认清除',
          tone: 'danger',
          details: (
            <div className="cleanup-confirm-detail">
              <p>清除后需要重新配置 QQ 邮箱授权码和 DeepSeek API Key。</p>
              <p>如果缓存文件正被 WebView 占用，可能需要退出应用后由卸载器继续清理。</p>
            </div>
          ),
        } : null}
        onCancel={() => !clearing && setClearConfirmOpen(false)}
        onConfirm={() => void confirmClearUserData()}
      />
      <ConfirmDialog
        state={dataMigrationConfirmOpen ? {
          title: '迁移业务数据目录',
          message: `确认后会停止后台 Agent，将现有 SQLite、草稿和 AI 结果复制到新的业务数据目录，然后重启后台。目标根目录：${dataRootDraft.trim()}`,
          confirmLabel: storageBusy === 'data' ? '迁移中…' : '确认迁移',
          tone: 'warning',
          details: (
            <div className="cleanup-confirm-detail">
              <p>迁移成功前不会切换配置；迁移失败不会删除原数据。</p>
              <p>旧目录会保留，你确认新目录可用后可再手动清理。</p>
            </div>
          ),
        } : null}
        onCancel={() => storageBusy !== 'data' && setDataMigrationConfirmOpen(false)}
        onConfirm={() => void confirmMigrateDataDirectory()}
      />
      <ConfirmDialog
        state={dataResetConfirmOpen ? {
          title: '恢复默认业务数据目录',
          message: '确认后会停止后台 Agent，将当前业务数据复制回默认 AppData 目录，然后重启后台。',
          confirmLabel: storageBusy === 'data' ? '恢复中…' : '确认恢复',
          tone: 'warning',
          details: (
            <div className="cleanup-confirm-detail">
              <p>恢复成功前不会切换配置；当前自定义目录不会被自动删除。</p>
            </div>
          ),
        } : null}
        onCancel={() => storageBusy !== 'data' && setDataResetConfirmOpen(false)}
        onConfirm={() => void confirmResetDataDirectory()}
      />
    </>
  );
}
