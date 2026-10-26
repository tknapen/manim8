import { useCallback, useEffect, useRef, useState } from "react";

import { api, isActive, type Feedback, type Job, type Severity } from "../api";
import { routes } from "../router";
import { Empty, ErrorBox, KindBadge, StatusChip, formatTime, seconds } from "../ui";

const SEVERITIES: Severity[] = ["visual", "scientific", "timing", "other"];

export default function Video({ id, jobId }: { id: string; jobId?: string }) {
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<Feedback[]>([]);
  const [text, setText] = useState("");
  const [severity, setSeverity] = useState<Severity>("timing");
  const [author, setAuthor] = useState("");
  const [busy, setBusy] = useState(false);
  const [current, setCurrent] = useState(0);
  const videoRef = useRef<HTMLVideoElement | null>(null);

  // Without a job id, open the latest succeeded video of the working copy (or any revision).
  useEffect(() => {
    if (jobId) return;
    api
      .project(id)
      .then((detail) => {
        const latest = detail.latest_video.working ?? Object.values(detail.latest_video)[0];
        if (latest) window.location.hash = `#${routes.video(id, latest)}`;
        else setError("No succeeded video yet; render a draft from the overview first.");
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

  const loadFeedback = useCallback(() => {
    if (!job) return;
    api
      .feedback(id, { revision_id: job.revision_id })
      .then((all) => setFeedback(all.filter((f) => f.job_id === job.job_id || f.time_seconds != null)))
      .catch((e: Error) => setError(e.message));
  }, [id, job]);

  useEffect(() => {
    loadFeedback();
  }, [loadFeedback]);

  async function submit() {
    if (!job || !text.trim()) return;
    setBusy(true);
    try {
      const scene = job.timing?.scenes.find((s) => s.start_seconds <= current && current <= s.end_seconds);
      await api.addFeedback(id, {
        revision_id: job.revision_id,
        job_id: job.job_id,
        kind: "general_comment",
        scene_id: scene?.scene_id,
        text: text.trim(),
        severity,
        author: author.trim() || undefined,
        time_seconds: Math.round(current * 1000) / 1000,
      });
      setText("");
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
  const video = job.videos?.[0];
  if (!video) {
    return (
      <div>
        <StatusChip status={job.status} />
        <ErrorBox error={job.error ?? "This job produced no video."} />
      </div>
    );
  }
  const samples = job.checkpoints.filter((c) => c.kind === "sampled_video_frame");

  return (
    <div>
      <h1>
        {job.profile} video <span className="badge">{video.width_px}×{video.height_px} · {video.fps} fps · {video.frame_count} frames · {video.duration_seconds.toFixed(2)} s · {video.codec}</span>
      </h1>
      <p className="meta">
        job <code>{job.job_id}</code> · revision <code>{job.revision_id}</code> · {job.subtitles_url ? <a href={job.subtitles_url}>subtitles (SRT)</a> : "no subtitles"} ·{" "}
        <a href={video.url} download>
          download
        </a>
        {job.review_sheet_url ? (
          <>
            {" "}
            · <a href={job.review_sheet_url} target="_blank" rel="noreferrer">static review sheet</a>
          </>
        ) : null}
      </p>
      <ErrorBox error={error} />
      <div className="review" style={{ gridTemplateColumns: "1fr 340px" }}>
        <div>
          <video
            ref={videoRef}
            src={video.url}
            controls
            preload="metadata"
            style={{ width: "100%", border: "1px solid var(--line)", background: "#fff" }}
            onTimeUpdate={(e) => setCurrent(e.currentTarget.currentTime)}
            data-testid="player"
          >
            {job.subtitles_url ? <track kind="subtitles" src={job.subtitles_url} srcLang="en" label="narration" default /> : null}
          </video>
          {job.timing ? (
            <div style={{ marginTop: 12 }}>
              <h3>
                Timing{" "}
                <span className={`stat ${job.timing.within_tolerance ? "identical" : "changed"}`}>
                  {job.timing.within_tolerance ? "matches the storyboard" : "differs from the storyboard"}
                </span>
                <span className="meta">
                  {" "}
                  · {job.timing.actual_total_frames} of {job.timing.expected_total_frames} frames at {job.timing.fps} fps (tolerance {job.timing.tolerance_frames})
                </span>
              </h3>
              {job.timing.problems.map((p) => (
                <div className="warn-box" key={p}>
                  {p}
                </div>
              ))}
              <table>
                <thead>
                  <tr>
                    <th>scene</th>
                    <th>storyboard</th>
                    <th>expected frames</th>
                    <th>section frames</th>
                    <th>delta</th>
                  </tr>
                </thead>
                <tbody>
                  {job.timing.scenes.map((s) => (
                    <tr key={s.scene_id}>
                      <td>
                        <a onClick={() => videoRef.current && (videoRef.current.currentTime = s.start_seconds)} style={{ cursor: "pointer" }}>
                          <code>{s.scene_id}</code>
                        </a>
                      </td>
                      <td>
                        {s.start_seconds}–{s.end_seconds} s
                      </td>
                      <td>{s.expected_frames}</td>
                      <td>{s.actual_frames ?? "–"}</td>
                      <td className={s.delta_frames ? "stat changed" : ""}>{s.delta_frames == null ? "–" : s.delta_frames}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {job.timing.notes.map((n) => (
                <p className="meta" key={n}>
                  {n}
                </p>
              ))}
            </div>
          ) : null}
          {samples.length ? (
            <div style={{ marginTop: 16 }}>
              <h3>Sampled frames</h3>
              <p className="meta">Exact frames decoded from this video at the moment each checkpoint was reached; they confirm checkpoints that fast-forward can only approximate.</p>
              <div className="cards">
                {samples.map((c) => (
                  <div className="card" key={c.snapshot_id} style={{ padding: 6 }}>
                    <img src={c.url} alt={c.description} style={{ width: "100%", display: "block", cursor: "pointer" }} onClick={() => videoRef.current && (videoRef.current.currentTime = c.renderer_time_seconds ?? c.expected_time_seconds)} />
                    <div style={{ marginTop: 4 }}>
                      <code>{c.snapshot_id}</code> <KindBadge kind={c.kind} fidelity={c.fidelity} />
                      <div className="meta">
                        requested {c.expected_time_seconds} s · frame at {c.renderer_time_seconds?.toFixed(3)} s{c.fidelity_note ? ` · ${c.fidelity_note}` : ""}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ) : null}
          {job.sections?.length ? (
            <div style={{ marginTop: 16 }}>
              <h3>Sections</h3>
              <table>
                <tbody>
                  {job.sections.map((s) => (
                    <tr key={s.name}>
                      <td>
                        <code>{s.name}</code>
                      </td>
                      <td>{String(s.metadata.frames ?? "")} frames</td>
                      <td>{seconds(Number(s.metadata.duration_seconds ?? 0), 3)}</td>
                      <td>{s.url ? <a href={s.url}>section video</a> : null}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </div>
        <aside className="panel">
          <div className="target">
            comment at <strong>{current.toFixed(2)} s</strong> of the video
          </div>
          <textarea value={text} onChange={(e) => setText(e.target.value)} placeholder="What should change at this moment, and why?" data-testid="video-comment-text" />
          <div className="toolbar" style={{ margin: 0 }}>
            <select value={severity} onChange={(e) => setSeverity(e.target.value as Severity)}>
              {SEVERITIES.map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
            <input type="text" value={author} onChange={(e) => setAuthor(e.target.value)} placeholder="author (optional)" style={{ width: 140 }} />
            <button className="primary" onClick={submit} disabled={busy || !text.trim()} data-testid="submit-video-comment">
              Add comment
            </button>
          </div>
          <div>
            <h3>Timestamped comments ({feedback.length})</h3>
            <div className="feedback-list" data-testid="video-feedback-list">
              {feedback.length === 0 ? <Empty>none yet</Empty> : null}
              {[...feedback].reverse().map((f) => (
                <div key={f.id} className="feedback-item" data-testid={`feedback-${f.id}`}>
                  {f.time_seconds != null ? (
                    <a onClick={() => videoRef.current && (videoRef.current.currentTime = f.time_seconds ?? 0)} style={{ cursor: "pointer" }}>
                      <code>{f.time_seconds.toFixed(2)} s</code>
                    </a>
                  ) : null}{" "}
                  <span className="chip">{f.severity}</span> {f.scene_id ? <code>{f.scene_id}</code> : null} {f.text}
                  <div className="who">
                    {f.author ? `${f.author} · ` : ""}
                    {formatTime(f.created_at)} · {f.revision_id}
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
