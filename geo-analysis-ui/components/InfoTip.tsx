"use client";

type Props = {
  text: string;
  label?: string;
};

/** Compact ? tooltip for dashboard widgets. */
export function InfoTip({ text, label = "What this means" }: Props) {
  return (
    <span className="info-tip">
      <button type="button" className="info-tip-btn" aria-label={label}>
        ?
      </button>
      <span className="info-tip-bubble" role="tooltip">
        {text}
      </span>
    </span>
  );
}
