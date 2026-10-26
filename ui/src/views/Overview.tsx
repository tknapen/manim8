import { useCallback, useEffect, useState } from "react";

import { api, isActive, type ProjectDetail } from "../api";
import { routes } from "../router";
import { Empty, ErrorBox, StatusChip, formatTime, seconds } from "../ui";

const PROFILES = ["storyboard", "snapshot", "draft", "final"];

export default function Overview({ id }: { id: string }) {
  const [detail, setDetail] = useState<ProjectDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState("working");
  const [profile, setProfile] = useState("snapshot");
  const [noCache, setNoCache] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const load = useCallback(() => {
    api
      .project(id)
      .then((d) => {
        setDetail(d);
        setError(null);
      })
      .catch((e: Error) => setError(e.message));
  }, [id]);

  useEffect(() => {
    setDetail(null);
    load();
  }, [load]);

  const active = detail?.jobs.some((job) => isActive(job.status)) ?? false;
  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(load, 2000);
    return () => window.clearInterval(timer);
  }, [active, load]);

  async function render(operation: "render_snapshots" | "render_video" = "render_snapshots", videoProfile?: string) {
    setSubmitting(true);
    try {
      await api.submitJob(id, {
        revision_id: revision,
        snapshot_ids: [],
        profile: operation === "render_video" ? (videoProfile ?? "draft") : profile,
        no_cache: noCache,
        operation,
      });
      load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSubmitting(false);
    }
  }

  if (!detail) return error ? <ErrorBox error={error} /> : <Empty>Loading…</Empty>;
  const { animation, storyboard } = detail;
  const latest = detail.latest_render[revision];

  return (
    <div>
      <h1 data-testid="project-title">{detail.title}</h1>
      <p className="meta">
        <code>{detail.relative_path}</code> · family <code>{detail.family_id}</code>
        {detail.groups.length ? <> · groups {detail.groups.join(" / ")}</> : null} ·{" "}
        {detail.environment_ok ? "environment ready" : "family environment not synced"}
      </p>
      <ErrorBox error={error} />
      {detail.validation.errors.map((message) => (
        <div className="error-box" key={message}>
          {message}
        </div>
      ))}
      {detail.validation.warnings.map((message) => (
        <div className="warn-box" key={message}>
          {message}
        </div>
      ))}
      {detail.problems.map((message) => (
        <div className="warn-box" key={message}>
          {message}
        </div>
      ))}

      {animation && (
        <section className="cards" style={{ marginTop: 16 }}>
          <div className="card">
            <h3>Brief</h3>
            <p>{animation.objective}</p>
            {animation.audience && (
              <p className="meta">
                audience: <code>{animation.audience}</code>
              </p>
            )}
          </div>
          <div className="card">
            <h3>Output and style</h3>
            <p>
              {animation.output.width_px}×{animation.output.height_px} at {animation.output.fps} fps,{" "}
              {animation.output.duration_seconds} s ({animation.output.aspect_ratio})
            </p>
            <p className="meta">
              style <code>{animation.style.name}@{animation.style.version}</code>
              {detail.style ? (
                <>
                  {" "}
                  → resolved <code>{detail.style.theme}@{detail.style.version}</code>, hash{" "}
                  <code>{detail.style.hash.slice(7, 19)}</code>
                </>
              ) : null}
            </p>
          </div>
          <div className="card">
            <h3>Sources</h3>
            {animation.sources.length === 0 ? (
              <Empty>none</Empty>
            ) : (
              <table>
                <tbody>
                  {animation.sources.map((s) => (
                    <tr key={s.id}>
                      <td>
                        <code>{s.id}</code>
                      </td>
                      <td>{s.type}</td>
                      <td>{s.role.replace("_", " ")}</td>
                      <td className="meta">{s.citation ?? s.path}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
          <div className="card">
            <h3>Equations</h3>
            {animation.equations.length === 0 ? (
              <Empty>none</Empty>
            ) : (
              animation.equations.map((e) => (
                <div key={e.id} style={{ marginBottom: 8 }}>
                  <code>{e.id}</code>
                  <pre style={{ margin: "4px 0" }}>{e.typst ?? e.latex}</pre>
                  <div className="meta">
                    {Object.entries(e.symbols)
                      .map(([name, def]) => `${name}: ${def.meaning}${def.units ? ` (${def.units})` : ""}`)
                      .join(" · ")}
                  </div>
                </div>
              ))
            )}
          </div>
          {animation.scientific_constraints.length > 0 && (
            <div className="card">
              <h3>Scientific constraints</h3>
              <ul style={{ margin: 0, paddingLeft: 18 }}>
                {animation.scientific_constraints.map((c) => (
                  <li key={c.id}>
                    <code>{c.id}</code> ({c.kind}) {c.text}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </section>
      )}

      <h2>Storyboard</h2>
      {storyboard ? (
        <table>
          <thead>
            <tr>
              <th>scene</th>
              <th>time</th>
              <th>purpose and narration</th>
              <th>objects</th>
              <th>snapshots</th>
            </tr>
          </thead>
          <tbody>
            {storyboard.scenes.map((scene) => (
              <tr key={scene.id}>
                <td>
                  <code>{scene.id}</code>
                  {scene.title ? <div className="meta">{scene.title}</div> : null}
                </td>
                <td>
                  {scene.start_seconds}–{scene.end_seconds} s
                </td>
                <td>
                  {scene.purpose}
                  {scene.narration ? <div className="meta">“{scene.narration}”</div> : null}
                </td>
                <td>
                  {scene.objects.map((o) => (
                    <div key={o.id}>
                      <code>{o.id}</code> <span className="meta">{o.kind}</span>
                      {o.reveal_at_seconds != null ? <span className="meta"> at {o.reveal_at_seconds} s</span> : null}
                    </div>
                  ))}
                </td>
                <td>
                  {scene.snapshots.map((s) => (
                    <div key={s.id}>
                      {latest ? (
                        <a href={`#${routes.review(id, latest)}?snapshot=${s.id}`}>
                          <code>{s.id}</code>
                        </a>
                      ) : (
                        <code>{s.id}</code>
                      )}
                      <span className="meta"> at {s.at_seconds} s: {s.description}</span>
                    </div>
                  ))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <Empty>No storyboard yet.</Empty>
      )}

      <h2>Render</h2>
      <div className="toolbar">
        <label>
          revision{" "}
          <select value={revision} onChange={(e) => setRevision(e.target.value)} data-testid="render-revision">
            <option value="working">working copy</option>
            {detail.revisions.map((r) => (
              <option key={r.id} value={r.id}>
                {r.id}: {r.message}
              </option>
            ))}
          </select>
        </label>
        <label>
          profile{" "}
          <select value={profile} onChange={(e) => setProfile(e.target.value)}>
            {PROFILES.map((p) => (
              <option key={p}>{p}</option>
            ))}
          </select>
        </label>
        <label>
          <input type="checkbox" checked={noCache} onChange={(e) => setNoCache(e.target.checked)} /> ignore cache
        </label>
        <button className="primary" onClick={() => render()} disabled={submitting || !detail.environment_ok} data-testid="render-all">
          Render all snapshots
        </button>
        <button onClick={() => render("render_video", "draft")} disabled={submitting || !detail.environment_ok} data-testid="render-draft">
          Render draft video
        </button>
        <button onClick={() => render("render_video", "final")} disabled={submitting || !detail.environment_ok} data-testid="render-final">
          Render final video
        </button>
        {latest ? (
          <a href={`#${routes.review(id, latest)}`} data-testid="open-latest">
            open the latest snapshots of {revision}
          </a>
        ) : (
          <span className="meta">no succeeded snapshot render of {revision} yet</span>
        )}
        {detail.latest_video[revision] ? (
          <a href={`#${routes.video(id, detail.latest_video[revision])}`} data-testid="open-latest-video">
            open the latest video of {revision}
          </a>
        ) : null}
      </div>

      <h2>Revisions</h2>
      {detail.revisions.length === 0 ? (
        <Empty>
          None yet; freeze the working copy with <code>scianim revision create</code>. Approvals need a frozen revision.
        </Empty>
      ) : (
        <table>
          <thead>
            <tr>
              <th>revision</th>
              <th>created</th>
              <th>parent</th>
              <th>style</th>
              <th>message</th>
              <th>latest render</th>
            </tr>
          </thead>
          <tbody>
            {detail.revisions.map((r) => (
              <tr key={r.id}>
                <td>
                  <code>{r.id}</code>
                </td>
                <td>{formatTime(r.created_at)}</td>
                <td>{r.parent ?? "–"}</td>
                <td>
                  {r.style_theme}@{r.style_version}
                </td>
                <td>{r.message}</td>
                <td>
                  {detail.latest_render[r.id] ? (
                    <a href={`#${routes.review(id, detail.latest_render[r.id])}`}>{detail.latest_render[r.id]}</a>
                  ) : (
                    <span className="meta">none</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <h2>Recent jobs</h2>
      {detail.jobs.length === 0 ? (
        <Empty>No jobs yet.</Empty>
      ) : (
        <table>
          <thead>
            <tr>
              <th>job</th>
              <th>revision</th>
              <th>kind</th>
              <th>status</th>
              <th>checkpoints</th>
              <th>elapsed</th>
              <th>created</th>
              <th>by</th>
            </tr>
          </thead>
          <tbody>
            {detail.jobs.map((job) => (
              <tr key={job.job_id} data-testid={`job-${job.job_id}`}>
                <td>
                  {job.status === "succeeded" ? (
                    <a href={`#${job.operation === "render_video" ? routes.video(id, job.job_id) : routes.review(id, job.job_id)}`}>
                      <code>{job.job_id}</code>
                    </a>
                  ) : (
                    <code>{job.job_id}</code>
                  )}
                </td>
                <td>{job.revision_id}</td>
                <td>{job.operation === "render_video" ? `${job.profile} video` : "snapshots"}</td>
                <td>
                  <StatusChip status={job.status} />
                  {job.cache_hit ? <span className="meta"> cache hit</span> : null}
                  {job.error ? <div className="meta">{job.error.slice(0, 160)}</div> : null}
                </td>
                <td>{job.checkpoint_count}</td>
                <td>{seconds(job.elapsed_seconds)}</td>
                <td>{formatTime(job.created_at)}</td>
                <td>{job.submitted_by}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
