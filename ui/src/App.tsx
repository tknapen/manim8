import { useCallback, useEffect, useState } from "react";

import { api, type Workspace } from "./api";
import { navigate, routes, useRoute, type Route } from "./router";
import { Empty, ErrorBox } from "./ui";
import Compare from "./views/Compare";
import Jobs from "./views/Jobs";
import Overview from "./views/Overview";
import Review from "./views/Review";

export default function App() {
  const route = useRoute();
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(() => {
    api
      .workspace()
      .then((ws) => {
        setWorkspace(ws);
        setError(null);
      })
      .catch((e: Error) => setError(e.message));
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  const projectId = route.parts[0] === "p" ? route.parts[1] : undefined;

  return (
    <div className="app">
      <header className="topbar">
        <a className="brand" href="#/">
          SciAnim <span>Studio</span>
        </a>
        <span className="root" title="workspace root">
          {workspace?.root ?? ""}
        </span>
        <span className="meta" style={{ marginLeft: "auto" }}>
          {workspace ? `scianim ${workspace.version}` : "connecting"}
        </span>
      </header>
      <nav className="sidebar" aria-label="workspace">
        {workspace?.families.map((family) => (
          <div key={family.id}>
            <div className="family" title={family.relative_path}>
              {family.id}
              {family.environment_ok ? "" : " · no env"}
            </div>
            {workspace.projects
              .filter((p) => p.family_id === family.id)
              .map((p) => (
                <a
                  key={p.id}
                  className={`project${p.id === projectId ? " active" : ""}`}
                  href={`#${routes.project(p.id)}`}
                  data-testid={`project-${p.id}`}
                >
                  {p.title}
                  <small>
                    {p.id}
                    {p.groups.length ? ` · ${p.groups.join(" / ")}` : ""}
                  </small>
                </a>
              ))}
          </div>
        ))}
        {workspace?.problems.length ? (
          <div className="warn-box" style={{ margin: "12px 12px 0" }}>
            {workspace.problems.map((problem) => (
              <div key={problem}>{problem}</div>
            ))}
          </div>
        ) : null}
      </nav>
      <main className="main">
        <ErrorBox error={error} />
        {projectId ? <ProjectShell id={projectId} route={route} /> : <Welcome workspace={workspace} />}
      </main>
    </div>
  );
}

function Welcome({ workspace }: { workspace: Workspace | null }) {
  return (
    <div>
      <h1>Review</h1>
      <p className="meta">
        Pick a project. Every image here is labelled with its kind; a Manim checkpoint is a frame captured from the real
        animation flow, nothing else is.
      </p>
      {workspace && workspace.projects.length === 0 ? (
        <Empty>No projects in this workspace yet. Create one with `scianim project init`.</Empty>
      ) : null}
    </div>
  );
}

function ProjectShell({ id, route }: { id: string; route: Route }) {
  const view = route.parts[2] ?? "overview";
  const jobId = route.parts[3];
  const tabs: [string, string, string][] = [
    ["overview", "Overview", routes.project(id)],
    ["review", "Review", jobId ? routes.review(id, jobId) : `${routes.project(id)}/review`],
    ["compare", "Compare", routes.compare(id)],
    ["jobs", "Jobs", routes.jobs(id)],
  ];
  return (
    <div>
      <nav className="subnav">
        {tabs.map(([key, label, href]) => (
          <a key={key} className={view === key ? "active" : ""} href={`#${href}`} data-testid={`tab-${key}`}>
            {label}
          </a>
        ))}
      </nav>
      {view === "overview" && <Overview id={id} />}
      {view === "review" && <Review id={id} jobId={jobId} snapshotId={route.query.get("snapshot") ?? undefined} />}
      {view === "compare" && <Compare id={id} a={route.query.get("a") ?? undefined} b={route.query.get("b") ?? undefined} />}
      {view === "jobs" && <Jobs id={id} />}
      {!["overview", "review", "compare", "jobs"].includes(view) && (
        <Empty>
          Unknown view. <a onClick={() => navigate(routes.project(id))}>Back to the overview.</a>
        </Empty>
      )}
    </div>
  );
}
