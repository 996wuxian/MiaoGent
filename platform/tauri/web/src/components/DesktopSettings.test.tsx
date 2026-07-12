import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const desktopMocks = vi.hoisted(() => ({
  desktopConfigChecks: (value: typeof config) => [
    { key: 'mailAddress', label: 'QQ 邮箱地址', done: Boolean(value.mailAddress.trim()) },
    { key: 'mailAuthCode', label: 'QQ 授权码', done: value.hasMailAuthCode },
    { key: 'deepseekApiKey', label: 'DeepSeek API Key', done: value.hasDeepseekApiKey },
    { key: 'connection', label: '连接参数', done: true },
  ],
  getDesktopConfig: vi.fn(),
  saveDesktopConfig: vi.fn(),
  clearDesktopUserData: vi.fn(),
  checkDesktopUpdate: vi.fn(),
  installDesktopUpdate: vi.fn(),
  getDesktopStorageLocations: vi.fn(),
  chooseStorageDirectory: vi.fn(),
  migrateDesktopDataDirectory: vi.fn(),
  resetDesktopDataDirectory: vi.fn(),
  setWebviewDataDirectory: vi.fn(),
  resetWebviewDataDirectory: vi.fn(),
  openStorageDirectory: vi.fn(),
  getAutostartStatus: vi.fn(),
  setAutostartEnabled: vi.fn(),
}));

vi.mock('../desktop/desktopBridge', () => desktopMocks);

import { DesktopSettings } from './DesktopSettings';

const config = {
  mailAddress: 'me@qq.com',
  imapHost: 'imap.qq.com',
  imapPort: 993,
  smtpHost: 'smtp.qq.com',
  smtpPort: 465,
  deepseekBaseUrl: 'https://api.deepseek.com',
  deepseekModel: 'deepseek-chat',
  deepseekTimeoutSeconds: 45,
  hasMailAuthCode: false,
  hasDeepseekApiKey: false,
  secretStorage: 'windows_credential_manager' as const,
  dataDirectory: 'C:\\Users\\kata\\AppData\\Roaming\\com.wuxian.qqmailagent',
  dataDirectoryRoot: null,
  isDefaultDataDirectory: true,
  webviewDataDirectory: 'C:\\Users\\kata\\AppData\\Local\\com.wuxian.qqmailagent',
  webviewDataDirectoryRoot: null,
  isDefaultWebviewDataDirectory: true,
};

const storageLocations = {
  dataDirectory: 'C:\\Users\\kata\\AppData\\Roaming\\com.wuxian.qqmailagent',
  dataDirectoryRoot: null,
  defaultDataDirectory: 'C:\\Users\\kata\\AppData\\Roaming\\com.wuxian.qqmailagent',
  isDefaultDataDirectory: true,
  webviewDataDirectory: 'C:\\Users\\kata\\AppData\\Local\\com.wuxian.qqmailagent',
  webviewDataDirectoryRoot: null,
  defaultWebviewDataDirectory: 'C:\\Users\\kata\\AppData\\Local\\com.wuxian.qqmailagent',
  isDefaultWebviewDataDirectory: true,
  webviewChangeRequiresRestart: true,
};

describe('DesktopSettings', () => {
  beforeEach(() => {
    desktopMocks.getDesktopConfig.mockReset().mockResolvedValue(config);
    desktopMocks.saveDesktopConfig.mockReset().mockResolvedValue({
      ...config,
      hasMailAuthCode: true,
      hasDeepseekApiKey: true,
    });
    desktopMocks.getAutostartStatus.mockReset().mockResolvedValue({ enabled: true });
    desktopMocks.setAutostartEnabled.mockReset().mockResolvedValue({ enabled: false });
    desktopMocks.getDesktopStorageLocations.mockReset().mockResolvedValue(storageLocations);
    desktopMocks.chooseStorageDirectory.mockReset().mockResolvedValue('D:\\MailAgent');
    desktopMocks.migrateDesktopDataDirectory.mockReset().mockResolvedValue({
      previousDirectory: storageLocations.dataDirectory,
      currentDirectory: 'D:\\MailAgent\\MiaoGent\\data',
      copiedFiles: ['D:\\MailAgent\\MiaoGent\\data\\state.sqlite3'],
      skippedFiles: [],
    });
    desktopMocks.resetDesktopDataDirectory.mockReset().mockResolvedValue({
      previousDirectory: 'D:\\MailAgent\\MiaoGent\\data',
      currentDirectory: storageLocations.defaultDataDirectory,
      copiedFiles: [],
      skippedFiles: [],
    });
    desktopMocks.setWebviewDataDirectory.mockReset().mockResolvedValue({
      ...storageLocations,
      webviewDataDirectory: 'D:\\MailAgent\\MiaoGent\\webview',
      webviewDataDirectoryRoot: 'D:\\MailAgent',
      isDefaultWebviewDataDirectory: false,
    });
    desktopMocks.resetWebviewDataDirectory.mockReset().mockResolvedValue(storageLocations);
    desktopMocks.openStorageDirectory.mockReset().mockResolvedValue(undefined);
    desktopMocks.checkDesktopUpdate.mockReset().mockResolvedValue({
      available: false,
      version: null,
      currentVersion: null,
      date: null,
      body: null,
    });
    desktopMocks.installDesktopUpdate.mockReset().mockResolvedValue(undefined);
    desktopMocks.clearDesktopUserData.mockReset().mockResolvedValue({
      removedPaths: ['C:\\Users\\kata\\AppData\\Roaming\\com.wuxian.qqmailagent'],
      missingPaths: [],
      failedPaths: [],
      clearedCredentials: true,
    });
  });

  it('saves new secrets without ever reading existing secret values back', async () => {
    const user = userEvent.setup();
    const onSaved = vi.fn();
    render(<DesktopSettings open onClose={() => undefined} onSaved={onSaved} />);

    const authCode = await screen.findByLabelText('客户端授权码');
    const apiKey = screen.getByLabelText('API Key');
    expect(authCode).toHaveValue('');
    expect(apiKey).toHaveValue('');

    await user.type(authCode, 'mail-secret');
    await user.type(apiKey, 'deepseek-secret');
    await user.click(screen.getByRole('button', { name: '保存并重启 Agent' }));

    await waitFor(() => expect(desktopMocks.saveDesktopConfig).toHaveBeenCalledTimes(1));
    expect(desktopMocks.saveDesktopConfig).toHaveBeenCalledWith(
      expect.objectContaining({
        mailAddress: 'me@qq.com',
        mailAuthCode: 'mail-secret',
        deepseekApiKey: 'deepseek-secret',
      }),
    );
    expect(onSaved).toHaveBeenCalledTimes(1);
  });

  it('allows the user to disable autostart without changing credentials', async () => {
    const user = userEvent.setup();
    render(<DesktopSettings open onClose={() => undefined} onSaved={() => undefined} />);

    const checkbox = await screen.findByRole('checkbox', { name: /登录 Windows 后静默启动/ });
    expect(checkbox).toBeChecked();
    await user.click(checkbox);

    await waitFor(() => expect(desktopMocks.setAutostartEnabled).toHaveBeenCalledWith(false));
  });

  it('never submits a replacement secret together with its clear flag', async () => {
    desktopMocks.getDesktopConfig.mockResolvedValue({
      ...config,
      hasMailAuthCode: true,
      hasDeepseekApiKey: true,
    });
    const user = userEvent.setup();
    render(<DesktopSettings open onClose={() => undefined} onSaved={() => undefined} />);

    const authCode = await screen.findByLabelText('客户端授权码');
    await user.type(authCode, 'replacement-secret');
    await user.click(screen.getByRole('checkbox', { name: /清除现有 QQ 邮箱授权码/ }));
    await user.click(screen.getByRole('button', { name: '保存并重启 Agent' }));

    await waitFor(() => expect(desktopMocks.saveDesktopConfig).toHaveBeenCalledTimes(1));
    const payload = desktopMocks.saveDesktopConfig.mock.calls[0][0];
    expect(payload.clearMailAuthCode).toBe(true);
    expect(payload).not.toHaveProperty('mailAuthCode');
  });

  it('shows onboarding progress and save copy in onboarding mode', async () => {
    render(<DesktopSettings open mode="onboarding" onClose={() => undefined} onSaved={() => undefined} />);

    expect(await screen.findByRole('heading', { name: '首次配置 MiaoGent' })).toBeInTheDocument();
    expect(screen.getByText('已完成 2 / 4 项')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '保存并启动巡检' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '稍后配置' })).toBeInTheDocument();
  });

  it('uses the custom dropdown-style chevron for advanced connection settings', async () => {
    render(<DesktopSettings open onClose={() => undefined} onSaved={() => undefined} />);

    expect(await screen.findByText('高级连接设置')).toBeInTheDocument();
    expect(document.querySelector('.settings-advanced-chevron')).toBeInTheDocument();
  });

  it('requires confirmation before clearing local secrets and data', async () => {
    const user = userEvent.setup();
    const onCleared = vi.fn();
    render(<DesktopSettings open onClose={() => undefined} onSaved={() => undefined} onCleared={onCleared} />);

    await user.click(await screen.findByRole('button', { name: '清除密钥和本地数据' }));
    expect(desktopMocks.clearDesktopUserData).not.toHaveBeenCalled();

    const dialog = await screen.findByRole('dialog', { name: '清除 MiaoGent 本机数据' });
    await user.click(screen.getByRole('button', { name: '确认清除' }));

    await waitFor(() => expect(desktopMocks.clearDesktopUserData).toHaveBeenCalledTimes(1));
    expect(onCleared).toHaveBeenCalledWith(expect.objectContaining({ clearedCredentials: true }));
    expect(dialog).not.toBeInTheDocument();
  });

  it('requires confirmation before migrating the desktop data directory', async () => {
    const user = userEvent.setup();
    const onSaved = vi.fn();
    render(<DesktopSettings open onClose={() => undefined} onSaved={onSaved} />);

    expect(await screen.findByText('业务数据目录')).toBeInTheDocument();
    await user.click(screen.getAllByRole('button', { name: '选择位置' })[0]);
    await waitFor(() => expect(desktopMocks.chooseStorageDirectory).toHaveBeenCalledTimes(1));
    await user.click(screen.getByRole('button', { name: '迁移现有数据' }));

    expect(desktopMocks.migrateDesktopDataDirectory).not.toHaveBeenCalled();
    await user.click(await screen.findByRole('button', { name: '确认迁移' }));

    await waitFor(() => expect(desktopMocks.migrateDesktopDataDirectory).toHaveBeenCalledWith('D:\\MailAgent'));
    expect(onSaved).toHaveBeenCalledTimes(1);
  });

  it('saves a custom WebView cache root and tells the user to restart', async () => {
    const user = userEvent.setup();
    render(<DesktopSettings open onClose={() => undefined} onSaved={() => undefined} />);

    expect(await screen.findByText('WebView 缓存目录（高级）')).toBeInTheDocument();
    expect(screen.getByText(/保存后请从托盘退出并重新打开应用/)).toBeInTheDocument();

    await user.click(screen.getAllByRole('button', { name: '选择位置' })[1]);
    await user.click(screen.getByRole('button', { name: '保存缓存位置' }));

    await waitFor(() => expect(desktopMocks.setWebviewDataDirectory).toHaveBeenCalledWith('D:\\MailAgent'));
  });

  it('checks for desktop updates and reports when the app is current', async () => {
    const user = userEvent.setup();
    render(<DesktopSettings open onClose={() => undefined} onSaved={() => undefined} />);

    await user.click(await screen.findByRole('button', { name: '检查更新' }));

    await waitFor(() => expect(desktopMocks.checkDesktopUpdate).toHaveBeenCalledTimes(1));
    expect(screen.getByText('当前已经是最新版本。')).toBeInTheDocument();
  });

  it('explains GitHub updater network failures in Chinese', async () => {
    desktopMocks.checkDesktopUpdate.mockRejectedValue(
      new Error('error sending request for url (https://github.com/996wuxian/MiaoGent/releases/latest/download/latest.json)'),
    );
    const user = userEvent.setup();
    render(<DesktopSettings open onClose={() => undefined} onSaved={() => undefined} />);

    await user.click(await screen.findByRole('button', { name: '检查更新' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('无法连接 GitHub 更新源');
    expect(screen.getByRole('alert')).toHaveTextContent('原始错误：error sending request for url');
  });

  it('requires confirmation before installing a desktop update and then closes the prompt', async () => {
    desktopMocks.checkDesktopUpdate.mockResolvedValue({
      available: true,
      version: '0.1.14',
      currentVersion: '0.1.13',
      date: '2026-07-12T00:00:00Z',
      body: '更新日志',
    });
    const user = userEvent.setup();
    render(<DesktopSettings open onClose={() => undefined} onSaved={() => undefined} />);

    await user.click(await screen.findByRole('button', { name: '检查更新' }));

    const dialog = await screen.findByRole('dialog', { name: '新版本准备就绪' });
    expect(within(dialog).getByText('当前版本：0.1.13')).toBeInTheDocument();
    expect(within(dialog).getByText('新版本：0.1.14')).toBeInTheDocument();
    expect(desktopMocks.installDesktopUpdate).not.toHaveBeenCalled();

    await user.click(within(dialog).getByRole('button', { name: '现在安装' }));

    await waitFor(() => expect(desktopMocks.installDesktopUpdate).toHaveBeenCalledTimes(1));
    expect(dialog).not.toBeInTheDocument();
    expect(screen.getByText('安装中，稍后将自动进入安装状态…')).toBeInTheDocument();
  });
});
