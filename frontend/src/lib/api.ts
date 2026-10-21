/** Thin API client. All analytical numbers come from the backend; this file only moves JSON. */
import type { Filters } from "./filters";
import { filtersToParams } from "./filters";

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

export type Params = Record<string, string | number | boolean | null | undefined | (string | number)[]>;

const BACKEND_DOWN = "Cannot reach the RestaurantIQ backend. Make sure it is running on 127.0.0.1:8010.";

export function buildQuery(params: Params = {}): string {
  const usp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    if (Array.isArray(v)) v.forEach((item) => usp.append(k, String(item)));
    else usp.append(k, String(v));
  }
  const s = usp.toString();
  return s ? `?${s}` : "";
}

async function parseError(res: Response): Promise<ApiError> {
  let message = `The server returned an error (${res.status}).`;
  try {
    const body = await res.json();
    if (body && typeof body.error === "string") message = body.error;
  } catch {
    // Vite's proxy answers 500/502/504 without a JSON body when the backend is down.
    if ([500, 502, 503, 504].includes(res.status)) message = BACKEND_DOWN;
  }
  return new ApiError(message, res.status);
}

export async function api<T>(path: string, opts: { params?: Params; method?: string; body?: unknown } = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`/api${path}${buildQuery(opts.params)}`, {
      method: opts.method ?? "GET",
      headers: opts.body !== undefined ? { "Content-Type": "application/json" } : undefined,
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    });
  } catch {
    throw new ApiError(BACKEND_DOWN, 0);
  }
  if (!res.ok) throw await parseError(res);
  try {
    return (await res.json()) as T;
  } catch {
    throw new ApiError("The server sent a response the app could not read. Please retry.", res.status);
  }
}

/** Fetch a binary response (PDF / ZIP / CSV) and save it, surfacing friendly errors. */
export async function downloadFile(path: string, opts: { params?: Params; method?: string; body?: unknown } = {},
                                   fallbackName = "download"): Promise<string> {
  let res: Response;
  try {
    res = await fetch(`/api${path}${buildQuery(opts.params)}`, {
      method: opts.method ?? "GET",
      headers: opts.body !== undefined ? { "Content-Type": "application/json" } : undefined,
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    });
  } catch {
    throw new ApiError(BACKEND_DOWN, 0);
  }
  if (!res.ok) throw await parseError(res);
  const blob = await res.blob();
  const disposition = res.headers.get("Content-Disposition") ?? "";
  const name = /filename="?([^"]+)"?/.exec(disposition)?.[1] ?? fallbackName;
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  return name;
}

/** Parameters shared by every analytical request: dataset version + active filters. */
export function analysisParams(datasetId: string | undefined, filters: Filters, extra: Params = {}): Params {
  return { dataset_id: datasetId, ...filtersToParams(filters), ...extra };
}

/** Upload with real byte progress (XMLHttpRequest exposes upload progress; fetch does not). */
export function uploadFile<T>(file: File, onProgress: (fraction: number) => void, signal?: AbortSignal): Promise<T> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/uploads");
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(e.loaded / e.total);
    };
    xhr.onload = () => {
      let body: unknown = null;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        /* handled below */
      }
      if (xhr.status >= 200 && xhr.status < 300 && body) {
        resolve(body as T);
        return;
      }
      const err = body && typeof (body as { error?: unknown }).error === "string" ? (body as { error: string }).error : null;
      const msg = err
        ?? (xhr.status === 413
          ? "The upload was rejected by a server or proxy body-size limit (not by RestaurantIQ). Increase that limit or split the file."
          : `Upload failed (${xhr.status || "network error"}). Make sure the backend is running.`);
      reject(new ApiError(msg, xhr.status));
    };
    xhr.onerror = () => reject(new ApiError("The upload was interrupted. Check that the backend is running and try again.", 0));
    xhr.onabort = () => reject(new ApiError("Upload cancelled.", 0));
    signal?.addEventListener("abort", () => xhr.abort());
    const form = new FormData();
    form.append("file", file);
    xhr.send(form);
  });
}

export function downloadUrl(path: string, params: Params = {}): string {
  return `/api${path}${buildQuery(params)}`;
}
