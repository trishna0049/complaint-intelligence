import clsx from "clsx";
import { AlertTriangle, Inbox, Loader2, RefreshCw } from "lucide-react";
import {
  forwardRef,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from "react";

/* ---------------- Button ---------------- */
type Variant = "primary" | "secondary" | "ghost" | "danger" | "subtle";
const variants: Record<Variant, string> = {
  primary: "bg-brand-600 text-white hover:bg-brand-700 shadow-sm disabled:bg-brand-300",
  secondary:
    "bg-white text-slate-700 border border-slate-300 hover:bg-slate-50 shadow-sm disabled:text-slate-400",
  ghost: "text-slate-600 hover:bg-slate-100 hover:text-slate-900",
  danger: "bg-rose-600 text-white hover:bg-rose-700 shadow-sm disabled:bg-rose-300",
  subtle: "bg-brand-50 text-brand-700 hover:bg-brand-100",
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: "sm" | "md";
  loading?: boolean;
  icon?: ReactNode;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "primary", size = "md", loading, icon, className, children, disabled, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      className={clsx(
        "inline-flex items-center justify-center gap-1.5 rounded-md font-medium transition-colors",
        "focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 focus-visible:ring-offset-1",
        "disabled:cursor-not-allowed",
        size === "sm" ? "h-8 px-2.5 text-xs" : "h-9 px-3.5 text-sm",
        variants[variant],
        className,
      )}
      disabled={disabled || loading}
      {...rest}
    >
      {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : icon}
      {children}
    </button>
  );
});

/* ---------------- Form fields ---------------- */
// Full width unless the caller passes its own width class (e.g. "w-40").
const width = (className?: string) => (/(^|\s)w-/.test(className ?? "") ? "" : "w-full");
const fieldBase =
  "block rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-900 shadow-sm " +
  "placeholder:text-slate-400 focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20 " +
  "disabled:bg-slate-50 disabled:text-slate-500";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input(
  { className, ...rest },
  ref,
) {
  return <input ref={ref} className={clsx(fieldBase, width(className), "h-9", className)} {...rest} />;
});

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(
  function Textarea({ className, ...rest }, ref) {
    return <textarea ref={ref} className={clsx(fieldBase, width(className), "py-2 leading-relaxed", className)} {...rest} />;
  },
);

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(function Select(
  { className, children, ...rest },
  ref,
) {
  return (
    <select ref={ref} className={clsx(fieldBase, width(className), "h-9 pr-8", className)} {...rest}>
      {children}
    </select>
  );
});

export function Field({
  label,
  htmlFor,
  hint,
  error,
  children,
  className,
}: {
  label: string;
  htmlFor?: string;
  hint?: string;
  error?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={className}>
      <label htmlFor={htmlFor} className="mb-1 block text-xs font-medium text-slate-700">
        {label}
      </label>
      {children}
      {error ? (
        <p className="mt-1 text-xs text-rose-600">{error}</p>
      ) : hint ? (
        <p className="mt-1 text-xs text-slate-500">{hint}</p>
      ) : null}
    </div>
  );
}

/* ---------------- Surfaces ---------------- */
export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={clsx("rounded-lg border border-slate-200 bg-white shadow-card", className)}>{children}</div>;
}

export function CardHeader({
  title,
  subtitle,
  actions,
  icon,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-3 border-b border-slate-100 px-4 py-3">
      <div className="flex min-w-0 items-start gap-2">
        {icon && <span className="mt-0.5 text-slate-400">{icon}</span>}
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-slate-900">{title}</h3>
          {subtitle && <p className="mt-0.5 text-xs text-slate-500">{subtitle}</p>}
        </div>
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  );
}

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold tracking-tight text-slate-900">{title}</h1>
        {description && <p className="mt-1 text-sm text-slate-500">{description}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}

/* ---------------- Badges ---------------- */
export type Tone = "slate" | "blue" | "green" | "amber" | "red" | "violet" | "brand" | "teal";
const tones: Record<Tone, string> = {
  slate: "bg-slate-100 text-slate-700 ring-slate-200",
  blue: "bg-sky-50 text-sky-700 ring-sky-200",
  green: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  amber: "bg-amber-50 text-amber-800 ring-amber-200",
  red: "bg-rose-50 text-rose-700 ring-rose-200",
  violet: "bg-violet-50 text-violet-700 ring-violet-200",
  brand: "bg-brand-50 text-brand-700 ring-brand-200",
  teal: "bg-teal-50 text-teal-700 ring-teal-200",
};

export function Badge({
  tone = "slate",
  children,
  className,
  dot,
  title,
}: {
  tone?: Tone;
  children: ReactNode;
  className?: string;
  dot?: boolean;
  title?: string;
}) {
  return (
    <span
      title={title}
      className={clsx(
        "inline-flex items-center gap-1 whitespace-nowrap rounded-md px-1.5 py-0.5 text-xs font-medium ring-1 ring-inset",
        tones[tone],
        className,
      )}
    >
      {dot && <span className="h-1.5 w-1.5 rounded-full bg-current" />}
      {children}
    </span>
  );
}

/* ---------------- States ---------------- */
export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={clsx("h-5 w-5 animate-spin text-slate-400", className)} />;
}

export function LoadingState({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 py-16 text-sm text-slate-500" role="status">
      <Spinner /> {label}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={clsx("animate-pulse rounded bg-slate-200/70", className)} />;
}

export function EmptyState({
  title,
  description,
  icon,
  action,
}: {
  title: string;
  description?: string;
  icon?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-14 text-center">
      <div className="mb-3 rounded-full bg-slate-100 p-3 text-slate-400">{icon ?? <Inbox className="h-6 w-6" />}</div>
      <p className="text-sm font-medium text-slate-900">{title}</p>
      {description && <p className="mt-1 max-w-sm text-sm text-slate-500">{description}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const message = error instanceof Error ? error.message : "Something went wrong";
  return (
    <div className="flex flex-col items-center justify-center px-6 py-12 text-center" role="alert">
      <div className="mb-3 rounded-full bg-rose-50 p-3 text-rose-500">
        <AlertTriangle className="h-6 w-6" />
      </div>
      <p className="text-sm font-medium text-slate-900">Couldn’t load this</p>
      <p className="mt-1 max-w-sm text-sm text-slate-500">{message}</p>
      {onRetry && (
        <Button variant="secondary" size="sm" className="mt-4" onClick={onRetry} icon={<RefreshCw className="h-3.5 w-3.5" />}>
          Try again
        </Button>
      )}
    </div>
  );
}

export function Avatar({ name, size = "md" }: { name: string; size?: "sm" | "md" }) {
  const initials = name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase())
    .join("");
  const palette = ["bg-indigo-100 text-indigo-700", "bg-emerald-100 text-emerald-700", "bg-amber-100 text-amber-800",
    "bg-sky-100 text-sky-700", "bg-rose-100 text-rose-700", "bg-violet-100 text-violet-700"];
  const color = palette[[...name].reduce((a, c) => a + c.charCodeAt(0), 0) % palette.length];
  return (
    <span
      className={clsx(
        "inline-flex shrink-0 items-center justify-center rounded-full font-semibold",
        size === "sm" ? "h-6 w-6 text-[10px]" : "h-8 w-8 text-xs",
        color,
      )}
      aria-hidden
    >
      {initials || "?"}
    </span>
  );
}

export function Modal({
  open,
  title,
  onClose,
  children,
  footer,
  wide,
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  wide?: boolean;
}) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-slate-900/40 p-4 pt-[10vh]" onMouseDown={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={clsx("w-full rounded-lg bg-white shadow-xl", wide ? "max-w-2xl" : "max-w-md")}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="border-b border-slate-100 px-5 py-3.5">
          <h2 className="text-sm font-semibold text-slate-900">{title}</h2>
        </div>
        <div className="px-5 py-4">{children}</div>
        {footer && <div className="flex justify-end gap-2 border-t border-slate-100 bg-slate-50/60 px-5 py-3">{footer}</div>}
      </div>
    </div>
  );
}
