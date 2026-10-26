import { useCallback, useEffect, useState } from "react";

import { api, isActive, type Job } from "../api";
import { routes } from "../router";
import { Empty, ErrorBox, StatusChip, formatTime, seconds } from "../ui";

export default function Jobs({ id }: { id: string }) {
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [log, setLog] = useState<string>("");

  const load = useCallback(() => {
    api
      .jobs(id)
      .then((all) => {
        setJobs(all);
        setError(null);
      })
      .catch((e: Error) => setError(e.message));
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  const active = jobs?.some((job) => isActive(job.status)) ?? false;
  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(load, 2000);
    return () => window.clearInterval(timer);
  }, [active, load]);

  useEffect(() => {
    if (!selected) {
      setLog("");
      return;
    }
    api
      .jobLog(id, selected)
      .then(setLog)
      .catch((e: Error) => setLog(e.message));
  }, [id, selected, jobs]);

  async function cancel(jobId: string) {
    try {
      await api.cancelJob(id, jobId);
      load();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function retry(job: Job) {
    try {
      await api.submitJob(id, { revision_id: job.revision_id, snapshot_ids: job.snapshot_ids, profile: job.profile, no_cache: true });
      load();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  if (!jobs) return error ? <ErrorBox error={error} /> : <Empty>Loading…</Empty>;

  return (
    <div>
      <h1>Jobs</h1>
      <p className="meta">Each job runs the family worker in a separate process; the control plane never imports Manim.</p>
      <ErrorBox error={error} />
      {jobs.length === 0 ? <Empty>No jobs yet.</Empty> : null}
      <table>
        <thead>
          <tr>
            <th>job</th>
            <th>revision</th>
            <th>profile</th>
            <th>status</th>
            <th>checkpoints</th>
            <th>elapsed</th>
            <th>created</th>
            <th>by</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {jobs.map((job) => (
            <tr key={job.job_id} data-testid={`jobrow-${job.job_id}`}>
              <td>
                <a onClick={() => setSelected(job.job_id)} style={{ cursor: "pointer" }}>
                  <code>{job.job_id}</code>
                </a>
              </td>
              <td>{job.revision_id}</td>
              <td>{job.profile}</td>
              <td>
                <StatusChip status={job.status} />
                {job.cache_hit ? <span className="meta"> cache hit</span> : null}
                {job.error ? <div className="meta">{job.error.slice(0, 200)}</div> : null}
              </td>
              <td>{job.status === "succeeded" && job.checkpoint_count ? <a href={`#${routes.review(id, job.job_id)}`}>{job.checkpoint_count}</a> : job.checkpoint_count}</td>
              <td>{seconds(job.elapsed_seconds)}</td>
              <td>{formatTime(job.created_at)}</td>
              <td>{job.submitted_by}</td>
              <td>
                {isActive(job.status) ? (
                  <button className="danger" onClick={() => cancel(job.job_id)}>
                    cancel
                  </button>
                ) : (
                  <button onClick={() => retry(job)}>retry</button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {selected ? (
        <div style={{ marginTop: 16 }}>
          <h2>Worker log: {selected}</h2>
          <pre data-testid="job-log">{log || "(no log yet)"}</pre>
        </div>
      ) : null}
    </div>
  );
}
