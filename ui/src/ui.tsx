// Small shared pieces: badges, chips, formatting.

import type { JobLifecycle } from "./api";

export function KindBadge({ kind, fidelity }: { kind: string; fidelity?: string }) {
  const label = kind === "manim_checkpoint" ? "Manim checkpoint" : kind === "sampled_video_frame" ? "sampled video frame" : "storyboard schematic";
  return (
    <span className={`badge badge-${kind}`} title={`preview kind: ${kind}`}>
      {label}
      {fidelity && fidelity !== "exact" ? ` · ${fidelity}` : ""}
    </span>
  );
}

export function StatusChip({ status }: { status: JobLifecycle | string }) {
  return <span className={`chip chip-${status}`}>{status.replace("_", " ")}</span>;
}

export function formatTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString();
}

export function seconds(value: number | null | undefined, digits = 1): string {
  return value == null ? "" : `${value.toFixed(digits)} s`;
}

export function percent(fraction: number | null | undefined): string {
  return fraction == null ? "" : `${(100 * fraction).toFixed(2)}%`;
}

export function ErrorBox({ error }: { error: string | null }) {
  return error ? <div className="error-box">{error}</div> : null;
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <p className="empty">{children}</p>;
}
