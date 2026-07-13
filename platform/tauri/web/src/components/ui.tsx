import altArrowLeftOutline from '@iconify-icons/solar/alt-arrow-left-outline';
import altArrowRightOutline from '@iconify-icons/solar/alt-arrow-right-outline';
import checkCircleOutline from '@iconify-icons/solar/check-circle-outline';
import clipboardRemoveOutline from '@iconify-icons/solar/clipboard-remove-outline';
import closeCircleOutline from '@iconify-icons/solar/close-circle-outline';
import codeSquareOutline from '@iconify-icons/solar/code-square-outline';
import dangerTriangleOutline from '@iconify-icons/solar/danger-triangle-outline';
import disketteOutline from '@iconify-icons/solar/diskette-outline';
import documentAddOutline from '@iconify-icons/solar/document-add-outline';
import galleryOutline from '@iconify-icons/solar/gallery-outline';
import galleryWideOutline from '@iconify-icons/solar/gallery-wide-outline';
import historyOutline from '@iconify-icons/solar/history-outline';
import inboxUnreadOutline from '@iconify-icons/solar/inbox-unread-outline';
import letterBold from '@iconify-icons/solar/letter-bold';
import lightbulbBoltOutline from '@iconify-icons/solar/lightbulb-bolt-outline';
import magicStick3Outline from '@iconify-icons/solar/magic-stick-3-outline';
import mailboxOutline from '@iconify-icons/solar/mailbox-outline';
import moonOutline from '@iconify-icons/solar/moon-outline';
import paperclipOutline from '@iconify-icons/solar/paperclip-outline';
import penNewSquareOutline from '@iconify-icons/solar/pen-new-square-outline';
import plain2Outline from '@iconify-icons/solar/plain-2-outline';
import refreshOutline from '@iconify-icons/solar/refresh-outline';
import settingsOutline from '@iconify-icons/solar/settings-outline';
import sun2Outline from '@iconify-icons/solar/sun-2-outline';
import translation2Outline from '@iconify-icons/solar/translation-2-outline';
import trashBinTrashOutline from '@iconify-icons/solar/trash-bin-trash-outline';
import userIdOutline from '@iconify-icons/solar/user-id-outline';
import { Icon } from '@iconify/react';
import { useEffect, useId, useRef, useState, type ButtonHTMLAttributes, type ReactNode } from 'react';

const icons = {
  'alt-arrow-left-outline': altArrowLeftOutline,
  'alt-arrow-right-outline': altArrowRightOutline,
  'check-circle-outline': checkCircleOutline,
  'clipboard-remove-outline': clipboardRemoveOutline,
  'close-circle-outline': closeCircleOutline,
  'code-square-outline': codeSquareOutline,
  'danger-triangle-outline': dangerTriangleOutline,
  'diskette-outline': disketteOutline,
  'document-add-outline': documentAddOutline,
  'gallery-outline': galleryOutline,
  'gallery-wide-outline': galleryWideOutline,
  'history-outline': historyOutline,
  'inbox-unread-outline': inboxUnreadOutline,
  'letter-bold': letterBold,
  'lightbulb-bolt-outline': lightbulbBoltOutline,
  'magic-stick-3-outline': magicStick3Outline,
  'mailbox-outline': mailboxOutline,
  'moon-outline': moonOutline,
  'paperclip-outline': paperclipOutline,
  'pen-new-square-outline': penNewSquareOutline,
  'plain-2-outline': plain2Outline,
  'refresh-outline': refreshOutline,
  'settings-outline': settingsOutline,
  'sun-2-outline': sun2Outline,
  'translation-2-outline': translation2Outline,
  'trash-bin-trash-outline': trashBinTrashOutline,
  'user-id-outline': userIdOutline,
};

export type IconName = keyof typeof icons;
export type BadgeTone = 'info' | 'success' | 'warning' | 'danger' | 'neutral';

export function AppIcon({ icon, width = 18 }: { icon: IconName; width?: number }) {
  return <Icon icon={icons[icon]} width={width} aria-hidden="true" />;
}

export function Badge({ children, tone = 'neutral' }: { children: ReactNode; tone?: BadgeTone }) {
  return <span className={`badge badge-${tone}`}>{children}</span>;
}

export function IconButton({ icon, label, className = '', ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { icon: IconName; label: string }) {
  return (
    <button className={`icon-button ${className}`.trim()} aria-label={label} title={label} {...props}>
      <AppIcon icon={icon} />
    </button>
  );
}

export function EmptyState({ icon, title, detail, action }: { icon: IconName; title: string; detail?: string; action?: ReactNode }) {
  return (
    <div className="empty-state">
      <AppIcon icon={icon} width={25} />
      <strong>{title}</strong>
      {detail && <span>{detail}</span>}
      {action}
    </div>
  );
}

export function InlineError({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="inline-state inline-error" role="alert">
      <AppIcon icon="danger-triangle-outline" />
      <span>{message}</span>
      {onRetry && (
        <button className="text-button" onClick={onRetry}>
          重试
        </button>
      )}
    </div>
  );
}

export function LoadingLine({ active }: { active: boolean }) {
  return <div className={`panel-progress-line ${active ? 'is-active' : ''}`} aria-hidden="true" />;
}

export function PanelHeader({
  title,
  meta,
  actions,
  compact,
  metaInline,
  className = '',
}: {
  title: string;
  meta?: string;
  actions?: ReactNode;
  compact?: boolean;
  metaInline?: boolean;
  className?: string;
}) {
  return (
    <div className={`panel-header ${compact ? 'is-compact' : ''} ${metaInline ? 'has-inline-meta' : ''} ${className}`.trim()}>
      <div className="panel-title-block">
        <h2>{title}</h2>
        {meta && <p>{meta}</p>}
      </div>
      {actions && <div className="panel-actions">{actions}</div>}
    </div>
  );
}

export type CustomDropdownOption<T extends string> = {
  value: T;
  label: string;
  meta?: string;
};

export function CustomDropdown<T extends string>({
  label,
  value,
  options,
  onChange,
  disabled,
  className = '',
  emptyLabel = '暂无选项',
}: {
  label: string;
  value: T;
  options: Array<CustomDropdownOption<T>>;
  onChange: (value: T) => void;
  disabled?: boolean;
  className?: string;
  emptyLabel?: string;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const labelId = useId();
  const menuId = useId();
  const selected = options.find((option) => option.value === value);
  const selectedLabel = selected?.label ?? emptyLabel;

  useEffect(() => {
    if (!open) return undefined;
    const onPointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    document.addEventListener('pointerdown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [open]);

  useEffect(() => {
    if (disabled) setOpen(false);
  }, [disabled]);

  return (
    <div className={`custom-dropdown ${className}`.trim()} ref={rootRef}>
      <span id={labelId} className="custom-dropdown-label">{label}</span>
      <button
        type="button"
        className={`custom-dropdown-trigger ${open ? 'is-open' : ''}`}
        aria-label={`${label}：${selectedLabel}`}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={menuId}
        disabled={disabled}
        onClick={() => setOpen((current) => !current)}
      >
        <span className="custom-dropdown-main">{selectedLabel}</span>
        {selected?.meta && <span className="custom-dropdown-sub">{selected.meta}</span>}
        <span className="custom-dropdown-chevron" aria-hidden="true" />
      </button>
      {open && (
        <div id={menuId} className="custom-dropdown-menu" role="listbox" aria-labelledby={labelId}>
          {options.map((option) => {
            const isSelected = option.value === value;
            return (
              <button
                key={option.value}
                type="button"
                role="option"
                aria-selected={isSelected}
                className={isSelected ? 'is-selected' : ''}
                onClick={() => {
                  setOpen(false);
                  if (!isSelected) onChange(option.value);
                }}
              >
                <span className="custom-dropdown-option-title">{option.label}</span>
                {option.meta && <span className="custom-dropdown-option-meta">{option.meta}</span>}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

export function SegmentedTabs<T extends string>({
  label,
  value,
  options,
  onChange,
  compact,
  disabled,
}: {
  label: string;
  value: T;
  options: Array<{ value: T; label: string; count?: number }>;
  onChange: (value: T) => void;
  compact?: boolean;
  disabled?: boolean;
}) {
  return (
    <div className={`segmented-tabs ${compact ? 'is-compact' : ''}`} role="tablist" aria-label={label}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          role="tab"
          aria-selected={value === option.value}
          className={value === option.value ? 'is-active' : ''}
          disabled={disabled}
          onClick={() => onChange(option.value)}
        >
          <span>{option.label}</span>
          {option.count !== undefined && <span className="tab-count">{option.count}</span>}
        </button>
      ))}
    </div>
  );
}
