// Typed client for the review API. Every call goes through fetch; nothing here executes code.

export type Project = {
  id: string;
  title: string;
  family_id: string;
  relative_path: string;
  groups: string[];
  has_storyboard: boolean;
  environment_ok: boolean;
};

export type Family = {
  id: string;
  relative_path: string;
  environment_ok: boolean;
  has_lockfile: boolean;
  projects: string[];
};

export type Workspace = {
  root: string;
  families: Family[];
  projects: Project[];
  problems: string[];
  version: string;
};

export type BBox = { x: number; y: number; width: number; height: number };

export type LayoutItem = {
  object_id: string;
  kind: string;
  bbox: BBox;
  text?: string | null;
  text_height_px?: number | null;
};

export type LayoutWarning = { code: string; object_ids: string[]; detail: string };

export type Checkpoint = {
  snapshot_id: string;
  scene_id: string;
  kind: "manim_checkpoint" | "sampled_video_frame" | "storyboard_schematic";
  png: string;
  width_px: number;
  height_px: number;
  sha256: string;
  animation_index: number;
  expected_time_seconds: number;
  renderer_time_seconds: number | null;
  fidelity: "exact" | "approximate";
  fidelity_note: string | null;
  layout: LayoutItem[];
  warnings: LayoutWarning[];
  url: string;
  description: string;
};

export type JobLifecycle = "queued" | "preparing" | "running" | "succeeded" | "failed" | "canceled";

export type VideoRecord = {
  path: string;
  width_px: number;
  height_px: number;
  fps: number;
  duration_seconds: number;
  frame_count: number | null;
  codec: string | null;
  sha256: string;
  url: string;
};

export type SectionRecord = {
  name: string;
  type: string;
  video: string | null;
  metadata: Record<string, unknown>;
  url: string | null;
};

export type SceneTiming = {
  scene_id: string;
  start_seconds: number;
  end_seconds: number;
  expected_frames: number;
  actual_frames: number | null;
  delta_frames: number | null;
};

export type TimingReport = {
  fps: number;
  tolerance_frames: number;
  expected_total_frames: number;
  actual_total_frames: number | null;
  actual_duration_seconds: number | null;
  scenes: SceneTiming[];
  notes: string[];
  within_tolerance: boolean;
  problems: string[];
};

export type Job = {
  job_id: string;
  revision_id: string;
  operation: string;
  profile: string;
  status: JobLifecycle;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  elapsed_seconds: number | null;
  cache_hit: boolean;
  checkpoint_count: number;
  manifest: string | null;
  error: string | null;
  submitted_by: string;
  snapshot_ids: string[];
  checkpoints: Checkpoint[];
  review_sheet_url?: string;
  manifest_url?: string;
  worker_warnings?: string[];
  pixel_width?: number;
  pixel_height?: number;
  videos?: VideoRecord[];
  sections?: SectionRecord[];
  subtitles_url?: string | null;
  timing?: TimingReport | null;
};

export type Revision = {
  id: string;
  created_at: string;
  parent: string | null;
  message: string;
  style_theme: string;
  style_version: string;
};

export type SceneObject = { id: string; kind: string; style_role: string | null; reveal_at_seconds: number | null };
export type Snapshot = { id: string; at_seconds: number; description: string; kind: string };
export type Scene = {
  id: string;
  title: string | null;
  start_seconds: number;
  end_seconds: number;
  purpose: string;
  narration: string | null;
  objects: SceneObject[];
  snapshots: Snapshot[];
};

export type ProjectDetail = {
  id: string;
  title: string;
  family_id: string;
  relative_path: string;
  groups: string[];
  environment_ok: boolean;
  validation: { ok: boolean; errors: string[]; warnings: string[]; notices: string[] };
  animation: {
    id: string;
    title: string;
    objective: string;
    audience: string | null;
    output: { duration_seconds: number; width_px: number; height_px: number; fps: number; aspect_ratio: string };
    style: { name: string; version: string };
    sources: { id: string; type: string; path: string; role: string; citation: string | null }[];
    equations: { id: string; typst: string | null; latex: string | null; symbols: Record<string, { meaning: string; units?: string | null }> }[];
    scientific_constraints: { id: string; kind: string; text: string; equation?: string | null }[];
    timeline: { id: string; at_seconds: number; kind: string; instruction: string }[];
  } | null;
  storyboard: { project_id: string; total_end_seconds: number; scenes: Scene[] } | null;
  style: { theme: string; version: string; hash: string; layers: string[] } | null;
  revisions: Revision[];
  jobs: Job[];
  counts: { revisions: number; jobs: number; feedback: number };
  latest_render: Record<string, string>;
  latest_video: Record<string, string>;
  problems: string[];
};

export type FeedbackKind = "region_comment" | "object_comment" | "general_comment" | "status";
export type Severity = "visual" | "scientific" | "timing" | "other";
export type ReviewStatus = "approved" | "needs_revision" | "scientific_concern";

export type Feedback = {
  id: string;
  created_at: string;
  author: string | null;
  project_id: string;
  revision_id: string;
  job_id: string | null;
  scene_id: string | null;
  snapshot_id: string | null;
  object_id: string | null;
  kind: FeedbackKind;
  region: BBox | null;
  text: string;
  severity: Severity;
  status: ReviewStatus | null;
  image_sha256: string | null;
  time_seconds: number | null;
};

export type FeedbackCreate = {
  revision_id: string;
  kind: FeedbackKind;
  text?: string;
  severity?: Severity;
  status?: ReviewStatus;
  snapshot_id?: string;
  scene_id?: string;
  object_id?: string;
  region?: BBox;
  job_id?: string;
  author?: string;
  time_seconds?: number;
};

export type ObjectChange = {
  object_id: string;
  kind: string;
  change: "moved" | "resized" | "text_changed" | "added" | "removed";
  detail: string;
  before: BBox | null;
  after: BBox | null;
};

export type Comparison = {
  a: { job_id: string; revision_id: string };
  b: { job_id: string; revision_id: string };
  snapshots: {
    snapshot_id: string;
    identical: boolean;
    pixel_diff_fraction: number | null;
    note: string | null;
    a: Checkpoint | null;
    b: Checkpoint | null;
    diff_url: string | null;
    changes: ObjectChange[];
  }[];
};

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, { ...init, headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) } });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    } catch {
      // keep the status text
    }
    throw new ApiError(response.status, detail);
  }
  if (response.headers.get("content-type")?.includes("application/json")) {
    return (await response.json()) as T;
  }
  return (await response.text()) as unknown as T;
}

export const api = {
  workspace: () => request<Workspace>("/api/workspace"),
  project: (id: string) => request<ProjectDetail>(`/api/projects/${id}`),
  jobs: (id: string) => request<Job[]>(`/api/projects/${id}/jobs`),
  job: (id: string, jobId: string) => request<Job>(`/api/projects/${id}/jobs/${jobId}`),
  jobLog: (id: string, jobId: string) => request<string>(`/api/projects/${id}/jobs/${jobId}/log`),
  submitJob: (
    id: string,
    body: { revision_id: string; snapshot_ids: string[]; profile: string; no_cache: boolean; operation?: string; samples?: Record<string, number> },
  ) => request<{ job_id: string; status: JobLifecycle }>(`/api/projects/${id}/jobs`, { method: "POST", body: JSON.stringify(body) }),
  cancelJob: (id: string, jobId: string) => request<{ status: JobLifecycle }>(`/api/projects/${id}/jobs/${jobId}/cancel`, { method: "POST" }),
  feedback: (id: string, params: Record<string, string | undefined>) => {
    const query = new URLSearchParams(Object.entries(params).filter((e): e is [string, string] => Boolean(e[1])));
    const suffix = query.toString() ? `?${query}` : "";
    return request<Feedback[]>(`/api/projects/${id}/feedback${suffix}`);
  },
  addFeedback: (id: string, body: FeedbackCreate) =>
    request<Feedback>(`/api/projects/${id}/feedback`, { method: "POST", body: JSON.stringify(body) }),
  compare: (id: string, a: string, b: string) =>
    request<Comparison>(`/api/projects/${id}/compare?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`),
};

export const ACTIVE: JobLifecycle[] = ["queued", "preparing", "running"];
export const isActive = (status: JobLifecycle) => ACTIVE.includes(status);
