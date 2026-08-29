import type { CSSProperties, ReactNode } from "react";

type WorkspaceKind = "cockpit" | "analysis" | "management";

function classNames(...values: Array<string | false | null | undefined>): string {
  return values.filter(Boolean).join(" ");
}

export function WorkspacePage({
  kind,
  className,
  children,
}: {
  kind: WorkspaceKind;
  className?: string;
  children: ReactNode;
}) {
  return <div className={classNames("ops-page-canvas", `ops-workspace--${kind}`, className)}>{children}</div>;
}

export function DecisionBand({
  eyebrow,
  title,
  description,
  action,
  ariaLabel,
}: {
  eyebrow: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  ariaLabel: string;
}) {
  return (
    <section className="ops-decision-band" aria-label={ariaLabel}>
      <div>
        <span className="ops-decision-band__eyebrow">{eyebrow}</span>
        <h2 className="ops-decision-band__title">{title}</h2>
        {description ? <span className="ops-decision-band__description">{description}</span> : null}
      </div>
      {action}
    </section>
  );
}

export function WorkspaceToolbar({
  tone = "default",
  className,
  children,
}: {
  tone?: "default" | "action";
  className?: string;
  children: ReactNode;
}) {
  return <div className={classNames("ops-filter-bar", tone === "action" && "ops-action-filter", className)}>{children}</div>;
}

export type MetricRailItem = {
  key?: string;
  label: ReactNode;
  value: ReactNode;
  hint?: ReactNode;
  tone?: string;
  onClick?: () => void;
  active?: boolean;
  ariaLabel?: string;
};

export function MetricRail({
  items,
  columns = 6,
  className,
  style,
}: {
  items: MetricRailItem[];
  columns?: 4 | 6;
  className?: string;
  style?: CSSProperties;
}) {
  return (
    <div className={classNames("ops-metric-rail", columns === 4 && "ops-metric-rail--four", className)} style={style}>
      {items.map((item, index) => (
        item.onClick ? <button
          type="button"
          className={classNames("ops-metric-rail__item", "is-clickable", item.active && "is-active")}
          key={item.key ?? `${index}-${String(item.label)}`}
          onClick={item.onClick}
          aria-label={item.ariaLabel ?? `${String(item.label)}，点击筛选`}
          aria-pressed={item.active}
        >
          <span className="ops-metric-rail__label">{item.label}</span>
          <span className="ops-metric-rail__value" style={item.tone ? { color: item.tone } : undefined}>{item.value}</span>
          {item.hint !== undefined ? <span className="ops-metric-rail__hint">{item.hint}</span> : null}
        </button> : <div className="ops-metric-rail__item" key={item.key ?? `${index}-${String(item.label)}`}>
          <span className="ops-metric-rail__label">{item.label}</span>
          <span className="ops-metric-rail__value" style={item.tone ? { color: item.tone } : undefined}>{item.value}</span>
          {item.hint !== undefined ? <span className="ops-metric-rail__hint">{item.hint}</span> : null}
        </div>
      ))}
    </div>
  );
}
