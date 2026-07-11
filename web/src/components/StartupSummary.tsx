import { useCallback } from 'react';
import { useDialogFocus } from '../hooks/useDialogFocus';
import type { StartupSummary, StartupSummaryItem } from '../types';
import { AppIcon, Badge, IconButton } from './ui';

const importanceLabel: Record<string, string> = {
  general: '一般',
  important: '重要',
  urgent: '紧急',
};

function itemTone(item: StartupSummaryItem) {
  if (item.importance === 'urgent') return 'danger' as const;
  if (item.importance === 'important') return 'warning' as const;
  return 'neutral' as const;
}

export function StartupSummaryDrawer({
  open,
  summary,
  loading,
  error,
  onClose,
  onRetry,
  onSelect,
}: {
  open: boolean;
  summary: StartupSummary | null;
  loading: boolean;
  error: string;
  onClose: () => void;
  onRetry: () => void;
  onSelect: (uid: string) => void;
}) {
  const close = useCallback(() => onClose(), [onClose]);
  const ref = useDialogFocus(open, close);
  if (!open) return null;

  const stats = summary
    ? [
        ['新增', summary.new_count],
        ['待回复', summary.reply_count],
        ['草稿就绪', summary.draft_ready_count],
        ['重要', summary.important_count],
        ['紧急', summary.urgent_count],
        ['失败', summary.failed_count],
      ]
    : [];

  return (
    <div className="drawer-backdrop" role="presentation" onMouseDown={onClose}>
      <aside
        ref={ref}
        className="inspection-drawer startup-summary-drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="startup-summary-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="drawer-header">
          <div>
            <span className="eyebrow">DESKTOP STARTUP SUMMARY</span>
            <h2 id="startup-summary-title">新邮件已整理</h2>
            <p>{summary?.generated_at || summary?.created_at || '正在读取最近一次汇总'}</p>
          </div>
          <IconButton icon="close-circle-outline" label="关闭启动汇总" onClick={onClose} />
        </div>

        <div className="drawer-body inspection-body scroll-area">
          {loading && <div className="inspection-group-empty">正在加载汇总…</div>}
          {error && (
            <div className="inspection-run-error" role="alert">
              <AppIcon icon="danger-triangle-outline" />
              <span>{error}</span>
            </div>
          )}
          {summary && (
            <>
              <section className="inspection-section">
                <div className="inspection-stat-grid">
                  {stats.map(([label, value]) => (
                    <div className="inspection-stat" key={label}>
                      <strong>{value}</strong>
                      <span>{label}</span>
                    </div>
                  ))}
                </div>
                {summary.has_more && <p className="inspection-partial-note">还有后续批次，Agent 会继续整理。</p>}
              </section>

              <section className="inspection-section">
                <div className="section-heading">
                  <div><h3>本轮邮件</h3><p>点击邮件进入主工作台，待回复草稿已经提前准备。</p></div>
                </div>
                <div className="inspection-item-list">
                  {summary.items.map((item) => (
                    <button className="inspection-plan-item" key={item.uid} onClick={() => onSelect(item.uid)}>
                      <span className="inspection-item-main">
                        <strong>{item.subject || '(无主题)'}</strong>
                        <span>{item.sender || '未知发件人'}</span>
                      </span>
                      <span className="inspection-item-badges">
                        {item.analysis_status === 'analyzed' && (item.confidence ?? 0) >= 0.55 && item.importance && <Badge tone={itemTone(item)}>{importanceLabel[item.importance] ?? item.importance}</Badge>}
                        {(item.analysis_status !== 'analyzed' || (item.confidence ?? 0) < 0.55) && <Badge tone="warning">待人工查看</Badge>}
                        {item.needs_reply && !['sent', 'not_needed'].includes(item.reply_status) && <Badge tone="info">待回复</Badge>}
                        {item.reply_status === 'sent' && <Badge tone="success">已回复</Badge>}
                        {item.draft_id && item.reply_status === 'draft_ready' && <Badge tone="success">草稿就绪</Badge>}
                      </span>
                      {item.summary_zh && <span className="inspection-item-reason">{item.summary_zh}</span>}
                    </button>
                  ))}
                  {summary.items.length === 0 && <div className="inspection-group-empty">本轮没有新增邮件</div>}
                </div>
              </section>

              {summary.failures.length > 0 && (
                <section className="inspection-section inspection-failures">
                  <div className="section-heading">
                    <div><h3>需要人工查看</h3><p>失败项不会归入“一般”邮件；可按 UID 重新打开检查。</p></div>
                  </div>
                  <div className="inspection-failure-list">
                    {summary.failures.map((failure, index) => (
                      <div className="inspection-failure-item" key={`${failure.uid}-${failure.stage}-${index}`}>
                        <AppIcon icon="danger-triangle-outline" />
                        <div>
                          <strong>{failure.uid || '邮箱同步'} · {failure.stage}</strong>
                          <span>{failure.error}</span>
                          {failure.uid && failure.uid !== 'mailbox' && (
                            <button className="text-button" type="button" onClick={() => onSelect(failure.uid)}>查看邮件</button>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </section>
              )}
            </>
          )}
        </div>

        <div className="drawer-footer inspection-footer">
          <button className="btn btn-secondary" onClick={onClose}>关闭</button>
          <button className="btn btn-primary" onClick={onRetry} disabled={loading}>
            <AppIcon icon="refresh-outline" />
            <span>{loading ? '同步中…' : '立即重新整理'}</span>
          </button>
        </div>
      </aside>
    </div>
  );
}

export function InsightSummary({ item }: { item: {
  importance: string;
  needs_reply: boolean;
  summary_zh: string;
  action_items: string[];
  priority_reason: string;
  confidence: number;
  analysis_status: string;
  analysis_error: string | null;
  reply_status: string;
} }) {
  const requiresReview = item.analysis_status !== 'analyzed' || item.confidence < 0.55;
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
        {item.needs_reply && !['sent', 'not_needed'].includes(item.reply_status) && <Badge tone="info">需要回复</Badge>}
        {item.reply_status === 'sent' && <Badge tone="success">已回复</Badge>}
      </div>
      <p>{item.summary_zh || '暂无摘要'}</p>
      {item.analysis_error && <small>分析状态：{item.analysis_error}</small>}
      {item.priority_reason && <small>判断依据：{item.priority_reason} · 置信度 {Math.round(item.confidence * 100)}%</small>}
      {item.action_items.length > 0 && (
        <ul>{item.action_items.map((action) => <li key={action}>{action}</li>)}</ul>
      )}
    </section>
  );
}
