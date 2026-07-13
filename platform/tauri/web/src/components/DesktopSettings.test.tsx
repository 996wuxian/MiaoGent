import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const desktopMocks = vi.hoisted(() => ({
  desktopConfigChecks: (value: { mailProvider: 'qq' | 'netease_163'; mailAddress: string; hasMailAuthCode: boolean; hasDeepseekApiKey: boolean }) => [
    { key: 'mailAddress', label: value.mailProvider === 'netease_163' ? '163 邮箱地址' : 'QQ 邮箱地址', done: Boolean(value.mailAddress.trim()) },
    { key: 'mailAuthCode', label: value.mailProvider === 'netease_163' ? '163 授权码' : 'QQ 授权码', done: value.hasMailAuthCode },
    { key: 'deepseekApiKey', label: 'DeepSeek API Key', done: value.hasDeepseekApiKey },
    { key: 'connection', label: '连接参数', done: true },
  ],
  mailProviderLabel: (value: 'qq' | 'netease_163') => (value === 'netease_163' ? '163 邮箱' : 'QQ 邮箱'),
  mailProviderAuthCodeLabel: (value: 'qq' | 'netease_163') => (value === 'netease_163' ? '163 授权码' : 'QQ 授权码'),
  getDesktopConfig: vi.fn(),
  saveDesktopConfig: vi.fn(),
  clearDesktopUserData: vi.fn(),
  getDesktopAppVersion: vi.fn(),
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
  mailProvider: 'qq' as const,
  mailAddress: 'me@qq.com',
  imapHost: 'imap.qq.com',
  imapPort: 993,
  smtpHost: 'smtp.qq.com',
  smtpPort: 465,
  deepseekBaseUrl: 'https://api.deepseek.com',
  deepseekModel: 'deepseek-chat',
  deepseekTimeoutSeconds: 45,
  privacyProtectionEnabled: true,
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
    desktopMocks.getDesktopAppVersion.mockReset().mockResolvedValue('0.1.20');
  });

  it('saves new secrets without ever reading existing secret values back', async () => {
    const user = userEvent.setup();
    const onSaved = vi.fn();
    render(<DesktopSettings open onClose={() => undefined} onSaved={onSaved} />);

    const authCode = await screen.findByLabelText('QQ 授权码');
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
        mailProvider: 'qq',
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

  it('saves the privacy protection mode toggle', async () => {
    const user = userEvent.setup();
    render(<DesktopSettings open onClose={() => undefined} onSaved={() => undefined} />);

    const toggle = await screen.findByRole('checkbox', { name: /阻止敏感邮件自动 AI 分析/ });
    expect(toggle).toBeChecked();
    await user.click(toggle);
    await user.type(screen.getByLabelText('QQ 授权码'), 'mail-secret');
    await user.type(screen.getByLabelText('API Key'), 'deepseek-secret');
    await user.click(screen.getByRole('button', { name: '保存并重启 Agent' }));

    await waitFor(() => expect(desktopMocks.saveDesktopConfig).toHaveBeenCalledTimes(1));
    expect(desktopMocks.saveDesktopConfig).toHaveBeenCalledWith(
      expect.objectContaining({
        privacyProtectionEnabled: false,
      }),
    );
  });

  it('switches the mail provider tab locally and applies 163 defaults only on save', async () => {
    const user = userEvent.setup();
    render(<DesktopSettings open onClose={() => undefined} onSaved={() => undefined} />);

    await screen.findByRole('tab', { name: 'QQ 邮箱' });
    await user.click(screen.getByRole('tab', { name: '163 邮箱' }));

    expect(screen.getByRole('tab', { name: '163 邮箱' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByLabelText('邮箱地址')).toHaveAttribute('placeholder', 'name@163.com');
    expect(screen.getByLabelText('邮箱地址')).toHaveValue('');
    expect(screen.getByLabelText('163 授权码')).toBeInTheDocument();
    expect(desktopMocks.saveDesktopConfig).not.toHaveBeenCalled();

    await user.click(screen.getByText('高级连接设置'));
    expect(screen.getByLabelText('IMAP 主机')).toHaveValue('imap.qq.com');
    expect(screen.getByLabelText('SMTP 主机')).toHaveValue('smtp.qq.com');

    await user.type(screen.getByLabelText('邮箱地址'), 'me@163.com');
    await user.type(screen.getByLabelText('163 授权码'), 'netease-secret');
    await user.type(screen.getByLabelText('API Key'), 'deepseek-secret');
    await user.click(screen.getByRole('button', { name: '保存并重启 Agent' }));

    await waitFor(() => expect(desktopMocks.saveDesktopConfig).toHaveBeenCalledTimes(1));
    expect(desktopMocks.saveDesktopConfig).toHaveBeenCalledWith(
      expect.objectContaining({
        mailProvider: 'netease_163',
        mailAddress: 'me@163.com',
        imapHost: 'imap.163.com',
        smtpHost: 'smtp.163.com',
        mailAuthCode: 'netease-secret',
      }),
    );
  });

  it('never submits a replacement secret together with its clear flag', async () => {
    desktopMocks.getDesktopConfig.mockResolvedValue({
      ...config,
      hasMailAuthCode: true,
      hasDeepseekApiKey: true,
    });
    const user = userEvent.setup();
    render(<DesktopSettings open onClose={() => undefined} onSaved={() => undefined} />);

    const authCode = await screen.findByLabelText('QQ 授权码');
    await user.type(authCode, 'replacement-secret');
    await user.click(screen.getByRole('checkbox', { name: /清除现有QQ 授权码/ }));
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
    render(<DesktopSettings open onClose={() => undefined} onSaved={() => undefined} />);

    expect(await screen.findByText('当前版本 v0.1.20')).toBeInTheDocument();

    await waitFor(() => expect(desktopMocks.checkDesktopUpdate).toHaveBeenCalledTimes(1));
    expect(screen.getByText('当前已是最新版本。')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '检查更新' })).not.toBeInTheDocument();
  });

  it('explains GitHub updater network failures in Chinese', async () => {
    desktopMocks.checkDesktopUpdate.mockRejectedValue(
      new Error('error sending request for url (https://github.com/996wuxian/MiaoGent/releases/latest/download/latest.json)'),
    );
    const user = userEvent.setup();
    const onNotify = vi.fn();
    const onOpenReleasePage = vi.fn();
    render(
      <DesktopSettings
        open
        onClose={() => undefined}
        onSaved={() => undefined}
        onNotify={onNotify}
        onOpenReleasePage={onOpenReleasePage}
      />,
    );

    await waitFor(() => expect(onNotify).toHaveBeenCalledTimes(1));
    expect(onNotify).toHaveBeenCalledWith(
      'error',
      expect.stringContaining('无法连接 GitHub 更新源'),
      expect.objectContaining({ persist: true, actionLabel: '去官网下载' }),
    );
    expect(onNotify.mock.calls[0][1]).toContain('原始错误：error sending request for url');
    onNotify.mock.calls[0][2].onAction();
    expect(onOpenReleasePage).toHaveBeenCalledTimes(1);
    await user.click(await screen.findByRole('button', { name: '去官网下载' }));
    expect(onOpenReleasePage).toHaveBeenCalledTimes(2);
    expect(screen.getByText('暂时无法连接 GitHub 更新源。你可以稍后重新打开设置页，或去官网下载最新版本。')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('shows cached update check results when GitHub is temporarily unreachable', async () => {
    desktopMocks.checkDesktopUpdate.mockResolvedValue({
      available: true,
      version: '0.1.28',
      currentVersion: '0.1.27',
      date: '2026-07-13T12:00:00Z',
      body: null,
      source: 'cache',
      checkedAt: '2026-07-13T11:30:00Z',
      error: 'GitHub API: network failed',
    });
    const onOpenReleasePage = vi.fn();
    const user = userEvent.setup();
    render(
      <DesktopSettings
        open
        onClose={() => undefined}
        onSaved={() => undefined}
        onOpenReleasePage={onOpenReleasePage}
      />,
    );

    expect(await screen.findByText(/有新的版本 v0.1.28/)).toBeInTheDocument();
    expect(screen.getByText('暂时无法连接 GitHub 更新源，已显示上次成功检查结果。')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '去官网下载' }));
    expect(onOpenReleasePage).toHaveBeenCalledTimes(1);
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

    expect(await screen.findByText('有新的版本 v0.1.14。')).toBeInTheDocument();
    expect(screen.queryByRole('dialog', { name: '新版本准备就绪' })).not.toBeInTheDocument();
    await user.click(await screen.findByRole('button', { name: '现在安装' }));

    const dialog = await screen.findByRole('dialog', { name: '新版本准备就绪' });
    expect(within(dialog).getByText('当前版本：0.1.13')).toBeInTheDocument();
    expect(within(dialog).getByText('新版本：0.1.14')).toBeInTheDocument();
    expect(desktopMocks.installDesktopUpdate).not.toHaveBeenCalled();

    await user.click(within(dialog).getByRole('button', { name: '现在安装' }));

    await waitFor(() => expect(desktopMocks.installDesktopUpdate).toHaveBeenCalledTimes(1));
    expect(dialog).not.toBeInTheDocument();
    expect(screen.getByText('安装中，稍后将自动进入安装状态…')).toBeInTheDocument();
  });

  it('reports desktop update installation failures through the global notification callback', async () => {
    desktopMocks.checkDesktopUpdate.mockResolvedValue({
      available: true,
      version: '0.1.14',
      currentVersion: '0.1.13',
      date: '2026-07-12T00:00:00Z',
      body: null,
    });
    desktopMocks.installDesktopUpdate.mockRejectedValue(new Error('installer failed'));
    const user = userEvent.setup();
    const onNotify = vi.fn();
    const onOpenReleasePage = vi.fn();
    render(
      <DesktopSettings
        open
        onClose={() => undefined}
        onSaved={() => undefined}
        onNotify={onNotify}
        onOpenReleasePage={onOpenReleasePage}
      />,
    );

    expect(await screen.findByText('有新的版本 v0.1.14。')).toBeInTheDocument();
    await user.click(await screen.findByRole('button', { name: '现在安装' }));
    const dialog = await screen.findByRole('dialog', { name: '新版本准备就绪' });
    await user.click(within(dialog).getByRole('button', { name: '现在安装' }));

    await waitFor(() => expect(onNotify).toHaveBeenCalledTimes(1));
    expect(onNotify).toHaveBeenCalledWith(
      'error',
      '安装更新失败：installer failed',
      expect.objectContaining({ persist: true, actionLabel: '去官网下载' }),
    );
    onNotify.mock.calls[0][2].onAction();
    expect(onOpenReleasePage).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});
