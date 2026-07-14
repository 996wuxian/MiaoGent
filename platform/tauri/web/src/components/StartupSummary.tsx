import { AppIcon, Badge } from './ui';
import { getMailPrivacyLevel } from '../mailPrivacy';
import type { MailAiAudit } from '../types';

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
  ai_audit?: MailAiAudit;
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
      {item.ai_audit && <MailAiAuditPanel audit={item.ai_audit} />}
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

function MailAiAuditPanel({ audit }: { audit: MailAiAudit }) {
  const risky = audit.privacy_level !== 'normal';
  const rows = [
    { key: 'title', label: '标题分类', section: audit.title_classification },
    { key: 'summary', label: '正文摘要', section: audit.body_summary },
    { key: 'draft', label: '回复草稿', section: audit.reply_draft },
    { key: 'policy', label: '隐私策略', section: audit.body_policy },
  ];
  return (
    <section className={`ai-audit-panel ${risky ? 'is-risky' : 'is-normal'}`} aria-label="隐私与 AI 使用情况">
      <div className="ai-audit-head">
        <span>隐私与 AI 使用情况</span>
        <Badge tone={risky ? 'danger' : 'neutral'}>{audit.privacy_label}</Badge>
      </div>
      {audit.privacy_reason && <p>{audit.privacy_reason}</p>}
      <dl>
        {rows.map((row) => (
          <div key={row.key}>
            <dt>{row.label}</dt>
            <dd>
              <strong>{row.section.label}</strong>
              <span>{row.section.description}</span>
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
