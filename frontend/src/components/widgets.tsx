import { ReactNode, useEffect, useId } from "react";
import { createPortal } from "react-dom";

export function Chip({ children, tone = "" }: { children: ReactNode; tone?: string }) {
  return <span className={`chip ${tone}`}>{children}</span>;
}

export function QcChip({ status }: { status: string }) {
  const tone = status === "passed" ? "ok" : status === "warning" ? "warn" : "bad";
  return <Chip tone={tone}>QC {status}</Chip>;
}

export function AsrChip({ status }: { status: string }) {
  if (!status || status === "not_run") return <Chip tone="off">ASR not run</Chip>;
  const tone =
    status === "match" ? "ok" : status === "minor_mismatch" ? "warn" : "bad";
  return <Chip tone={tone}>ASR {status.replace("_", " ")}</Chip>;
}

export function HumanChip({ status }: { status: string }) {
  const tone = status === "accepted" ? "ok" : status === "rejected" ? "bad" : "off";
  return <Chip tone={tone}>{status}</Chip>;
}

export function Modal({
  title,
  onClose,
  children,
  wide,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  wide?: boolean;
}) {
  const titleId = useId();

  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", closeOnEscape);
    document.body.classList.add("modal-open");
    return () => {
      document.removeEventListener("keydown", closeOnEscape);
      document.body.classList.remove("modal-open");
    };
  }, [onClose]);

  return createPortal(
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div
        className={`modal ${wide ? "wide" : ""}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
      >
        <div className="modal-head">
          <h3 id={titleId}>{title}</h3>
          <button className="icon-btn" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>
        <div className="modal-body">{children}</div>
      </div>
    </div>,
    document.body
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <span className="spinner-wrap">
      <span className="spinner" />
      {label && <span className="muted small">{label}</span>}
    </span>
  );
}

export function MultiSelect({
  options,
  value,
  onChange,
}: {
  options: string[];
  value: string[];
  onChange: (v: string[]) => void;
}) {
  return (
    <div className="multi-select">
      {options.map((o) => (
        <label key={o} className={value.includes(o) ? "on" : ""}>
          <input
            type="checkbox"
            checked={value.includes(o)}
            onChange={(e) =>
              onChange(e.target.checked ? [...value, o] : value.filter((v) => v !== o))
            }
          />
          {o}
        </label>
      ))}
    </div>
  );
}
