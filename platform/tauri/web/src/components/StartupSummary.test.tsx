import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { InsightSummary } from './StartupSummary';

describe('InsightSummary', () => {
  it('marks low confidence insights as manual review work', () => {
    render(
      <InsightSummary
        item={{
          importance: 'general',
          needs_reply: false,
          summary_zh: '判断不确定',
          action_items: [],
          priority_reason: '置信度不足',
          confidence: 0.4,
          analysis_status: 'analyzed',
          analysis_error: null,
          reply_status: 'not_needed',
        }}
      />,
    );

    expect(screen.getByText('待人工查看')).toBeInTheDocument();
    expect(screen.queryByText('一般')).not.toBeInTheDocument();
  });

  it('shows reply and sent states without reopening startup summary UI', () => {
    render(
      <InsightSummary
        item={{
          importance: 'important',
          needs_reply: true,
          summary_zh: '历史邮件已处理',
          action_items: ['无需再次发送'],
          priority_reason: '历史重要邮件',
          confidence: 0.9,
          analysis_status: 'analyzed',
          analysis_error: null,
          reply_status: 'sent',
        }}
      />,
    );

    expect(screen.getByText('重要')).toBeInTheDocument();
    expect(screen.getByText('已回复')).toBeInTheDocument();
    expect(screen.queryByText('需要回复')).not.toBeInTheDocument();
    expect(screen.getByText('无需再次发送')).toBeInTheDocument();
  });
});
