/** Three-segment urgency meter (mock `.urg`); `segments` of 0–3 lit, color keyed to `label`. */
export function UrgencyScale({ segments, label }: { segments: number; label?: string }) {
  return (
    <span
      className={`urg lvl-${label ?? "none"}`}
      title={label ? `Urgency: ${label}` : undefined}
      aria-label={label ? `Urgency ${label}` : "Urgency"}
    >
      {[1, 2, 3].map((i) => (
        <span key={i} className={"urg-seg" + (i <= segments ? " on" : "")} />
      ))}
    </span>
  );
}
