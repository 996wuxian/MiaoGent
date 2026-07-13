import { useCallback, useMemo } from 'react';
import { useDialogFocus } from '../hooks/useDialogFocus';
import { isSensitiveMail } from '../mailPrivacy';
import type { InspectionGroupKey, InspectionPlanItem, SecretaryInspectionReport } from '../types';
import { AppIcon, Badge, IconButton } from './ui';

const groupDefinitions: Array<{ key: InspectionGroupKey; title: string; detail: string }> = [
  { key: 'reply', title: '需要回复', detail: '优先准备回复或确认对方诉求' },
  { key: 'review', title: '需要查看', detail: '需要人工阅读后决定下一步' },
  { key: 'status', title: '状态处理建议', detail: '同步进度、提醒或更新本地状态' },
  { key: 'no_action', title: '无需行动', detail: '当前没有建议执行的动作' },
];

const classificationLabels: Record<string, string> = {
  ignore: '忽略',
  notify: '通知',
  respond: '需回复',
};

const actionLabels: Record<string, string> = {
  read_full: '查看全文',
  translate: '翻译',
  draft_reply: '生成草稿',
  mark_seen: '标为已读',
  move_to_trash: '移到垃圾箱',
  no_action: '无需处理',
};

const queueLabels: Record<string, string> = {
  pending: '待处理',
  later: '稍后',
  done: '已处理',
  skipped: '已跳过',
};

export function InspectionReport({
  open,
  focusEnabled,
  report,
  error,
  pending,
  onClose,
  onRerun,
  onSelect,
}: {
  open: boolean;
  focusEnabled: boolean;
  report: SecretaryInspectionReport | null;
  error: string;
  pending: boolean;
  onClose: () => void;
  onRerun: () => void;
  onSelect: (item: InspectionPlanItem) => void;
}) {
  const close = useCallback(() => onClose(), [onClose]);
  const ref = useDialogFocus(open && focusEnabled, close);
  const groups = useMemo(
    () => new Map((report?.groups ?? []).map((group) => [group.key, group])),
    [report],
  );
  if (!open || !report) return null;

  const stats = [
    ['扫描邮件', report.scanned_count],
    ['完成分析', report.processed_count],
    ['跳过已读', report.skipped_seen],
    ['跳过已分类', report.skipped_triaged],
    ['处理失败', report.failed_count],
    ['当前待跟进', report.current_actionable_count],
  ] as const;

  return (
    <div className="drawer-backdrop" role="presentation" onMouseDown={onClose}>
      <aside
        ref={ref}
        className="inspection-drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="inspection-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="drawer-header">
          <div>
            <span className="eyebrow">SECRETARY INSPECTION</span>
            <h2 id="inspection-title">秘书巡检报告</h2>
            <p>{report.inspected_at || '刚刚完成'} · 仅生成处理计划，不会自动执行邮件操作。</p>
          </div>
          <IconButton icon="close-circle-outline" label="关闭巡检报告" onClick={onClose} />
        </div>

        <div className="drawer-body inspection-body scroll-area">
          {error && (
            <div className="inspection-run-error" role="alert">
              <AppIcon icon="danger-triangle-outline" />
              <span>{error}</span>
            </div>
          )}
          <section className="inspection-section" aria-labelledby="inspection-summary-title">
            <div className="section-heading">
              <div>
                <h3 id="inspection-summary-title">本轮概览</h3>
                <p>范围为最新 20 封邮件，模型只处理未读且尚未分类的邮件。</p>
              </div>
              <Badge tone={report.failed_count > 0 ? 'warning' : 'success'}>
                {report.failed_count > 0 ? '部分完成' : '巡检完成'}
              </Badge>
            </div>
            <div className="inspection-stat-grid">
              {stats.map(([label, value]) => (
                <div className="inspection-stat" key={label}>
                  <strong>{value}</strong>
                  <span>{label}</span>
                </div>
              ))}
            </div>
            {report.current_actionable_count === 0 && (
              <div className="inspection-empty-summary">
                <AppIcon icon="check-circle-outline" />
                <div>
                  <strong>当前没有需要跟进的邮件</strong>
                  <p>仍可查看“无需行动”分组与本轮失败记录。</p>
                </div>
              </div>
            )}
            {report.failed_count > 0 && (
              <div className="inspection-partial-note" role="status">
                <AppIcon icon="danger-triangle-outline" />
                <span>有 {report.failed_count} 封邮件处理失败，其余巡检结果已完整保留。</span>
              </div>
            )}
          </section>

          <section className="inspection-section" aria-labelledby="inspection-plan-title">
            <div className="section-heading">
              <div>
                <h3 id="inspection-plan-title">处理计划</h3>
                <p>点击任一邮件可回到工作台查看全文，并沿用自动标记已读流程。</p>
              </div>
            </div>
            <div className="inspection-group-list">
              {groupDefinitions.map((definition) => {
                const group = groups.get(definition.key);
                const items = group?.items ?? [];
                return (
                  <section className={`inspection-group inspection-group-${definition.key}`} key={definition.key}>
                    <div className="inspection-group-head">
                      <div>
                        <h4>{group?.title || definition.title}</h4>
                        <p>{definition.detail}</p>
                      </div>
                      <Badge tone={definition.key === 'no_action' ? 'neutral' : 'info'}>{items.length}</Badge>
                    </div>
                    {items.length > 0 ? (
                      <div className="inspection-item-list">
                        {items.map((item) => (
                          <button className="inspection-plan-item" key={`${definition.key}-${item.uid}`} onClick={() => onSelect(item)}>
                            <span className="inspection-item-main">
                              <strong>{item.subject || '(无主题)'}</strong>
                              <span>{item.sender || '未知发件人'} · UID {item.uid}</span>
                            </span>
                            <span className="inspection-item-badges">
                              {item.classification && <Badge>{classificationLabels[item.classification] ?? item.classification}</Badge>}
                              {item.suggested_action && <Badge tone="info">{actionLabels[item.suggested_action] ?? item.suggested_action}</Badge>}
                              {item.queue_status && <Badge>{queueLabels[item.queue_status] ?? item.queue_status}</Badge>}
                              {isSensitiveMail({ summary_zh: item.reason, priority_reason: item.action_reason }) && <Badge tone="danger">敏感</Badge>}
                            </span>
                            {(item.action_reason || item.reason) && (
                              <span className="inspection-item-reason">{item.action_reason || item.reason}</span>
                            )}
                            {item.action_reason && item.reason && item.action_reason !== item.reason && (
                              <span className="inspection-item-context">分类依据：{item.reason}</span>
                            )}
                            {item.updated_at && <time>{item.updated_at}</time>}
                          </button>
                        ))}
                      </div>
                    ) : (
                      <div className="inspection-group-empty">暂无此类计划</div>
                    )}
                  </section>
                );
              })}
            </div>
          </section>

          {(report.failed_count > 0 || report.failures.length > 0) && (
            <section className="inspection-section inspection-failures" aria-labelledby="inspection-failures-title">
              <div className="section-heading">
                <div>
                  <h3 id="inspection-failures-title">失败明细</h3>
                  <p>失败不会清空其他邮件已经生成的计划。</p>
                </div>
                <Badge tone="danger">{report.failed_count}</Badge>
              </div>
              <div className="inspection-failure-list">
                {report.failures.map((failure) => (
                  <div className="inspection-failure-item" key={`${failure.uid}-${failure.error}`}>
                    <AppIcon icon="danger-triangle-outline" />
                    <div>
                      <strong>{failure.subject || '(无主题)'}</strong>
                      <span>UID {failure.uid}</span>
                      {isSensitiveMail(failure) && <Badge tone="danger">敏感</Badge>}
                      <p>{failure.error}</p>
                    </div>
                  </div>
                ))}
                {report.failures.length === 0 && <div className="inspection-group-empty">后端未返回失败明细</div>}
              </div>
            </section>
          )}
        </div>

        <div className="drawer-footer inspection-footer">
          <button className="btn btn-secondary" onClick={onClose}>关闭</button>
          <button className="btn btn-primary" onClick={onRerun} disabled={pending}>
            <AppIcon icon="refresh-outline" />
            <span>{pending ? '巡检中…' : '重新巡检'}</span>
          </button>
        </div>
      </aside>
    </div>
  );
}
