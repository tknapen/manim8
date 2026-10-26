// A hash router: no dependency, works when the page is served from any path by FastAPI.

import { useEffect, useState } from "react";

export type Route = { parts: string[]; query: URLSearchParams };

function parse(hash: string): Route {
  const raw = hash.startsWith("#") ? hash.slice(1) : hash;
  const [path, search] = raw.split("?", 2);
  const parts = path.split("/").filter(Boolean);
  return { parts, query: new URLSearchParams(search ?? "") };
}

export function useRoute(): Route {
  const [route, setRoute] = useState<Route>(() => parse(window.location.hash));
  useEffect(() => {
    const onChange = () => setRoute(parse(window.location.hash));
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return route;
}

export function navigate(path: string, query?: Record<string, string | undefined>): void {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value) params.set(key, value);
  }
  const suffix = params.toString() ? `?${params}` : "";
  window.location.hash = `#${path}${suffix}`;
}

export const routes = {
  project: (id: string) => `/p/${id}`,
  review: (id: string, jobId: string) => `/p/${id}/review/${jobId}`,
  compare: (id: string) => `/p/${id}/compare`,
  jobs: (id: string) => `/p/${id}/jobs`,
};
