import { useEffect, useState } from "react";

import { api, type Comparison, type Job } from "../api";
import { navigate, routes } from "../router";
import { Empty, ErrorBox, KindBadge, percent } from "../ui";

export default function Compare({ id, a, b }: { id: string; a?: string; b?: string }) {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [comparison, setComparison] = useState<Comparison | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api
      .jobs(id)
      .then((all) => setJobs(all.filter((job) => job.status === "succeeded" && job.checkpoint_count > 0)))
      .catch((e: Error) => setError(e.message));
  }, [id]);

  useEffect(() => {
    if (!a || !b) {
      setComparison(null);
      return;
    }
    setBusy(true);
    api
      .compare(id, a, b)
      .then((c) => {
        setComparison(c);
        setError(null);
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setBusy(false));
  }, [id, a, b]);

  const options = jobs.map((job) => (
    <option key={job.job_id} value={job.job_id}>
      {job.job_id} · {job.revision_id} · {job.checkpoint_count} checkpoints
    </option>
  ));

  return (
    <div>
      <h1>Compare two renders</h1>
      <p className="meta">Pixel differences beyond antialiasing noise are shown in red; layout changes come from the object bounding boxes.</p>
      <div className="toolbar">
        <label>
          A{" "}
          <select value={a ?? ""} onChange={(e) => navigate(routes.compare(id), { a: e.target.value, b })} data-testid="compare-a">
            <option value="">choose a job</option>
            {options}
          </select>
        </label>
        <label>
          B{" "}
          <select value={b ?? ""} onChange={(e) => navigate(routes.compare(id), { a, b: e.target.value })} data-testid="compare-b">
            <option value="">choose a job</option>
            {options}
          </select>
        </label>
        {jobs.length >= 2 && (!a || !b) ? (
          <button onClick={() => navigate(routes.compare(id), { a: jobs[1].job_id, b: jobs[0].job_id })}>latest two</button>
        ) : null}
        {busy ? <span className="meta">comparing…</span> : null}
      </div>
      <ErrorBox error={error} />
      {jobs.length < 2 && !comparison ? <Empty>Two succeeded renders are needed.</Empty> : null}
      {comparison?.snapshots.map((s) => (
        <section key={s.snapshot_id} data-testid={`compare-${s.snapshot_id}`}>
          <h2>
            {s.snapshot_id}{" "}
            <span className={`stat ${s.identical ? "identical" : "changed"}`}>
              {s.identical ? "identical" : s.pixel_diff_fraction != null ? `${percent(s.pixel_diff_fraction)} of pixels differ` : s.note}
            </span>
          </h2>
          <div className="compare-row">
            <div>
              {s.a ? <img src={s.a.url} alt={`${s.snapshot_id} in A`} /> : <Empty>not in A</Empty>}
              <div className="caption">
                A · {comparison.a.revision_id} {s.a ? <KindBadge kind={s.a.kind} /> : null}
              </div>
            </div>
            <div>
              {s.b ? <img src={s.b.url} alt={`${s.snapshot_id} in B`} /> : <Empty>not in B</Empty>}
              <div className="caption">
                B · {comparison.b.revision_id} {s.b ? <KindBadge kind={s.b.kind} /> : null}
              </div>
            </div>
            <div>
              {s.diff_url ? <img src={s.diff_url} alt={`${s.snapshot_id} difference`} /> : <Empty>{s.identical ? "no difference" : "no diff image"}</Empty>}
              <div className="caption">difference{s.note ? ` · ${s.note}` : ""}</div>
            </div>
          </div>
          <div className="changes">
            {s.changes.length === 0 ? (
              <span className="meta">no object moved, resized, appeared or disappeared</span>
            ) : (
              s.changes.map((c) => (
                <div key={`${c.object_id}-${c.change}`}>
                  <code>{c.object_id}</code> {c.change.replace("_", " ")} {c.detail ? <span className="meta">({c.detail})</span> : null}
                </div>
              ))
            )}
          </div>
        </section>
      ))}
    </div>
  );
}
