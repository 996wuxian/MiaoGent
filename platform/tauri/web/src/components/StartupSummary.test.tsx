import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { StartupSummary } from '../types';
import { StartupSummaryDrawer } from './StartupSummary';

const summary: StartupSummary = {
  id: 123,
  trigger: 'startup',
  generated_at: '2026-07-10T08:00:00+08:00',
  new_count: 1,
  processed_count: 1,
  important_count: 0,
  urgent_count: 0,
  reply_count: 0,
  draft_ready_count: 0,
  general_count: 0,
  failed_count: 1,
  has_more: false,
  items: [],
  failures: [{ uid: 'uid:9', stage: 'analysis', error: 'RuntimeError: 本封邮件分析失败，请稍后重试' }],
};

describe('StartupSummaryDrawer', () => {
  it('shows failed items as manual review work and lets the user locate the mail', async () => {
    const onSelect = vi.fn();
    const user = userEvent.setup();
    render(
      <StartupSummaryDrawer
        open
        summary={summary}
        loading={false}
        error=""
        onClose={() => undefined}
        onRetry={() => undefined}
        onSelect={onSelect}
      />,
    );

    expect(screen.getByRole('heading', { name: '需要人工查看' })).toBeInTheDocument();
    expect(screen.getByText(/uid:9 · analysis/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '查看邮件' }));
    expect(onSelect).toHaveBeenCalledWith('uid:9');
  });

  it('does not present low-confidence or sent items as trusted pending work', () => {
    render(
      <StartupSummaryDrawer
        open
        summary={{
          ...summary,
          failed_count: 0,
          failures: [],
          items: [
            {
              uid: 'uid:10',
              sender: 'low@example.com',
              subject: '低置信度邮件',
              importance: 'general',
              needs_reply: false,
              summary_zh: '判断不确定',
              priority_reason: '置信度不足',
              confidence: 0.4,
              analysis_status: 'analyzed',
              reply_status: 'not_needed',
              notification_status: 'attention_emitted',
              draft_id: null,
            },
            {
              uid: 'uid:11',
              sender: 'sent@example.com',
              subject: '已经回复的邮件',
              importance: 'important',
              needs_reply: true,
              summary_zh: '历史邮件已处理',
              priority_reason: '历史重要邮件',
              confidence: 0.9,
              analysis_status: 'analyzed',
              reply_status: 'sent',
              notification_status: 'notified',
              draft_id: 'draft-11',
            },
          ],
        }}
        loading={false}
        error=""
        onClose={() => undefined}
        onRetry={() => undefined}
        onSelect={() => undefined}
      />,
    );

    const lowConfidence = screen.getByRole('button', { name: /低置信度邮件/ });
    expect(within(lowConfidence).getByText('待人工查看')).toBeInTheDocument();
    expect(within(lowConfidence).queryByText('一般')).not.toBeInTheDocument();

    const sent = screen.getByRole('button', { name: /已经回复的邮件/ });
    expect(within(sent).getByText('已回复')).toBeInTheDocument();
    expect(within(sent).queryByText('待回复')).not.toBeInTheDocument();
    expect(within(sent).queryByText('草稿就绪')).not.toBeInTheDocument();
  });
});
