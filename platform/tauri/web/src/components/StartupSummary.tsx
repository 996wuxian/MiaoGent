import { AppIcon, Badge } from './ui';
import { getMailPrivacyLevel } from '../mailPrivacy';

const importanceLabel: Record<string, string> = {
  general: '一般',
  important: '重要',
  urgent: '紧急',
};

export function InsightSummary({ item, onGenerateSummary, summaryPending }: { item: {
  importance: string;
  needs_reply: boolean;
  summary_zh: string;
  action_items: string[];
  priority_reason: string;
  confidence: number;
  analysis_status: string;
  analysis_error: string | null;
  reply_status: string;
}; onGenerateSummary?: () => void; summaryPending?: boolean }) {
  const requiresReview = !['analyzed', 'title_classified'].includes(item.analysis_status) || item.confidence < 0.55;
  const privacyLevel = getMailPrivacyLevel(item);
  const hasSummary = item.summary_zh.trim().length > 0;
  return (
    <section className={`insight-summary is-${item.importance}`}>
      <div className="section-title">
        <AppIcon icon="magic-stick-3-outline" />
        <span>Agent 摘要</span>
        {requiresReview ? (
          <Badge tone="warning">待人工查看</Badge>
        ) : (
          <Badge tone={item.importance === 'urgent' ? 'danger' : item.importance === 'important' ? 'warning' : 'neutral'}>
            {importanceLabel[item.importance] ?? item.importance}
          </Badge>
        )}
        {privacyLevel !== 'normal' && <Badge tone="danger">{privacyLevel === 'private' ? '隐私' : '敏感'}</Badge>}
        {item.needs_reply && !['sent', 'not_needed'].includes(item.reply_status) && <Badge tone="info">需要回复</Badge>}
        {item.reply_status === 'sent' && <Badge tone="success">已回复</Badge>}
      </div>
      <p>{hasSummary ? item.summary_zh : '尚未生成 Agent 摘要。'}</p>
      {!hasSummary && onGenerateSummary && (
        <button className="btn btn-secondary mini-button" type="button" onClick={onGenerateSummary} disabled={summaryPending}>
          {summaryPending ? '生成中…' : '生成摘要'}
        </button>
      )}
      {item.analysis_error && <small>分析状态：{item.analysis_error}</small>}
      {item.priority_reason && <small>判断依据：{item.priority_reason} · 置信度 {Math.round(item.confidence * 100)}%</small>}
      {item.action_items.length > 0 && (
        <ul>{item.action_items.map((action) => <li key={action}>{action}</li>)}</ul>
      )}
    </section>
  );
}
