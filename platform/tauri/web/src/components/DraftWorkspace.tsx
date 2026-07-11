import type { Draft, DraftFilter } from '../types';
import { AppIcon, Badge, CustomDropdown, EmptyState, InlineError, LoadingLine, SegmentedTabs } from './ui';

export type DraftEditorState = {
  draftId: string;
  subject: string;
  body: string;
  baselineSubject: string;
  baselineBody: string;
};

function draftStatus(draft: Draft): { label: string; tone: 'info' | 'success' | 'warning' | 'danger' | 'neutral' } {
  if (draft.send_status === 'sending') return { label: '发送中', tone: 'info' };
  if (draft.send_status === 'failed') return { label: '发送失败', tone: 'danger' };
  if (draft.send_status === 'unknown') return { label: '状态待核验', tone: 'warning' };
  if (draft.sent_at || draft.send_status === 'sent') return { label: '已发送', tone: 'success' };
  return { label: '待发送', tone: 'neutral' };
}

export function DraftWorkspace({
  drafts,
  selectedDraft,
  editor,
  dirty,
  filter,
  loading,
  error,
  currentMailId,
  isSaving,
  isSending,
  locked,
  onFilterChange,
  onSelect,
  onEditorChange,
  onSave,
  onSend,
  onRetry,
}: {
  drafts: Draft[];
  selectedDraft: Draft | undefined;
  editor: DraftEditorState | null;
  dirty: boolean;
  filter: DraftFilter;
  loading: boolean;
  error: string;
  currentMailId: string;
  isSaving: boolean;
  isSending: boolean;
  locked: boolean;
  onFilterChange: (filter: DraftFilter) => void;
  onSelect: (draftId: string) => void;
  onEditorChange: (patch: Partial<Pick<DraftEditorState, 'subject' | 'body'>>) => void;
  onSave: () => void;
  onSend: () => void;
  onRetry: () => void;
}) {
  const status = selectedDraft ? draftStatus(selectedDraft) : null;
  const pendingCount = drafts.filter((draft) => !draft.sent_at && draft.send_status !== 'sent').length;
  const failedCount = drafts.filter((draft) => draft.send_status === 'failed' || draft.send_status === 'unknown').length;
  const readOnly = Boolean(
    loading ||
      isSaving ||
      isSending ||
      selectedDraft?.sent_at ||
      selectedDraft?.send_status === 'sent' ||
      selectedDraft?.send_status === 'sending' ||
      selectedDraft?.send_status === 'unknown',
  );
  const matchesCurrent = selectedDraft && normalizeUid(selectedDraft.uid) === normalizeUid(currentMailId);

  return (
    <section className="draft-workspace" aria-label="草稿工作区">
      <div className="draft-center-header">
        <div>
          <span className="eyebrow">DRAFT REVIEW</span>
          <h3>待发送草稿集中处理</h3>
          <p>逐封检查、编辑并确认发送；不会自动批量发送。</p>
        </div>
        <div className="draft-center-stats" aria-label="草稿统计">
          <Badge tone={pendingCount > 0 ? 'warning' : 'success'}>{pendingCount} 封待发送</Badge>
          {failedCount > 0 && <Badge tone="danger">{failedCount} 封需核验</Badge>}
        </div>
      </div>
      <SegmentedTabs
        label="草稿状态"
        value={filter}
        compact
        disabled={locked}
        options={[
          { value: 'pending', label: '待发送' },
          { value: 'sent', label: '已发送' },
          { value: 'all', label: '全部' },
        ]}
        onChange={onFilterChange}
      />
      <LoadingLine active={loading} />
      {error && <InlineError message={error} onRetry={onRetry} />}
      <DraftDropdown
        drafts={drafts}
        selectedDraft={selectedDraft}
        currentMailId={currentMailId}
        disabled={locked || loading || drafts.length === 0}
        onSelect={onSelect}
      />

      {selectedDraft && editor ? (
        <div className="draft-editor">
          <div className="draft-status-row">
            {status && <Badge tone={status.tone}>{status.label}</Badge>}
            {dirty && <Badge tone="warning">未保存</Badge>}
            {matchesCurrent && <Badge tone="info">当前邮件</Badge>}
            {selectedDraft.draft_version && selectedDraft.draft_version > 1 && <Badge>版本 {selectedDraft.draft_version}</Badge>}
          </div>
          <div className="recipient-line">
            <AppIcon icon="user-id-outline" width={17} />
            <span>To: {selectedDraft.to_addr}</span>
          </div>
          <label className="field-label" htmlFor="draft-subject">主题</label>
          <input
            id="draft-subject"
            className="field"
            value={editor.subject}
            readOnly={readOnly}
            onChange={(event) => onEditorChange({ subject: event.target.value })}
          />
          <label className="field-label" htmlFor="draft-body">正文</label>
          <textarea
            id="draft-body"
            className="field draft-body"
            value={editor.body}
            readOnly={readOnly}
            onChange={(event) => onEditorChange({ body: event.target.value })}
          />
          {selectedDraft.send_error && <InlineError message={selectedDraft.send_error} />}
          {!readOnly && (
            <div className="draft-actions">
              <button className="btn btn-secondary" onClick={onSave} disabled={isSaving || isSending || !dirty}>
                <AppIcon icon="diskette-outline" />
                <span>{isSaving ? '保存中…' : dirty ? '保存草稿' : '已保存'}</span>
              </button>
              <button className="btn btn-primary" onClick={onSend} disabled={isSaving || isSending}>
                <AppIcon icon="plain-2-outline" />
                <span>{isSending ? '处理中…' : selectedDraft.send_status === 'failed' ? '保存并重试发送' : '保存并发送'}</span>
              </button>
            </div>
          )}
        </div>
      ) : (
        <EmptyState
          icon="document-add-outline"
          title={loading ? '正在加载草稿' : `暂无${filter === 'pending' ? '待发送' : filter === 'sent' ? '已发送' : ''}草稿`}
          detail={currentMailId ? '为当前邮件生成草稿后会优先显示在这里' : '先选择一封邮件，再生成回复草稿'}
        />
      )}
    </section>
  );
}

function DraftDropdown({
  drafts,
  selectedDraft,
  currentMailId,
  disabled,
  onSelect,
}: {
  drafts: Draft[];
  selectedDraft: Draft | undefined;
  currentMailId: string;
  disabled: boolean;
  onSelect: (draftId: string) => void;
}) {
  return (
    <CustomDropdown
      label="草稿"
      value={selectedDraft?.draft_id ?? ''}
      className="draft-picker-row draft-dropdown"
      disabled={disabled}
      emptyLabel="暂无草稿"
      options={drafts.map((draft) => ({
        value: draft.draft_id,
        label: draft.subject || '(无主题)',
        meta: draftMeta(draft, currentMailId),
      }))}
      onChange={onSelect}
    />
  );
}

function draftMeta(draft: Draft, currentMailId: string) {
  const status = draftStatus(draft).label;
  const current = normalizeUid(draft.uid) === normalizeUid(currentMailId) ? '当前邮件' : `UID ${draft.uid}`;
  const version = draft.draft_version && draft.draft_version > 1 ? ` · v${draft.draft_version}` : '';
  return `${status} · ${current}${version}`;
}

export function normalizeUid(value: string) {
  return value.trim().replace(/^uid:/i, '');
}
