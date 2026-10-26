import { useCallback, useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";

import { api, isActive, type BBox, type Checkpoint, type Feedback, type Job, type LayoutItem, type ReviewStatus, type Severity } from "../api";
import { navigate, routes } from "../router";
import { Empty, ErrorBox, KindBadge, StatusChip, formatTime } from "../ui";

const SEVERITIES: Severity[] = ["visual", "scientific", "timing", "other"];
const STATUSES: { value: ReviewStatus; label: string }[] = [
  { value: "approved", label: "Approve" },
  { value: "needs_revision", label: "Needs revision" },
  { value: "scientific_concern", label: "Scientific concern" },
];

type Draft = { x1: number; y1: number; x2: number; y2: number };

function clamp(value: number): number {
  return Math.min(1, Math.max(0, value));
}

function rectOf(draft: Draft): BBox {
  const x = Math.min(draft.x1, draft.x2);
  const y = Math.min(draft.y1, draft.y2);
  return { x, y, width: Math.abs(draft.x2 - draft.x1), height: Math.abs(draft.y2 - draft.y1) };
}

function clampBox(b: BBox): BBox {
  const x = clamp(b.x);
  const y = clamp(b.y);
  return { x, y, width: Math.max(0.001, Math.min(1 - x, b.x + b.width - x)), height: Math.max(0.001, Math.min(1 - y, b.y + b.height - y)) };
}

export default function Review({ id, jobId, snapshotId }: { id: string; jobId?: string; snapshotId?: string }) {
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<Feedback[]>([]);
  const [selected, setSelected] = useState<string | undefined>(snapshotId);
  useEffect(() => {
    setSelected(snapshotId);
  }, [snapshotId]);
  const [objectId, setObjectId] = useState<string | null>(null);
  const [region, setRegion] = useState<BBox | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [hover, setHover] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [severity, setSeverity] = useState<Severity>("visual");
  const [author, setAuthor] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const imageRef = useRef<HTMLImageElement | null>(null);

  // Without a job id, show the latest succeeded render of the working copy.
  useEffect(() => {
    if (jobId) return;
    api
      .project(id)
      .then((detail) => {
        const latest = detail.latest_render.working ?? Object.values(detail.latest_render)[0];
        if (latest) window.location.hash = `#${routes.review(id, latest)}`;
        else setError("No succeeded render yet; render snapshots from the overview first.");
      })
      .catch((e: Error) => setError(e.message));
  }, [id, jobId]);

  const loadJob = useCallback(() => {
    if (!jobId) return;
    api
      .job(id, jobId)
      .then((j) => {
        setJob(j);
        setError(null);
      })
      .catch((e: Error) => setError(e.message));
  }, [id, jobId]);

  useEffect(() => {
    setJob(null);
    loadJob();
  }, [loadJob]);

  useEffect(() => {
    if (!job || !isActive(job.status)) return;
    const timer = window.setInterval(loadJob, 2000);
    return () => window.clearInterval(timer);
  }, [job, loadJob]);

  const checkpoint: Checkpoint | undefined = useMemo(() => {
    if (!job) return undefined;
    return job.checkpoints.find((c) => c.snapshot_id === selected) ?? job.checkpoints[0];
  }, [job, selected]);

  const loadFeedback = useCallback(() => {
    if (!job || !checkpoint) return;
    api
      .feedback(id, { revision_id: job.revision_id, snapshot_id: checkpoint.snapshot_id })
      .then(setFeedback)
      .catch((e: Error) => setError(e.message));
  }, [id, job, checkpoint]);

  useEffect(() => {
    loadFeedback();
  }, [loadFeedback]);

  useEffect(() => {
    setObjectId(null);
    setRegion(null);
    setDraft(null);
  }, [checkpoint?.snapshot_id]);

  function toNormalized(event: ReactPointerEvent<SVGSVGElement>): { x: number; y: number } {
    const rect = (imageRef.current ?? event.currentTarget).getBoundingClientRect();
    return { x: clamp((event.clientX - rect.left) / rect.width), y: clamp((event.clientY - rect.top) / rect.height) };
  }

  function hitTest(point: { x: number; y: number }): LayoutItem | null {
    if (!checkpoint) return null;
    const hits = checkpoint.layout.filter(
      (item) => point.x >= item.bbox.x && point.x <= item.bbox.x + item.bbox.width && point.y >= item.bbox.y && point.y <= item.bbox.y + item.bbox.height,
    );
    hits.sort((p, q) => p.bbox.width * p.bbox.height - q.bbox.width * q.bbox.height);
    return hits[0] ?? null;
  }

  function onPointerDown(event: ReactPointerEvent<SVGSVGElement>) {
    const point = toNormalized(event);
    setDraft({ x1: point.x, y1: point.y, x2: point.x, y2: point.y });
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function onPointerMove(event: ReactPointerEvent<SVGSVGElement>) {
    const point = toNormalized(event);
    if (draft) {
      setDraft({ ...draft, x2: point.x, y2: point.y });
    } else {
      setHover(hitTest(point)?.object_id ?? null);
    }
  }

  function onPointerUp(event: ReactPointerEvent<SVGSVGElement>) {
    if (!draft) return;
    const point = toNormalized(event);
    const box = rectOf({ ...draft, x2: point.x, y2: point.y });
    setDraft(null);
    if (box.width < 0.005 && box.height < 0.005) {
      const item = hitTest(point);
      if (item) {
        setObjectId(item.object_id);
        setRegion(clampBox(item.bbox));
      } else {
        setObjectId(null);
        setRegion(null);
      }
      return;
    }
    setObjectId(null);
    setRegion(clampBox(box));
  }

  async function submitComment() {
    if (!job || !checkpoint || !text.trim()) return;
    setBusy(true);
    try {
      const kind = objectId ? "object_comment" : region ? "region_comment" : "general_comment";
      await api.addFeedback(id, {
        revision_id: job.revision_id,
        job_id: job.job_id,
        kind,
        snapshot_id: checkpoint.snapshot_id,
        scene_id: checkpoint.scene_id,
        object_id: objectId ?? undefined,
        region: region ?? undefined,
        text: text.trim(),
        severity,
        author: author.trim() || undefined,
      });
      setText("");
      setObjectId(null);
      setRegion(null);
      loadFeedback();
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function submitStatus(status: ReviewStatus) {
    if (!job || !checkpoint) return;
    setBusy(true);
    try {
      await api.addFeedback(id, {
        revision_id: job.revision_id,
        job_id: job.job_id,
        kind: "status",
        status,
        snapshot_id: checkpoint.snapshot_id,
        scene_id: checkpoint.scene_id,
        text: note.trim(),
        author: author.trim() || undefined,
      });
      setNote("");
      loadFeedback();
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (!jobId) return <ErrorBox error={error} />;
  if (!job) return error ? <ErrorBox error={error} /> : <Empty>Loading…</Empty>;
  if (isActive(job.status)) {
    return (
      <div>
        <StatusChip status={job.status} /> <span className="meta">job {job.job_id} is still running; this page refreshes itself.</span>
      </div>
    );
  }
  if (!checkpoint) {
    return (
      <div>
        <StatusChip status={job.status} />
        <ErrorBox error={job.error ?? "This job produced no checkpoints."} />
      </div>
    );
  }

  const statuses = feedback.filter((f) => f.kind === "status");
  const latestStatus = statuses[statuses.length - 1];
  const selectedItem = checkpoint.layout.find((i) => i.object_id === objectId);

  return (
    <div>
      <p className="meta">
        job <code>{job.job_id}</code> · revision <code>{job.revision_id}</code> · {job.pixel_width}×{job.pixel_height} ·{" "}
        {job.review_sheet_url ? <a href={job.review_sheet_url} target="_blank" rel="noreferrer">static review sheet</a> : null}
        {job.worker_warnings?.length ? <> · {job.worker_warnings.join("; ")}</> : null}
      </p>
      <ErrorBox error={error} />
      <div className="review">
        <div className="filmstrip" data-testid="filmstrip">
          {job.checkpoints.map((c) => (
            <button
              key={c.snapshot_id}
              className={`thumb${c.snapshot_id === checkpoint.snapshot_id ? " active" : ""}`}
              onClick={() => navigate(routes.review(id, job.job_id), { snapshot: c.snapshot_id })}
              data-testid={`thumb-${c.snapshot_id}`}
            >
              <img src={c.url} alt={c.description} />
              <div className="label">{c.snapshot_id}</div>
              <div className="sub">
                {c.scene_id} · {c.expected_time_seconds} s{c.warnings.length ? ` · ${c.warnings.length} warning(s)` : ""}
              </div>
            </button>
          ))}
        </div>

        <div>
          <div style={{ display: "flex", gap: 8, alignItems: "baseline", marginBottom: 6 }}>
            <strong data-testid="snapshot-title">{checkpoint.snapshot_id}</strong>
            <KindBadge kind={checkpoint.kind} fidelity={checkpoint.fidelity} />
            {latestStatus?.status ? <StatusChip status={latestStatus.status} /> : null}
            <span className="meta">
              scene {checkpoint.scene_id}, requested {checkpoint.expected_time_seconds} s, animation #{checkpoint.animation_index}
            </span>
          </div>
          <div className="viewer" data-testid="viewer">
            <img ref={imageRef} src={checkpoint.url} alt={checkpoint.description} draggable={false} />
            <svg
              viewBox="0 0 1 1"
              preserveAspectRatio="none"
              onPointerDown={onPointerDown}
              onPointerMove={onPointerMove}
              onPointerUp={onPointerUp}
              onPointerLeave={() => setHover(null)}
              data-testid="overlay"
            >
              {checkpoint.layout.map((item) => (
                <rect
                  key={item.object_id}
                  className={`object${item.object_id === objectId ? " selected" : ""}${item.object_id === hover ? " hover" : ""}`}
                  x={item.bbox.x}
                  y={item.bbox.y}
                  width={item.bbox.width}
                  height={item.bbox.height}
                  data-object-id={item.object_id}
                >
                  <title>{`${item.object_id} (${item.kind})`}</title>
                </rect>
              ))}
              {feedback
                .filter((f) => f.region)
                .map((f) => (
                  <rect
                    key={f.id}
                    className={`feedback${hover === f.id ? " hover" : ""}`}
                    x={f.region!.x}
                    y={f.region!.y}
                    width={f.region!.width}
                    height={f.region!.height}
                  >
                    <title>{f.text}</title>
                  </rect>
                ))}
              {draft && (() => {
                const box = rectOf(draft);
                return <rect className="draft" x={box.x} y={box.y} width={box.width} height={box.height} />;
              })()}
              {!draft && region && !objectId && <rect className="draft" x={region.x} y={region.y} width={region.width} height={region.height} />}
            </svg>
          </div>
          <p className="meta" style={{ marginTop: 6 }}>
            {checkpoint.description}
            {checkpoint.fidelity_note ? ` · ${checkpoint.fidelity_note}` : ""}
          </p>
          {checkpoint.warnings.map((w) => (
            <div className="warn-box" key={`${w.code}-${w.object_ids.join(",")}`}>
              {w.code}: {w.detail} ({w.object_ids.join(", ")})
            </div>
          ))}
          <h3 style={{ marginTop: 14 }}>Layout report</h3>
          <table className="layout-table">
            <thead>
              <tr>
                <th>object</th>
                <th>kind</th>
                <th>x</th>
                <th>y</th>
                <th>w</th>
                <th>h</th>
                <th>text px</th>
              </tr>
            </thead>
            <tbody>
              {checkpoint.layout.map((item) => (
                <tr
                  key={item.object_id}
                  onMouseEnter={() => setHover(item.object_id)}
                  onMouseLeave={() => setHover(null)}
                  onClick={() => {
                    setObjectId(item.object_id);
                    setRegion(clampBox(item.bbox));
                  }}
                  style={{ cursor: "pointer" }}
                >
                  <td>{item.object_id}</td>
                  <td>{item.kind}</td>
                  <td>{item.bbox.x.toFixed(3)}</td>
                  <td>{item.bbox.y.toFixed(3)}</td>
                  <td>{item.bbox.width.toFixed(3)}</td>
                  <td>{item.bbox.height.toFixed(3)}</td>
                  <td>{item.text_height_px?.toFixed(0) ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <aside className="panel">
          <div className="target" data-testid="target">
            {selectedItem ? (
              <>
                object <code>{selectedItem.object_id}</code> ({selectedItem.kind})
              </>
            ) : region ? (
              <>
                region x {region.x.toFixed(2)} y {region.y.toFixed(2)} w {region.width.toFixed(2)} h {region.height.toFixed(2)}
              </>
            ) : (
              <>click an object or drag a region on the image; or comment on the whole frame</>
            )}
          </div>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="What should change, and why?"
            data-testid="comment-text"
          />
          <div className="toolbar" style={{ margin: 0 }}>
            <select value={severity} onChange={(e) => setSeverity(e.target.value as Severity)} data-testid="severity">
              {SEVERITIES.map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
            <input type="text" value={author} onChange={(e) => setAuthor(e.target.value)} placeholder="author (optional)" style={{ width: 140 }} />
            <button className="primary" onClick={submitComment} disabled={busy || !text.trim()} data-testid="submit-comment">
              Add comment
            </button>
          </div>
          <div>
            <h3>Checkpoint status</h3>
            <input type="text" value={note} onChange={(e) => setNote(e.target.value)} placeholder="note (optional)" style={{ width: "100%", marginBottom: 6 }} />
            <div className="status-buttons">
              {STATUSES.map((s) => (
                <button
                  key={s.value}
                  onClick={() => submitStatus(s.value)}
                  disabled={busy || (s.value === "approved" && job.revision_id === "working")}
                  title={
                    s.value === "approved" && job.revision_id === "working"
                      ? "Approval needs an immutable revision: run `scianim revision create` and render it"
                      : `record ${s.label.toLowerCase()} for this image (${checkpoint.sha256.slice(0, 12)}…)`
                  }
                  data-testid={`status-${s.value}`}
                >
                  {s.label}
                </button>
              ))}
            </div>
            {job.revision_id === "working" ? (
              <p className="meta">Approval is only possible on a frozen revision; the working copy may still change.</p>
            ) : null}
          </div>
          <div>
            <h3>Feedback on this snapshot ({feedback.length})</h3>
            <div className="feedback-list" data-testid="feedback-list">
              {feedback.length === 0 ? <Empty>none yet</Empty> : null}
              {[...feedback].reverse().map((f) => (
                <div
                  key={f.id}
                  className={`feedback-item${hover === f.id ? " hover" : ""}`}
                  onMouseEnter={() => setHover(f.id)}
                  onMouseLeave={() => setHover(null)}
                  data-testid={`feedback-${f.id}`}
                >
                  {f.kind === "status" ? (
                    <>
                      <StatusChip status={f.status ?? ""} /> {f.text}
                    </>
                  ) : (
                    <>
                      <span className="chip">{f.severity}</span> {f.object_id ? <code>{f.object_id}</code> : f.region ? <span className="meta">region</span> : null} {f.text}
                    </>
                  )}
                  <div className="who">
                    {f.author ? `${f.author} · ` : ""}
                    {formatTime(f.created_at)} · {f.revision_id}
                    {f.image_sha256 ? ` · image ${f.image_sha256.slice(0, 8)}` : ""}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}
