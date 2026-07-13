import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import App from './App';
import type { Draft, MailInsight, MailMessage, SearchMailItem, SecretaryInspectionReport } from './types';

const tauriMocks = vi.hoisted(() => ({
  invoke: vi.fn(),
  listen: vi.fn(async () => vi.fn()),
}));

vi.mock('@tauri-apps/api/core', () => ({ invoke: tauriMocks.invoke }));
vi.mock('@tauri-apps/api/event', () => ({ listen: tauriMocks.listen }));

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  tauriMocks.invoke.mockReset();
  tauriMocks.listen.mockReset().mockResolvedValue(vi.fn());
});

function message(id: string, subject: string, isSeen = false): MailMessage {
  return {
    id,
    sender: `${id.toLowerCase()}@example.com`,
    recipient: 'me@example.com',
    subject,
    body: `${subject} 正文`,
    date: '2026-07-10 10:00',
    snippet: `${subject} 摘要`,
    html_body: '',
    remote_images: [],
    inline_images: [],
    attachments: [],
    is_seen: isSeen,
    message_id: `<${id}@example.com>`,
    references: '',
  };
}

function draft(overrides: Partial<Draft> = {}): Draft {
  return {
    draft_id: 'draft-1',
    uid: 'A',
    to_addr: 'a@example.com',
    subject: '旧主题',
    body: '旧正文',
    body_preview: '旧正文',
    reply_to_message_id: '',
    references: '',
    created_at: '2026-07-10 10:00',
    sent_at: null,
    send_status: 'pending',
    ...overrides,
  };
}

function insight(overrides: Partial<MailInsight> = {}): MailInsight {
  return {
    mail_key: 'INBOX-key-1',
    uid: 'uid:10',
    mailbox: 'INBOX',
    source_uidvalidity: 123,
    sender: 'hr@example.com',
    subject: '招聘沟通',
    date: 'Fri, 10 Jul 2026 08:08:09 +0800',
    is_seen: false,
    importance: 'general',
    needs_reply: false,
    summary_zh: '招聘沟通邮件。',
    action_items: [],
    confidence: 0.9,
    priority_reason: '初始标记为一般。',
    analysis_status: 'analyzed',
    reply_status: 'not_needed',
    notification_status: 'not_required',
    analysis_error: null,
    draft_id: null,
    latest_feedback: null,
    feedback_comment: '',
    feedback_updated_at: null,
    analyzed_at: '2026-07-10T08:09:00+08:00',
    updated_at: '2026-07-10T08:09:00+08:00',
    ...overrides,
  };
}

function desktopConfig(overrides: Record<string, unknown> = {}) {
  return {
    mailProvider: 'qq',
    mailAddress: 'me@qq.com',
    imapHost: 'imap.qq.com',
    imapPort: 993,
    smtpHost: 'smtp.qq.com',
    smtpPort: 465,
    deepseekBaseUrl: 'https://api.deepseek.com',
    deepseekModel: 'deepseek-chat',
    deepseekTimeoutSeconds: 45,
    privacyProtectionEnabled: true,
    hasMailAuthCode: true,
    hasDeepseekApiKey: true,
    secretStorage: 'windows_credential_manager',
    ...overrides,
  };
}

function inspectionReport(overrides: Partial<SecretaryInspectionReport> = {}): SecretaryInspectionReport {
  return {
    inspected_at: '2026-07-10 16:00',
    scanned_count: 20,
    processed_count: 4,
    skipped_seen: 8,
    skipped_triaged: 7,
    failed_count: 1,
    current_actionable_count: 3,
    groups: [
      {
        key: 'reply',
        title: '需要回复',
        items: [
          {
            uid: 'PLAN-1',
            sender: 'client@example.com',
            subject: '需要回复客户',
            classification: 'respond',
            reason: '客户提出了明确问题。',
            suggested_action: 'draft_reply',
            action_reason: '准备回复并确认交付时间。',
            queue_status: 'pending',
            updated_at: '2026-07-10 15:58',
          },
        ],
      },
      {
        key: 'review',
        title: '需要查看',
        items: [
          {
            uid: 'PLAN-2',
            sender: 'review@example.com',
            subject: '合同条款待审阅',
            classification: 'notify',
            reason: '包含需要人工判断的条款。',
            suggested_action: 'read_full',
            action_reason: '阅读全文后再决定是否回复。',
            queue_status: 'pending',
            updated_at: '2026-07-10 15:57',
          },
        ],
      },
      {
        key: 'status',
        title: '状态处理建议',
        items: [
          {
            uid: 'PLAN-3',
            sender: 'status@example.com',
            subject: '项目状态更新',
            classification: 'notify',
            reason: '对方同步了进度。',
            suggested_action: 'mark_seen',
            action_reason: '阅读后更新本地处理状态。',
            queue_status: 'later',
            updated_at: '2026-07-10 15:56',
          },
        ],
      },
      {
        key: 'no_action',
        title: '无需行动',
        items: [
          {
            uid: 'PLAN-4',
            sender: 'notice@example.com',
            subject: '系统通知',
            classification: 'ignore',
            reason: '无需人工跟进。',
            suggested_action: 'no_action',
            action_reason: '保留记录即可。',
            queue_status: 'done',
            updated_at: '2026-07-10 15:55',
          },
        ],
      },
    ],
    failures: [{ uid: 'FAIL-1', subject: '解析失败邮件', error: 'DeepSeek 请求超时' }],
    ...overrides,
  };
}

function jsonResponse(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function rect(top: number, bottom: number): DOMRect {
  return {
    top,
    bottom,
    left: 0,
    right: 300,
    width: 300,
    height: bottom - top,
    x: 0,
    y: top,
    toJSON: () => ({}),
  };
}

async function chooseDropdownOption(user: ReturnType<typeof userEvent.setup>, label: string, option: string) {
  await user.click(screen.getByRole('button', { name: new RegExp(`^${label}：`) }));
  const listbox = await screen.findByRole('listbox', { name: label });
  await user.click(within(listbox).getByRole('option', { name: new RegExp(option) }));
}

type FetchHandler = (url: string, init: RequestInit | undefined) => Promise<Response> | Response | undefined;

function installFetch({
  recent = [message('A', 'A 主题'), message('B', 'B 主题')],
  drafts = [],
  handler,
}: {
  recent?: MailMessage[];
  drafts?: Draft[];
  handler?: FetchHandler;
} = {}) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const custom = await handler?.(url, init);
    if (custom) return custom;
    if (url === '/api/health/local') return jsonResponse([{ name: 'local', ok: true, detail: 'ok' }]);
    if (url.startsWith('/api/messages/recent')) return jsonResponse(recent);
    if (url.startsWith('/api/triage/queue')) return jsonResponse([]);
    if (url.startsWith('/api/search/messages')) return jsonResponse([]);
    if (url.startsWith('/api/drafts?')) return jsonResponse(drafts);
    if (url.startsWith('/api/actions')) return jsonResponse([]);
    if (url.startsWith('/api/desktop/fetch-failures')) return jsonResponse([]);
    if (url.includes('/mark-seen')) return jsonResponse({ ok: true, detail: 'seen' });
    if (url.startsWith('/api/messages/')) {
      const id = decodeURIComponent(url.slice('/api/messages/'.length));
      return jsonResponse(recent.find((item) => item.id === id) ?? message(id, `${id} 主题`));
    }
    throw new Error(`Unhandled fetch: ${url}`);
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

describe('MiaoGent workbench', () => {
  it('格式化列表和详情里的邮件时间', async () => {
    const dated = { ...message('D', '带日期邮件'), date: 'Fri, 10 Jul 2026 08:08:09 +0800' };
    installFetch({ recent: [dated] });
    const user = userEvent.setup();
    render(<App />);

    expect(await screen.findByText('07-10 08:08')).toBeInTheDocument();
    expect(screen.queryByText('Fri, 10 Jul 2026 08:08:09 +0800')).not.toBeInTheDocument();

    await user.click(screen.getByText('带日期邮件'));
    expect(await screen.findByRole('heading', { name: '带日期邮件' })).toBeInTheDocument();
    expect(screen.getByText('2026-07-10 08:08')).toBeInTheDocument();
  });

  it('成功类全局提示会自动消失，错误提示保持可见', async () => {
    const user = userEvent.setup();
    installFetch({
      handler: (url, init) => {
        if (url === '/api/messages/A/draft' && init?.method === 'POST') {
          return jsonResponse({ detail: 'Draft failed' }, 500);
        }
        return undefined;
      },
    });
    render(<App />);

    await user.click(await screen.findByText('A 主题'));
    expect(await screen.findByText('已同步标记为已读。')).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText('已同步标记为已读。')).not.toBeInTheDocument(), { timeout: 2600 });

    await user.click(screen.getByRole('button', { name: '生成草稿' }));
    const dialog = await screen.findByRole('dialog', { name: '确认生成回复草稿' });
    await user.click(within(dialog).getByRole('button', { name: '生成草稿' }));
    await waitFor(() => expect(screen.getByText('Draft failed')).toBeInTheDocument());
    await new Promise((resolve) => {
      window.setTimeout(resolve, 2100);
    });
    expect(screen.getByText('Draft failed')).toBeInTheDocument();
  }, 10000);

  it('右侧面板可以人工修改重要性和待回复标记', async () => {
    const initialInsight = insight();
    const fetchMock = installFetch({
      recent: [{ ...message('uid:10', '招聘沟通'), date: 'Fri, 10 Jul 2026 08:08:09 +0800' }],
      handler: (url, init) => {
        if (url.startsWith('/api/insights?')) return jsonResponse([initialInsight]);
        if (url === '/api/insights/uid%3A10') return jsonResponse(initialInsight);
        if (url === '/api/insights/uid%3A10/labels' && init?.method === 'PATCH') {
          const payload = JSON.parse(String(init.body)) as { importance: MailInsight['importance']; needs_reply: boolean };
          return jsonResponse(insight({
            importance: payload.importance,
            needs_reply: payload.needs_reply,
            reply_status: payload.needs_reply ? 'needs_reply' : 'not_needed',
            notification_status: payload.importance === 'general' ? 'not_required' : 'pending',
            priority_reason: '人工更新标记。',
          }));
        }
        return undefined;
      },
    });
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole('tab', { name: '全部' }));
    await user.click(await screen.findByText('招聘沟通'));
    await user.click(within(screen.getByRole('group', { name: '重要性标记' })).getByRole('button', { name: '重要' }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([url, init]) => String(url) === '/api/insights/uid%3A10/labels' && init?.method === 'PATCH');
      expect(call).toBeTruthy();
      expect(JSON.parse(String(call?.[1]?.body))).toEqual({ importance: 'important', needs_reply: false });
    });

    await user.click(screen.getByLabelText('待回复'));
    await waitFor(() => {
      const calls = fetchMock.mock.calls.filter(([url, init]) => String(url) === '/api/insights/uid%3A10/labels' && init?.method === 'PATCH');
      const lastCall = calls[calls.length - 1];
      expect(JSON.parse(String(lastCall?.[1]?.body))).toEqual({ importance: 'important', needs_reply: true });
    });
    expect(screen.getAllByText('重要').length).toBeGreaterThan(0);
    expect(screen.queryAllByText('需要回复').length + screen.queryAllByText('待回复').length).toBeGreaterThan(0);
  });

  it('右侧面板可以记录 AI 判断反馈', async () => {
    const initialInsight = insight({ needs_reply: true, reply_status: 'needs_reply' });
    const fetchMock = installFetch({
      recent: [message('uid:10', '招聘沟通')],
      handler: (url, init) => {
        if (url.startsWith('/api/insights?')) return jsonResponse([initialInsight]);
        if (url === '/api/insights/uid%3A10') return jsonResponse(initialInsight);
        if (url === '/api/insights/uid%3A10/feedback' && init?.method === 'POST') {
          return jsonResponse({
            id: 1,
            mail_key: initialInsight.mail_key,
            uid: initialInsight.uid,
            feedback: 'wrong',
            comment: '',
            importance_at_feedback: 'general',
            needs_reply_at_feedback: true,
            created_at: '2026-07-10T08:10:00+08:00',
            updated_at: '2026-07-10T08:10:00+08:00',
          });
        }
        return undefined;
      },
    });
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole('tab', { name: '全部' }));
    await user.click(await screen.findByText('招聘沟通'));
    await user.click(within(screen.getByRole('group', { name: 'AI 判断反馈' })).getByRole('button', { name: '不准确' }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([url, init]) => String(url) === '/api/insights/uid%3A10/feedback' && init?.method === 'POST');
      expect(call).toBeTruthy();
      expect(JSON.parse(String(call?.[1]?.body))).toEqual({ feedback: 'wrong', comment: '' });
    });
    expect(await screen.findByText('已标记为不准确')).toBeInTheDocument();
  });

  it('桌面端刷新工作台会先同步邮箱并重拉全部邮件视图', async () => {
    vi.stubGlobal('__TAURI_INTERNALS__', {});
    tauriMocks.invoke.mockReset();
    tauriMocks.listen.mockReset().mockResolvedValue(vi.fn());
    tauriMocks.invoke.mockImplementation(async (command: string) => {
      if (command === 'backend_connection') return { base_url: '', token: 'desktop-token' };
      if (command === 'take_pending_navigation') return null;
      if (command === 'desktop_config') return desktopConfig();
      return null;
    });
    const calls: string[] = [];
    const fetchMock = installFetch({
      recent: [message('NEW', '新招聘邮件')],
      handler: (url, init) => {
        calls.push(`${init?.method ?? 'GET'} ${url}`);
        if (url === '/api/desktop/startup-summary/latest') return jsonResponse(null);
        if (url === '/api/desktop/sync' && init?.method === 'POST') {
          return jsonResponse({
            trigger: 'manual',
            generated_at: '2026-07-11T04:10:00Z',
            new_count: 1,
            processed_count: 1,
            important_count: 1,
            urgent_count: 0,
            reply_count: 0,
            draft_ready_count: 0,
            general_count: 0,
            failed_count: 0,
            has_more: false,
            items: [],
            failures: [],
          });
        }
        if (url.startsWith('/api/insights')) return jsonResponse([]);
        return undefined;
      },
    });

    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole('tab', { name: '邮件' }));
    await user.click(screen.getByRole('button', { name: '刷新工作台' }));

    expect(await screen.findByText('新招聘邮件')).toBeInTheDocument();
    const syncIndex = calls.findIndex((call) => call === 'POST /api/desktop/sync');
    const mailboxIndex = calls.findIndex(
      (call, index) => index > syncIndex && call === 'GET /api/messages/recent?limit=100&offset=0',
    );
    expect(syncIndex).toBeGreaterThanOrEqual(0);
    expect(mailboxIndex).toBeGreaterThan(syncIndex);
    expect(fetchMock).toHaveBeenCalledWith('/api/desktop/sync', expect.objectContaining({ method: 'POST' }));
  });

  it('桌面配置未完成时收到启动汇总事件也不直接弹窗', async () => {
    vi.stubGlobal('__TAURI_INTERNALS__', {});
    const listeners: Record<string, (event: { payload: unknown }) => void> = {};
    tauriMocks.invoke.mockReset();
    tauriMocks.listen.mockReset().mockImplementation(async (eventName?: string, callback?: (event: { payload: unknown }) => void) => {
      if (eventName && callback) listeners[eventName] = callback;
      return vi.fn();
    });
    tauriMocks.invoke.mockImplementation(async (command: string) => {
      if (command === 'backend_connection') return { base_url: '', token: 'desktop-token' };
      if (command === 'take_pending_navigation') return null;
      if (command === 'desktop_config') return desktopConfig({ hasMailAuthCode: false, hasDeepseekApiKey: false });
      return null;
    });
    installFetch({
      handler: (url) => {
        if (url === '/api/desktop/startup-summary/latest') return jsonResponse(null);
        if (url.startsWith('/api/insights')) return jsonResponse([]);
        return undefined;
      },
    });

    render(<App />);
    await waitFor(() => expect(listeners['qq-mail-event']).toBeTruthy());
    listeners['qq-mail-event']({
      payload: {
        event: 'startup_summary',
        payload: {
          trigger: 'startup',
          generated_at: '2026-07-11T04:10:00Z',
          new_count: 1,
          processed_count: 1,
          important_count: 1,
          urgent_count: 0,
          reply_count: 0,
          draft_ready_count: 0,
          general_count: 0,
          failed_count: 0,
          has_more: false,
          items: [],
          failures: [],
        },
      },
    });

    expect(await screen.findByText('桌面 Agent 配置未完成')).toBeInTheDocument();
    expect(document.querySelector('.startup-summary-drawer')).not.toBeInTheDocument();
  });

  it('桌面配置完成时收到启动汇总事件也不自动弹窗', async () => {
    vi.stubGlobal('__TAURI_INTERNALS__', {});
    const listeners: Record<string, (event: { payload: unknown }) => void> = {};
    tauriMocks.invoke.mockReset();
    tauriMocks.listen.mockReset().mockImplementation(async (eventName?: string, callback?: (event: { payload: unknown }) => void) => {
      if (eventName && callback) listeners[eventName] = callback;
      return vi.fn();
    });
    tauriMocks.invoke.mockImplementation(async (command: string) => {
      if (command === 'backend_connection') return { base_url: '', token: 'desktop-token' };
      if (command === 'take_pending_navigation') return null;
      if (command === 'desktop_config') return desktopConfig();
      return null;
    });
    installFetch({
      handler: (url) => {
        if (url === '/api/desktop/startup-summary/latest') return jsonResponse(null);
        if (url.startsWith('/api/insights')) return jsonResponse([]);
        return undefined;
      },
    });

    render(<App />);
    await waitFor(() => expect(listeners['qq-mail-event']).toBeTruthy());

    listeners['qq-mail-event']({
      payload: {
        event: 'startup_summary',
        payload: {
          trigger: 'startup',
          generated_at: '2026-07-11T04:10:00Z',
          new_count: 2,
          processed_count: 2,
          important_count: 1,
          urgent_count: 0,
          reply_count: 1,
          draft_ready_count: 1,
          general_count: 1,
          failed_count: 0,
          has_more: false,
          items: [],
          failures: [],
        },
      },
    });

    expect(document.querySelector('.startup-summary-drawer')).not.toBeInTheDocument();
  });

  it('左侧一级入口不再显示最近，邮件入口承载全部视图', async () => {
    Reflect.deleteProperty(window, '__TAURI_INTERNALS__');
    installFetch({ recent: [message('M1', '全部视图邮件')] });
    render(<App />);

    expect(await screen.findByRole('tab', { name: '邮件' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.queryByRole('tab', { name: '最近' })).not.toBeInTheDocument();
    expect(await screen.findByText('全部视图邮件')).toBeInTheDocument();
  });

  it('全部页以当前邮箱列表为基准，合并洞察后排序并隐藏已处理项', async () => {
    const currentMessages = [
      message('U4', '未读一般', false),
      message('R4', '已读一般', true),
      message('U2', '未读重要', false),
      message('R3', '已读待回复', true),
      message('U1', '未读紧急', false),
      message('R2', '已读重要', true),
      message('U3', '未读待回复', false),
      message('R1', '已读紧急', true),
      message('DONE', '已处理紧急', false),
    ];
    installFetch({
      recent: currentMessages,
      handler: (url) => {
        if (url.startsWith('/api/insights')) {
          return jsonResponse([
            insight({ uid: 'U1', subject: '未读紧急', importance: 'urgent', is_seen: false }),
            insight({ uid: 'U2', subject: '未读重要', importance: 'important', is_seen: false }),
            insight({ uid: 'U3', subject: '未读待回复', needs_reply: true, reply_status: 'needs_reply', is_seen: false }),
            insight({ uid: 'U4', subject: '未读一般', importance: 'general', is_seen: false }),
            insight({ uid: 'R1', subject: '已读紧急', importance: 'urgent', is_seen: true }),
            insight({ uid: 'R2', subject: '已读重要', importance: 'important', is_seen: true }),
            insight({ uid: 'R3', subject: '已读待回复', needs_reply: true, reply_status: 'needs_reply', is_seen: true }),
            insight({ uid: 'R4', subject: '已读一般', importance: 'general', is_seen: true }),
            insight({ uid: 'DONE', subject: '已处理紧急', importance: 'urgent', is_seen: false, queue_status: 'done' }),
            insight({ uid: 'HIST', subject: '历史缓存邮件', importance: 'urgent', is_seen: false }),
          ]);
        }
        return undefined;
      },
    });
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole('tab', { name: '全部' }));
    await screen.findByText('未读紧急');

    const subjects = Array.from(document.querySelectorAll('.mail-list .mail-subject')).map((node) => node.textContent);
    expect(subjects).toEqual([
      '未读紧急',
      '未读重要',
      '未读待回复',
      '未读一般',
      '已读紧急',
      '已读重要',
      '已读待回复',
      '已读一般',
    ]);
    expect(screen.getByText('8 项')).toBeInTheDocument();
    expect(screen.queryByText('已处理紧急')).not.toBeInTheDocument();
    expect(screen.queryByText('历史缓存邮件')).not.toBeInTheDocument();
  });

  it('在全部页打开未读邮件后左侧基准列表同步更新为已读', async () => {
    installFetch({
      recent: [message('U1', '未读紧急', false)],
      handler: (url) => {
        if (url === '/api/insights/U1') {
          return jsonResponse(insight({ uid: 'U1', subject: '未读紧急', importance: 'urgent', is_seen: false }));
        }
        if (url.startsWith('/api/insights?')) {
          return jsonResponse([insight({ uid: 'U1', subject: '未读紧急', importance: 'urgent', is_seen: false })]);
        }
        return undefined;
      },
    });
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole('tab', { name: '全部' }));
    const card = (await screen.findByText('未读紧急')).closest('article') as HTMLElement;
    expect(within(card).getByText('未读')).toBeInTheDocument();

    await user.click(within(card).getByRole('button', { name: /未读紧急/ }));
    expect(await screen.findByText('已同步标记为已读。')).toBeInTheDocument();

    await waitFor(() => {
      expect(within(card).getByText('已读')).toBeInTheDocument();
      expect(within(card).queryByText('未读')).not.toBeInTheDocument();
    });
  });

  it('选中邮件排序移动后会定位当前卡片，并提供回到顶部按钮', async () => {
    installFetch({
      recent: [
        message('U1', '未读紧急', false),
        message('R1', '已读紧急', true),
      ],
      handler: (url) => {
        if (url === '/api/insights/U1') {
          return jsonResponse(insight({ uid: 'U1', subject: '未读紧急', importance: 'urgent', is_seen: false }));
        }
        if (url.startsWith('/api/insights?')) {
          return jsonResponse([
            insight({ uid: 'U1', subject: '未读紧急', importance: 'urgent', is_seen: false }),
            insight({ uid: 'R1', subject: '已读紧急', importance: 'urgent', is_seen: true }),
          ]);
        }
        return undefined;
      },
    });
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole('tab', { name: '全部' }));
    const list = document.querySelector('.mail-list') as HTMLElement;
    const scrollTo = vi.fn((options: ScrollToOptions) => {
      if (typeof options.top === 'number') list.scrollTop = options.top;
    });
    Object.defineProperty(list, 'scrollTop', { configurable: true, writable: true, value: 40 });
    Object.defineProperty(list, 'scrollTo', { configurable: true, value: scrollTo });
    Object.defineProperty(list, 'getBoundingClientRect', { configurable: true, value: () => rect(0, 100) });

    const card = (await screen.findByText('未读紧急')).closest('article') as HTMLElement;
    Object.defineProperty(card, 'getBoundingClientRect', { configurable: true, value: () => rect(140, 200) });
    await user.click(within(card).getByRole('button', { name: /未读紧急/ }));

    await waitFor(() => expect(scrollTo).toHaveBeenCalledWith(expect.objectContaining({ top: 152, behavior: 'smooth' })));

    scrollTo.mockClear();
    await user.click(screen.getByRole('button', { name: '回到邮件列表顶部' }));
    expect(scrollTo).toHaveBeenCalledWith({ top: 0, behavior: 'smooth' });
  });

  it('连续点击标题五次后要求密码并打开 Tauri 开发者控制台', async () => {
    vi.stubGlobal('__TAURI_INTERNALS__', {});
    tauriMocks.invoke.mockReset();
    tauriMocks.listen.mockReset().mockResolvedValue(vi.fn());
    tauriMocks.invoke.mockImplementation(async (command: string, args?: Record<string, unknown>) => {
      if (command === 'backend_connection' || command === 'take_pending_navigation') return null;
      if (command === 'desktop_config') return desktopConfig();
      if (command === 'open_devtools') {
        if (args?.password !== 'iopp') throw new Error('开发者控制台密码不正确');
        return undefined;
      }
      return null;
    });

    const user = userEvent.setup();
    render(<App />);

    const title = screen.getByRole('button', { name: 'MiaoGent' });
    for (let index = 0; index < 5; index += 1) {
      await user.click(title);
    }

    const dialog = await screen.findByRole('dialog', { name: '打开开发者控制台' });
    fireEvent.mouseDown(document.querySelector('.modal-backdrop') as HTMLElement);
    expect(screen.getByRole('dialog', { name: '打开开发者控制台' })).toBeInTheDocument();

    await user.type(within(dialog).getByLabelText('密码'), 'wrong');
    await user.click(within(dialog).getByRole('button', { name: '打开' }));
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('开发者控制台密码不正确');
    expect(tauriMocks.invoke).toHaveBeenCalledWith('open_devtools', { password: 'wrong' });

    await user.clear(within(dialog).getByLabelText('密码'));
    await user.type(within(dialog).getByLabelText('密码'), 'iopp');
    await user.click(within(dialog).getByRole('button', { name: '打开' }));

    await waitFor(() => expect(screen.queryByRole('dialog', { name: '打开开发者控制台' })).not.toBeInTheDocument());
    expect(tauriMocks.invoke).toHaveBeenCalledWith('open_devtools', { password: 'iopp' });
  });

  it('全局阻止右键和 DevTools 快捷键但不阻止普通复制快捷键', async () => {
    installFetch();
    render(<App />);

    const contextMenuEvent = new MouseEvent('contextmenu', { bubbles: true, cancelable: true });
    document.dispatchEvent(contextMenuEvent);
    expect(contextMenuEvent.defaultPrevented).toBe(true);

    const f12Event = new KeyboardEvent('keydown', { key: 'F12', bubbles: true, cancelable: true });
    document.dispatchEvent(f12Event);
    expect(f12Event.defaultPrevented).toBe(true);

    const inspectEvent = new KeyboardEvent('keydown', {
      key: 'I',
      ctrlKey: true,
      shiftKey: true,
      bubbles: true,
      cancelable: true,
    });
    document.dispatchEvent(inspectEvent);
    expect(inspectEvent.defaultPrevented).toBe(true);

    const copyEvent = new KeyboardEvent('keydown', {
      key: 'c',
      ctrlKey: true,
      bubbles: true,
      cancelable: true,
    });
    document.dispatchEvent(copyEvent);
    expect(copyEvent.defaultPrevented).toBe(false);
  });

  it('提供全部、待回复、重要、紧急、一般五个 Agent 视图并使用正交筛选', async () => {
    const user = userEvent.setup();
    const fetchMock = installFetch({
      handler: (url) => {
        if (url.startsWith('/api/insights')) return jsonResponse([]);
        return undefined;
      },
    });
    render(<App />);

    for (const label of ['全部', '待回复', '重要', '紧急', '一般']) {
      expect(screen.getByRole('tab', { name: label })).toBeInTheDocument();
    }

    await user.click(screen.getByRole('tab', { name: '待回复' }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('reply_pending=true'), expect.anything()));
    await user.click(screen.getByRole('tab', { name: '重要' }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('importance=important'), expect.anything()));
    await user.click(screen.getByRole('tab', { name: '紧急' }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('importance=urgent'), expect.anything()));
    await user.click(screen.getByRole('tab', { name: '一般' }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('importance=general'), expect.anything()));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('analysis_status=analyzed'), expect.anything()));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('min_confidence=0.55'), expect.anything()));
  });

  it('在全部视图置顶展示持久的邮件读取失败并允许按 UID 重试打开', async () => {
    const user = userEvent.setup();
    const fetchMock = installFetch({
      handler: (url) => {
        if (url.startsWith('/api/insights?')) return jsonResponse([]);
        if (url.startsWith('/api/insights/')) return jsonResponse({ detail: 'not found' }, 404);
        if (url.startsWith('/api/desktop/fetch-failures')) {
          return jsonResponse([
            {
              mail_key: 'INBOX-key',
              mailbox: 'INBOX',
              uid_validity: 456,
              uid: 9,
              failure_count: 3,
              quarantined: true,
              attention_status: 'attention_emitted',
              last_failed_at: '2026-07-10T08:00:00+08:00',
              resolved_at: null,
            },
          ]);
        }
        return undefined;
      },
    });
    render(<App />);

    await user.click(screen.getByRole('tab', { name: '全部' }));
    await screen.findByText('邮件读取失败（UID 9）');
    expect(screen.getByText('待人工查看')).toBeInTheDocument();

    await user.click(screen.getByText('邮件读取失败（UID 9）'));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith('/api/messages/uid%3A9', expect.anything()),
    );
  });

  it('邮件洞察接口失败时仍展示已经取得的持久读取失败项', async () => {
    const user = userEvent.setup();
    installFetch({
      recent: [],
      handler: (url) => {
        if (url.startsWith('/api/insights?')) return jsonResponse({ detail: 'insights unavailable' }, 503);
        if (url.startsWith('/api/desktop/fetch-failures')) {
          return jsonResponse([
            {
              mail_key: 'INBOX-key-12',
              mailbox: 'INBOX',
              uid_validity: 456,
              uid: 12,
              failure_count: 2,
              quarantined: true,
              attention_status: 'attention_emitted',
              last_failed_at: '2026-07-10T08:10:00+08:00',
              resolved_at: null,
            },
          ]);
        }
        return undefined;
      },
    });
    render(<App />);

    await user.click(screen.getByRole('tab', { name: '全部' }));
    expect(await screen.findByText('邮件读取失败（UID 12）')).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('邮件洞察');
    expect(screen.getByText('1 项')).toBeInTheDocument();
  });

  it('在全部视图把低置信度洞察显示为待人工查看而不是一般邮件', async () => {
    const user = userEvent.setup();
    installFetch({
      recent: [message('uid:10', '低置信度洞察')],
      handler: (url) => {
        if (url.startsWith('/api/insights?')) {
          return jsonResponse([
            {
              uid: 'uid:10',
              sender: 'low@example.com',
              subject: '低置信度洞察',
              date: '2026-07-10T08:00:00+08:00',
              updated_at: '2026-07-10T08:00:00+08:00',
              is_seen: false,
              importance: 'general',
              needs_reply: false,
              summary_zh: '判断不确定',
              confidence: 0.4,
              analysis_status: 'analyzed',
              reply_status: 'not_needed',
              draft_id: null,
            },
          ]);
        }
        return undefined;
      },
    });
    render(<App />);

    await user.click(screen.getByRole('tab', { name: '全部' }));
    const card = (await screen.findByText('低置信度洞察')).closest('article');
    expect(card).not.toBeNull();
    expect(within(card as HTMLElement).getByText('待人工查看')).toBeInTheDocument();
    expect(within(card as HTMLElement).queryByText('一般')).not.toBeInTheDocument();
  });

  it('在全部视图和详情顶部展示隐私保护命中的敏感标记', async () => {
    const sensitiveInsight = insight({
      uid: 'uid:10',
      subject: '录取通知书',
      summary_zh: '隐私保护模式已跳过 AI 处理。',
      priority_reason: 'PrivacyProtected: 命中敏感关键词。',
      analysis_status: 'skipped',
      analysis_error: 'privacy_sensitive',
    });
    installFetch({
      recent: [message('uid:10', '录取通知书')],
      handler: (url) => {
        if (url.startsWith('/api/insights?')) return jsonResponse([sensitiveInsight]);
        if (url === '/api/insights/uid%3A10') return jsonResponse(sensitiveInsight);
        return undefined;
      },
    });
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole('tab', { name: '全部' }));
    const card = (await screen.findByText('录取通知书')).closest('article');
    expect(card).not.toBeNull();
    expect(within(card as HTMLElement).getByText('敏感')).toBeInTheDocument();

    await user.click(within(card as HTMLElement).getByRole('button', { name: /录取通知书/ }));
    const panel = (await screen.findByRole('heading', { name: '录取通知书' })).closest('.reading-panel');
    expect(panel).not.toBeNull();
    expect(within(panel as HTMLElement).getAllByText('敏感').length).toBeGreaterThanOrEqual(1);
  });

  it('旧洞察未写入隐私错误时也会按敏感主题显示敏感标记', async () => {
    const legacyInsight = insight({
      uid: 'uid:10',
      subject: '录用通知书-云宏信息',
      importance: 'important',
      needs_reply: true,
      reply_status: 'draft_ready',
      summary_zh: '已生成录用沟通草稿。',
      priority_reason: '对方需要确认。',
      analysis_status: 'analyzed',
      analysis_error: null,
    });
    installFetch({
      recent: [message('uid:10', '录用通知书-云宏信息', true)],
      handler: (url) => {
        if (url.startsWith('/api/insights?')) return jsonResponse([legacyInsight]);
        if (url === '/api/insights/uid%3A10') return jsonResponse(legacyInsight);
        return undefined;
      },
    });
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole('tab', { name: '全部' }));
    const card = (await screen.findByText('录用通知书-云宏信息')).closest('article');
    expect(card).not.toBeNull();
    expect(within(card as HTMLElement).getByText('敏感')).toBeInTheDocument();

    await user.click(within(card as HTMLElement).getByRole('button', { name: /录用通知书-云宏信息/ }));
    const badges = document.querySelector('.message-badges') as HTMLElement;
    expect(within(badges).getByText('敏感')).toBeInTheDocument();
  });

  it('标题分类后无摘要时可按需生成一般邮件摘要', async () => {
    const titleOnlyInsight = insight({
      uid: 'uid:10',
      subject: '普通项目沟通',
      summary_zh: '',
      analysis_status: 'title_classified',
      importance: 'general',
      needs_reply: false,
      analysis_error: null,
    });
    const generatedInsight = insight({
      ...titleOnlyInsight,
      summary_zh: '这是按需生成的摘要。',
      analysis_status: 'analyzed',
    });
    const fetchMock = installFetch({
      recent: [message('uid:10', '普通项目沟通', true)],
      handler: (url, init) => {
        if (url.startsWith('/api/insights?')) return jsonResponse([titleOnlyInsight]);
        if (url === '/api/insights/uid%3A10') return jsonResponse(titleOnlyInsight);
        if (url === '/api/messages/uid%3A10/summary' && init?.method === 'POST') return jsonResponse(generatedInsight);
        return undefined;
      },
    });
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole('tab', { name: '全部' }));
    const card = (await screen.findByText('普通项目沟通')).closest('article');
    expect(card).not.toBeNull();
    await user.click(within(card as HTMLElement).getByRole('button', { name: /普通项目沟通/ }));

    expect(await screen.findByText('尚未生成 Agent 摘要。')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '生成摘要' }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([url, init]) => String(url) === '/api/messages/uid%3A10/summary' && init?.method === 'POST');
      expect(call).toBeTruthy();
      expect(JSON.parse(String(call?.[1]?.body))).toEqual({ confirmed: false });
    });
    expect((await screen.findAllByText('这是按需生成的摘要。')).length).toBeGreaterThanOrEqual(1);
    expect(screen.queryByRole('dialog', { name: /确认为/ })).not.toBeInTheDocument();
  });

  it('敏感邮件按需生成摘要前必须二次确认', async () => {
    const sensitiveInsight = insight({
      uid: 'uid:10',
      subject: '录用通知 Offer Letter',
      summary_zh: '',
      analysis_status: 'title_classified',
      importance: 'important',
      needs_reply: false,
      analysis_error: 'privacy_sensitive',
    });
    const generatedInsight = insight({
      ...sensitiveInsight,
      summary_zh: '敏感邮件确认后生成的摘要。',
      analysis_status: 'analyzed',
    });
    const fetchMock = installFetch({
      recent: [message('uid:10', '录用通知 Offer Letter', true)],
      handler: (url, init) => {
        if (url.startsWith('/api/insights?')) return jsonResponse([sensitiveInsight]);
        if (url === '/api/insights/uid%3A10') return jsonResponse(sensitiveInsight);
        if (url === '/api/messages/uid%3A10/summary' && init?.method === 'POST') return jsonResponse(generatedInsight);
        return undefined;
      },
    });
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole('tab', { name: '全部' }));
    const card = (await screen.findByText('录用通知 Offer Letter')).closest('article');
    expect(card).not.toBeNull();
    await user.click(within(card as HTMLElement).getByRole('button', { name: /录用通知 Offer Letter/ }));
    await user.click(await screen.findByRole('button', { name: '生成摘要' }));

    const dialog = await screen.findByRole('dialog', { name: '确认为敏感邮件生成摘要' });
    expect(within(dialog).getByText('生成摘要会把邮件正文发送给 AI 服务。请确认你接受这次发送。')).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url]) => String(url) === '/api/messages/uid%3A10/summary')).toBe(false);

    await user.click(within(dialog).getByRole('button', { name: '确认生成摘要' }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([url, init]) => String(url) === '/api/messages/uid%3A10/summary' && init?.method === 'POST');
      expect(call).toBeTruthy();
      expect(JSON.parse(String(call?.[1]?.body))).toEqual({ confirmed: true });
    });
    expect((await screen.findAllByText('敏感邮件确认后生成的摘要。')).length).toBeGreaterThanOrEqual(1);
  });

  it('详情顶部折叠队列和洞察的重复待回复标签', async () => {
    const replyInsight = insight({
      uid: 'uid:10',
      subject: '需要回复的合作邮件',
      importance: 'important',
      needs_reply: true,
      reply_status: 'needs_reply',
    });
    installFetch({
      recent: [message('uid:10', '需要回复的合作邮件', true)],
      handler: (url) => {
        if (url.startsWith('/api/insights?')) return jsonResponse([replyInsight]);
        if (url === '/api/insights/uid%3A10') return jsonResponse(replyInsight);
        if (url.startsWith('/api/triage/queue')) {
          return jsonResponse([
            {
              uid: 'uid:10',
              sender: 'partner@example.com',
              subject: '需要回复的合作邮件',
              date: '2026-07-10',
              is_seen: true,
              classification: 'respond',
              suggested_action: 'draft_reply',
              queue_status: 'pending',
              reason: '需要回复',
              action_reason: '生成回复草稿',
              updated_at: '2026-07-10',
            },
          ]);
        }
        return undefined;
      },
    });
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole('tab', { name: '全部' }));
    await user.click(await screen.findByText('需要回复的合作邮件'));
    const badges = document.querySelector('.message-badges') as HTMLElement;
    expect(within(badges).getByText('已读')).toBeInTheDocument();
    expect(within(badges).getByText('重要')).toBeInTheDocument();
    expect(within(badges).getByText('待回复')).toBeInTheDocument();
    expect(within(badges).queryByText('待处理')).not.toBeInTheDocument();
    expect(within(badges).queryByText('需回复')).not.toBeInTheDocument();
    expect(within(badges).queryByText('需要回复')).not.toBeInTheDocument();
  });

  it('快速切换时只展示并自动标记最终有效选择', async () => {
    const detailA = deferred<Response>();
    const detailB = deferred<Response>();
    const fetchMock = installFetch({
      handler: (url) => {
        if (url === '/api/messages/A') return detailA.promise;
        if (url === '/api/messages/B') return detailB.promise;
        return undefined;
      },
    });

    const user = userEvent.setup();
    render(<App />);
    await screen.findByText('A 主题');

    await user.click(screen.getByText('A 主题'));
    await user.click(screen.getByText('B 主题'));
    detailB.resolve(jsonResponse(message('B', 'B 主题', false)));

    await screen.findByRole('heading', { name: 'B 主题' });
    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([url]) => String(url) === '/api/messages/B/mark-seen')).toBe(true);
    });

    detailA.resolve(jsonResponse(message('A', 'A 主题', false)));
    await Promise.resolve();

    expect(screen.getByRole('heading', { name: 'B 主题' })).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url]) => String(url) === '/api/messages/A/mark-seen')).toBe(false);
  });

  it('翻译结果通过原文和译文 tabs 切换展示', async () => {
    installFetch({
      recent: [message('A', 'A 主题', true)],
      handler: (url, init) => {
        if (url === '/api/messages/A/translate' && init?.method === 'POST') {
          return jsonResponse({ mail_id: 'A', subject_zh: 'A 中文主题', body_zh: 'A 中文译文内容' });
        }
        return undefined;
      },
    });
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByText('A 主题'));
    await user.click(screen.getByRole('button', { name: '翻译' }));
    const dialog = await screen.findByRole('dialog', { name: '确认发送给 DeepSeek 翻译' });
    await user.click(within(dialog).getByRole('button', { name: '确认翻译' }));

    expect(await screen.findByRole('tab', { name: '译文' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByText('A 中文主题')).toBeInTheDocument();
    expect(screen.getByText('A 中文译文内容')).toBeInTheDocument();
    expect(screen.queryByText('A 主题 正文')).not.toBeInTheDocument();

    await user.click(screen.getByRole('tab', { name: '原文' }));
    expect(screen.getByText('A 主题 正文')).toBeInTheDocument();
    expect(screen.queryByText('A 中文译文内容')).not.toBeInTheDocument();
  });

  it('发送前保存当前编辑快照，确认框与真实发送使用同一版本', async () => {
    const initialDraft = draft();
    let storedDraft = initialDraft;
    const requestOrder: string[] = [];
    const fetchMock = installFetch({
      recent: [message('A', 'A 主题', true)],
      drafts: [initialDraft],
      handler: (url, init) => {
        if (url === '/api/drafts/draft-1' && init?.method === 'PATCH') {
          requestOrder.push('patch');
          const payload = JSON.parse(String(init.body)) as { subject: string; body: string };
          storedDraft = { ...storedDraft, ...payload };
          return jsonResponse(storedDraft);
        }
        if (url === '/api/drafts/draft-1/send' && init?.method === 'POST') {
          requestOrder.push('send');
          return jsonResponse({ draft_id: 'draft-1', summary: '发送成功', send_status: 'sent' });
        }
        return undefined;
      },
    });

    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole('tab', { name: /草稿/ });
    await user.click(screen.getByRole('tab', { name: /草稿/ }));

    const subject = await screen.findByLabelText('主题');
    const body = screen.getByLabelText('正文');
    await user.clear(subject);
    await user.type(subject, '新主题');
    await user.clear(body);
    await user.type(body, '新正文内容');
    await user.click(screen.getByRole('button', { name: '保存并发送' }));

    const dialog = await screen.findByRole('dialog', { name: '确认发送邮件' });
    expect(within(dialog).getByText('新主题')).toBeInTheDocument();
    expect(within(dialog).getByText('新正文内容')).toBeInTheDocument();
    expect(JSON.parse(String(fetchMock.mock.calls.find(([url, init]) => String(url) === '/api/drafts/draft-1' && init?.method === 'PATCH')?.[1]?.body))).toEqual({
      subject: '新主题',
      body: '新正文内容',
    });

    await user.click(within(dialog).getByRole('button', { name: '确认发送' }));
    await waitFor(() => expect(requestOrder).toEqual(['patch', 'send']));
  });

  it('草稿页只保留下拉选择入口，不再重复渲染草稿列表', async () => {
    installFetch({
      recent: [message('A', 'A 主题', true)],
      drafts: [
        draft({ draft_id: 'draft-1', uid: 'A', subject: '回复 A', body_preview: '确认时间。' }),
        draft({ draft_id: 'draft-2', uid: 'B', subject: '回复 B', body_preview: '补充材料。' }),
      ],
    });
    const user = userEvent.setup();
    render(<App />);

    await screen.findByRole('tab', { name: /草稿/ });
    await user.click(screen.getByRole('tab', { name: /草稿/ }));

    expect(screen.getByText('待发送草稿集中处理')).toBeInTheDocument();
    expect(screen.getByText('2 封待发送')).toBeInTheDocument();
    expect(screen.queryByLabelText('草稿集中列表')).not.toBeInTheDocument();
    expect(document.querySelector('.draft-review-list')).not.toBeInTheDocument();

    const trigger = screen.getByRole('button', { name: /^草稿：/ });
    expect(trigger).toHaveTextContent('回复 A');
    await user.click(trigger);
    const listbox = await screen.findByRole('listbox', { name: '草稿' });
    expect(within(listbox).getByRole('option', { name: /回复 B/ })).toBeInTheDocument();
  });

  it('重复点击发送只会创建一个保存/发送流程', async () => {
    const initialDraft = draft();
    const patchRequest = deferred<Response>();
    const fetchMock = installFetch({
      recent: [message('A', 'A 主题', true)],
      drafts: [initialDraft],
      handler: (url, init) => {
        if (url === '/api/drafts/draft-1' && init?.method === 'PATCH') return patchRequest.promise;
        return undefined;
      },
    });

    render(<App />);
    await screen.findByRole('tab', { name: /草稿/ });
    fireEvent.click(screen.getByRole('tab', { name: /草稿/ }));
    const sendButton = await screen.findByRole('button', { name: '保存并发送' });
    fireEvent.click(sendButton);
    fireEvent.click(sendButton);

    await waitFor(() => {
      const patchCalls = fetchMock.mock.calls.filter(([url, init]) => String(url) === '/api/drafts/draft-1' && init?.method === 'PATCH');
      expect(patchCalls).toHaveLength(1);
      expect(screen.getByRole('button', { name: /^草稿：/ })).toBeDisabled();
      expect(screen.getByLabelText('主题')).toHaveAttribute('readonly');
    });
    patchRequest.resolve(jsonResponse(initialDraft));
  });

  it('详情请求等待期间产生的新草稿修改不会被自动绑定覆盖', async () => {
    const detailB = deferred<Response>();
    const draftA = draft();
    const draftB = draft({ draft_id: 'draft-2', uid: 'B', subject: 'B 草稿', body: 'B 正文' });
    installFetch({
      drafts: [draftA, draftB],
      handler: (url) => {
        if (url === '/api/messages/B') return detailB.promise;
        return undefined;
      },
    });
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole('tab', { name: /草稿/ }));
    const subject = await screen.findByLabelText('主题');
    await user.click(screen.getByText('B 主题'));
    await user.type(subject, '（等待期间修改）');
    detailB.resolve(jsonResponse(message('B', 'B 主题', true)));

    await screen.findByRole('heading', { name: 'B 主题' });
    expect(screen.getByLabelText('主题')).toHaveValue('旧主题（等待期间修改）');
    expect(screen.getByRole('button', { name: /^草稿：/ })).toHaveTextContent('旧主题');
  });

  it('草稿下拉菜单可以打开并切换草稿', async () => {
    const draftA = draft();
    const draftB = draft({ draft_id: 'draft-2', uid: 'B', subject: 'B 草稿', body: 'B 正文' });
    installFetch({ drafts: [draftA, draftB] });
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole('tab', { name: /草稿/ }));
    const trigger = await screen.findByRole('button', { name: /^草稿：/ });
    expect(trigger).toHaveTextContent('旧主题');
    await user.click(trigger);
    const listbox = await screen.findByRole('listbox', { name: '草稿' });
    expect(within(listbox).getByRole('option', { name: /B 草稿/ })).toBeInTheDocument();
    await user.click(within(listbox).getByRole('option', { name: /B 草稿/ }));
    expect(screen.getByRole('button', { name: /^草稿：/ })).toHaveTextContent('B 草稿');
    expect(screen.queryByRole('listbox', { name: '草稿' })).not.toBeInTheDocument();
  });

  it('搜索组合筛选并可从历史队列恢复为待处理', async () => {
    const doneResult: SearchMailItem = {
      uid: 'DONE-1',
      sender: 'done@example.com',
      subject: '已处理事项',
      date: '2026-07-10',
      is_seen: true,
      classification: 'respond',
      suggested_action: 'draft_reply',
      queue_status: 'done',
      updated_at: '2026-07-10',
    };
    const fetchMock = installFetch({
      handler: (url, init) => {
        if (url.startsWith('/api/search/messages') && url.includes('queue_status=done')) return jsonResponse([doneResult]);
        if (url === '/api/triage/DONE-1/status' && init?.method === 'POST') return jsonResponse({ ok: true, detail: 'updated' });
        return undefined;
      },
    });
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole('tab', { name: '搜索' }));
    await user.type(screen.getByLabelText('搜索发件人或主题'), '项目 周报');
    await chooseDropdownOption(user, '已读状态', '未读');
    await chooseDropdownOption(user, 'AI 分类', '需回复');
    await chooseDropdownOption(user, '队列状态', '已处理');
    await user.click(screen.getByRole('button', { name: '搜索' }));

    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(([url]) => {
          const value = String(url);
          return value.startsWith('/api/search/messages?') && value.includes('keyword=%E9%A1%B9%E7%9B%AE+%E5%91%A8%E6%8A%A5') && value.includes('is_seen=false') && value.includes('classification=respond') && value.includes('queue_status=done');
        }),
      ).toBe(true);
    });

    await user.click(screen.getByRole('tab', { name: 'AI 待办' }));
    await user.click(screen.getByRole('tab', { name: '已处理' }));
    await screen.findByText('已处理事项');
    await user.click(screen.getByRole('button', { name: '恢复待处理' }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([url, init]) => String(url) === '/api/triage/DONE-1/status' && init?.method === 'POST');
      expect(call).toBeTruthy();
      expect(JSON.parse(String(call?.[1]?.body))).toEqual({ status: 'pending' });
      const appliedSearchCalls = fetchMock.mock.calls.filter(([url]) => {
        const value = String(url);
        return value.includes('keyword=%E9%A1%B9%E7%9B%AE+%E5%91%A8%E6%8A%A5') && value.includes('is_seen=false') && value.includes('classification=respond') && value.includes('queue_status=done');
      });
      expect(appliedSearchCalls.length).toBeGreaterThanOrEqual(2);
    });
  });

  it('AI 队列保留真实已读状态，未知状态不伪装成未读', async () => {
    const queueSearch: SearchMailItem = {
      uid: 'QUEUE-1',
      sender: 'queue@example.com',
      subject: '队列已读邮件',
      date: '2026-07-10',
      is_seen: true,
      classification: 'notify',
      suggested_action: 'read_full',
      queue_status: 'pending',
      updated_at: '2026-07-10',
    };
    const unknownSearch: SearchMailItem = {
      ...queueSearch,
      uid: 'QUEUE-2',
      subject: '队列状态未知邮件',
      is_seen: null,
    };
    installFetch({
      handler: (url) => {
        if (url.startsWith('/api/triage/queue')) {
          return jsonResponse([
            { ...queueSearch, reason: '通知', action_reason: '查看', suggested_action: 'read_full' },
            { ...unknownSearch, reason: '通知', action_reason: '查看', suggested_action: 'read_full' },
          ]);
        }
        if (url.startsWith('/api/search/messages') && url.includes('queue_status=pending')) return jsonResponse([queueSearch, unknownSearch]);
        return undefined;
      },
    });
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole('tab', { name: 'AI 待办' }));
    const card = (await screen.findByText('队列已读邮件')).closest('article');
    expect(card).not.toBeNull();
    expect(within(card as HTMLElement).getByText('已读')).toBeInTheDocument();
    expect(within(card as HTMLElement).queryByText('未读')).not.toBeInTheDocument();
    const unknownCard = screen.getByText('队列状态未知邮件').closest('article');
    expect(unknownCard).not.toBeNull();
    expect(within(unknownCard as HTMLElement).queryByText('未读')).not.toBeInTheDocument();
    expect(within(unknownCard as HTMLElement).queryByText('已读')).not.toBeInTheDocument();
  });

  it('秘书巡检确认固定契约，重复点击只发送一个请求', async () => {
    const inspectionRequest = deferred<Response>();
    const fetchMock = installFetch({
      handler: (url, init) => {
        if (url === '/api/secretary/inspection' && init?.method === 'POST') return inspectionRequest.promise;
        return undefined;
      },
    });
    render(<App />);

    const startButton = await screen.findByRole('button', { name: '开始巡检' });
    fireEvent.click(startButton);
    fireEvent.click(startButton);

    const confirm = await screen.findByRole('dialog', { name: '确认开始秘书巡检' });
    expect(within(confirm).getByText('最新 20 封邮件')).toBeInTheDocument();
    expect(within(confirm).getByText('仅未读且未分类')).toBeInTheDocument();
    expect(within(confirm).getByText('只生成计划，不自动操作')).toBeInTheDocument();
    await userEvent.setup().click(within(confirm).getByRole('button', { name: '开始巡检' }));

    await waitFor(() => {
      const calls = fetchMock.mock.calls.filter(([url, init]) => String(url) === '/api/secretary/inspection' && init?.method === 'POST');
      expect(calls).toHaveLength(1);
      expect(JSON.parse(String(calls[0][1]?.body))).toEqual({ confirmed: true, limit: 20 });
    });

    inspectionRequest.resolve(jsonResponse(inspectionReport()));
    expect(await screen.findByRole('dialog', { name: '秘书巡检报告' })).toBeInTheDocument();
  });

  it('巡检报告展示统计、四个计划分组和部分失败明细', async () => {
    installFetch({
      handler: (url, init) =>
        url === '/api/secretary/inspection' && init?.method === 'POST' ? jsonResponse(inspectionReport()) : undefined,
    });
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole('button', { name: '开始巡检' }));
    const confirm = await screen.findByRole('dialog', { name: '确认开始秘书巡检' });
    await user.click(within(confirm).getByRole('button', { name: '开始巡检' }));

    const report = await screen.findByRole('dialog', { name: '秘书巡检报告' });
    expect(within(within(report).getByText('扫描邮件').closest('.inspection-stat') as HTMLElement).getByText('20')).toBeInTheDocument();
    expect(within(within(report).getByText('当前待跟进').closest('.inspection-stat') as HTMLElement).getByText('3')).toBeInTheDocument();
    expect(within(report).getByRole('heading', { name: '需要回复' })).toBeInTheDocument();
    expect(within(report).getByRole('heading', { name: '需要查看' })).toBeInTheDocument();
    expect(within(report).getByRole('heading', { name: '状态处理建议' })).toBeInTheDocument();
    expect(within(report).getByRole('heading', { name: '无需行动' })).toBeInTheDocument();
    expect(within(report).getByText('需要回复客户')).toBeInTheDocument();
    expect(within(report).getByText('DeepSeek 请求超时')).toBeInTheDocument();
    expect(within(report).getByText('有 1 封邮件处理失败，其余巡检结果已完整保留。')).toBeInTheDocument();
    const closeButton = within(report).getByRole('button', { name: '关闭巡检报告' });
    await waitFor(() => expect(closeButton).toHaveFocus());
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog', { name: '秘书巡检报告' })).not.toBeInTheDocument();
  });

  it('重新巡检失败时保留当前报告并在抽屉内明确提示旧结果', async () => {
    let inspectionCalls = 0;
    installFetch({
      handler: (url, init) => {
        if (url !== '/api/secretary/inspection' || init?.method !== 'POST') return undefined;
        inspectionCalls += 1;
        return inspectionCalls === 1
          ? jsonResponse(inspectionReport())
          : jsonResponse({ detail: 'DeepSeek 暂时不可用' }, 502);
      },
    });
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole('button', { name: '开始巡检' }));
    let confirm = await screen.findByRole('dialog', { name: '确认开始秘书巡检' });
    await user.click(within(confirm).getByRole('button', { name: '开始巡检' }));
    let report = await screen.findByRole('dialog', { name: '秘书巡检报告' });
    const rerun = within(report).getByRole('button', { name: '重新巡检' });
    await waitFor(() => expect(rerun).toBeEnabled());
    await user.click(rerun);

    confirm = await screen.findByRole('dialog', { name: '确认开始秘书巡检' });
    expect(screen.getByRole('dialog', { name: '秘书巡检报告' })).toBeInTheDocument();
    await user.click(within(confirm).getByRole('button', { name: '开始巡检' }));

    report = await screen.findByRole('dialog', { name: '秘书巡检报告' });
    expect(within(report).getByRole('alert')).toHaveTextContent('重新巡检失败，以下仍是上次报告：DeepSeek 暂时不可用');
    expect(within(report).getByText('需要回复客户')).toBeInTheDocument();
    expect(inspectionCalls).toBe(2);
  });

  it('点击巡检计划会关闭报告、读取邮件并自动标记已读', async () => {
    const target = message('PLAN-1', '需要回复客户', false);
    const fetchMock = installFetch({
      recent: [message('A', 'A 主题', true)],
      handler: (url, init) => {
        if (url === '/api/secretary/inspection' && init?.method === 'POST') return jsonResponse(inspectionReport());
        if (url === '/api/messages/PLAN-1') return jsonResponse(target);
        return undefined;
      },
    });
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole('button', { name: '开始巡检' }));
    const confirm = await screen.findByRole('dialog', { name: '确认开始秘书巡检' });
    await user.click(within(confirm).getByRole('button', { name: '开始巡检' }));
    const report = await screen.findByRole('dialog', { name: '秘书巡检报告' });
    await user.click(within(report).getByRole('button', { name: /需要回复客户/ }));

    expect(screen.queryByRole('dialog', { name: '秘书巡检报告' })).not.toBeInTheDocument();
    expect(await screen.findByRole('heading', { name: '需要回复客户' })).toBeInTheDocument();
    await waitFor(() => {
      const markSeenCall = fetchMock.mock.calls.find(([url]) => String(url) === '/api/messages/PLAN-1/mark-seen');
      expect(markSeenCall?.[1]?.method).toBe('POST');
      expect(JSON.parse(String(markSeenCall?.[1]?.body))).toEqual({ confirmed: true });
    });
    const readingPanel = screen.getByRole('heading', { name: '需要回复客户' }).closest('.reading-panel');
    expect(readingPanel).not.toBeNull();
    expect(within(readingPanel as HTMLElement).getByText('已读')).toBeInTheDocument();
    expect(document.querySelector('.app-shell')).toHaveClass('mobile-stage-reading');
  });

  it('配置体检显示检查中/异常真实状态并保留移动端巡检入口', async () => {
    const healthRequest = deferred<Response>();
    installFetch({
      handler: (url) => (url === '/api/health/local' ? healthRequest.promise : undefined),
    });
    render(<App />);

    expect(screen.getByRole('button', { name: '打开配置体检，当前状态：检查中' })).toHaveClass('is-loading');
    expect(screen.getByRole('button', { name: '开始巡检' })).toBeInTheDocument();
    healthRequest.resolve(jsonResponse([{ name: 'local', ok: false, detail: '未配置' }]));

    await waitFor(() => {
      expect(screen.getByRole('button', { name: '打开配置体检，当前状态：异常' })).toHaveClass('is-warning');
    });
  });
});
