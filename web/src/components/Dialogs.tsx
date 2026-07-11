import type { FormEvent, ReactNode } from 'react';
import { useCallback, useEffect, useState } from 'react';
import { useDialogFocus } from '../hooks/useDialogFocus';
import type { HealthItem } from '../types';
import { AppIcon, Badge, IconButton, InlineError } from './ui';

export type ConfirmTone = 'default' | 'warning' | 'danger';

export type ConfirmState = {
  title: string;
  message: string;
  confirmLabel?: string;
  tone?: ConfirmTone;
  details?: ReactNode;
};

export function ConfirmDialog({ state, onCancel, onConfirm }: { state: ConfirmState | null; onCancel: () => void; onConfirm: () => void }) {
  const close = useCallback(() => onCancel(), [onCancel]);
  const ref = useDialogFocus(Boolean(state), close);
  if (!state) return null;
  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={onCancel}>
      <div
        ref={ref}
        className={`confirm-modal confirm-${state.tone ?? 'default'}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby="confirm-title"
        aria-describedby="confirm-description"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="modal-header">
          <div>
            <h2 id="confirm-title">{state.title}</h2>
            <p id="confirm-description">{state.message}</p>
          </div>
          <IconButton icon="close-circle-outline" label="关闭" onClick={onCancel} />
        </div>
        {state.details && <div className="modal-body">{state.details}</div>}
        <div className="modal-footer">
          <button className="btn btn-secondary" onClick={onCancel}>
            取消
          </button>
          <button data-autofocus className={`btn ${state.tone === 'danger' ? 'btn-danger-solid' : 'btn-primary'}`} onClick={onConfirm}>
            {state.confirmLabel ?? '确认'}
          </button>
        </div>
      </div>
    </div>
  );
}

export function DevtoolsPasswordDialog({
  open,
  error,
  pending,
  onCancel,
  onUnlock,
}: {
  open: boolean;
  error: string;
  pending: boolean;
  onCancel: () => void;
  onUnlock: (password: string) => void;
}) {
  const [password, setPassword] = useState('');
  const close = useCallback(() => onCancel(), [onCancel]);
  const ref = useDialogFocus(open, close);

  useEffect(() => {
    if (open) setPassword('');
  }, [open]);

  if (!open) return null;

  function submit(event: FormEvent) {
    event.preventDefault();
    onUnlock(password);
  }

  return (
    <div className="modal-backdrop" role="presentation">
      <div
        ref={ref}
        className="confirm-modal devtools-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="devtools-title"
        aria-describedby="devtools-description"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <form onSubmit={submit}>
          <div className="modal-header">
            <div>
              <h2 id="devtools-title">打开开发者控制台</h2>
              <p id="devtools-description">输入本机调试密码后打开当前窗口的 DevTools。</p>
            </div>
            <IconButton icon="close-circle-outline" label="关闭" onClick={onCancel} />
          </div>
          <div className="modal-body">
            <label className="devtools-password-field">
              <span>密码</span>
              <input
                data-autofocus
                type="password"
                value={password}
                autoComplete="off"
                onChange={(event) => setPassword(event.target.value)}
              />
            </label>
            {error && <InlineError message={error} />}
          </div>
          <div className="modal-footer">
            <button className="btn btn-secondary" type="button" onClick={onCancel}>
              取消
            </button>
            <button className="btn btn-primary" type="submit" disabled={pending}>
              {pending ? '验证中…' : '打开'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

export function ConfirmDetail({ rows }: { rows: Array<[string, string]> }) {
  return (
    <div className="confirm-detail">
      {rows.map(([label, value]) => (
        <div key={label}>
          <span>{label}</span>
          <strong title={value}>{value}</strong>
        </div>
      ))}
    </div>
  );
}

export function ConfirmDraft({ to, subject, body }: { to: string; subject: string; body: string }) {
  return (
    <div className="confirm-draft">
      <ConfirmDetail rows={[['收件人', to], ['主题', subject]]} />
      <pre>{body}</pre>
    </div>
  );
}

type ExternalTarget = 'imap' | 'smtp' | 'deepseek';

const targetLabels: Record<ExternalTarget, string> = {
  imap: 'IMAP 登录',
  smtp: 'SMTP 登录',
  deepseek: 'DeepSeek 连通性',
};

export function HealthDrawer({
  open,
  localItems,
  localLoading,
  localError,
  externalItems,
  isChecking,
  onClose,
  onRetryLocal,
  onCheck,
}: {
  open: boolean;
  localItems: HealthItem[];
  localLoading: boolean;
  localError: string;
  externalItems: Partial<Record<ExternalTarget, HealthItem>>;
  isChecking: (target: ExternalTarget) => boolean;
  onClose: () => void;
  onRetryLocal: () => void;
  onCheck: (target: ExternalTarget) => void;
}) {
  const close = useCallback(() => onClose(), [onClose]);
  const ref = useDialogFocus(open, close);
  if (!open) return null;
  return (
    <div className="drawer-backdrop" role="presentation" onMouseDown={onClose}>
      <aside
        ref={ref}
        className="health-drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="health-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="drawer-header">
          <div>
            <span className="eyebrow">CONFIG DIAGNOSTICS</span>
            <h2 id="health-title">配置体检</h2>
            <p>本地检查不会联网；外部登录与模型检查会在确认后执行。</p>
          </div>
          <IconButton icon="close-circle-outline" label="关闭配置体检" onClick={onClose} />
        </div>
        <div className="drawer-body scroll-area">
          <section className="health-section">
            <div className="section-heading">
              <h3>本地配置</h3>
              <Badge tone={localItems.length > 0 && localItems.every((item) => item.ok) ? 'success' : 'warning'}>
                {localLoading ? '检查中' : `${localItems.filter((item) => item.ok).length}/${localItems.length || '-'}`}
              </Badge>
            </div>
            {localError && <InlineError message={localError} onRetry={onRetryLocal} />}
            <div className="health-list">
              {localItems.map((item) => (
                <div className="health-item" key={item.name}>
                  <AppIcon icon={item.ok ? 'check-circle-outline' : 'danger-triangle-outline'} />
                  <div>
                    <strong>{item.name}</strong>
                    <p>{item.detail}</p>
                  </div>
                  <Badge tone={item.ok ? 'success' : 'danger'}>{item.ok ? '正常' : '异常'}</Badge>
                </div>
              ))}
            </div>
          </section>
          <section className="health-section">
            <div className="section-heading">
              <div>
                <h3>外部连通性</h3>
                <p>每项都需要单独确认，不会自动执行。</p>
              </div>
            </div>
            <div className="external-health-grid">
              {(Object.keys(targetLabels) as ExternalTarget[]).map((target) => {
                const item = externalItems[target];
                const pending = isChecking(target);
                return (
                  <div className="external-health-card" key={target}>
                    <div>
                      <strong>{targetLabels[target]}</strong>
                      <p>{item?.detail ?? '尚未执行外部检查'}</p>
                    </div>
                    <div className="external-health-actions">
                      {item && <Badge tone={item.ok ? 'success' : 'danger'}>{item.ok ? '通过' : '失败'}</Badge>}
                      <button className="btn btn-secondary" disabled={pending} onClick={() => onCheck(target)}>
                        {pending ? '检查中…' : item ? '重新检查' : '开始检查'}
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          </section>
        </div>
      </aside>
    </div>
  );
}
