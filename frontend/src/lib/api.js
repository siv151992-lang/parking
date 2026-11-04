// Thin fetch wrapper: adds the JWT, parses JSON, normalises errors.
const TOKEN_KEY = "sp_token";

export const getToken = () => {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
};
export const setToken = (t) => {
  try {
    t ? localStorage.setItem(TOKEN_KEY, t) : localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable */
  }
};

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

let onUnauthorized = () => {};
export const setUnauthorizedHandler = (fn) => (onUnauthorized = fn);

function qs(params) {
  if (!params) return "";
  const p = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") p.append(k, v);
  });
  const s = p.toString();
  return s ? `?${s}` : "";
}

export async function api(path, { method = "GET", body, params, raw = false } = {}) {
  const headers = {};
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  const isForm = typeof FormData !== "undefined" && body instanceof FormData;
  if (body !== undefined && !isForm) headers["Content-Type"] = "application/json";
  const payload = body === undefined ? undefined : isForm ? body : JSON.stringify(body);
  const res = await fetch(`${path}${qs(params)}`, { method, headers, body: payload });
  if (res.status === 401 && !path.endsWith("/auth/login")) {
    onUnauthorized();
  }
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const j = await res.json();
      msg = typeof j.detail === "string" ? j.detail : Array.isArray(j.detail) ? j.detail.map((d) => `${d.loc?.slice(-1)[0]}: ${d.msg}`).join(", ") : msg;
    } catch {
      /* not json */
    }
    throw new ApiError(msg || `HTTP ${res.status}`, res.status);
  }
  if (raw) return res;
  if (res.status === 204) return null;
  return res.json();
}

export const get = (path, params) => api(path, { params });
export const post = (path, body) => api(path, { method: "POST", body: body ?? {} });
export const put = (path, body) => api(path, { method: "PUT", body });
export const del = (path) => api(path, { method: "DELETE" });

// Authenticated URL for <img> tags (MJPEG streams, captured images).
export const authUrl = (path) => {
  if (!path) return null;
  const t = getToken();
  return `${path}${path.includes("?") ? "&" : "?"}token=${encodeURIComponent(t || "")}`;
};

export async function download(path, params, fallbackName) {
  const res = await api(path, { params, raw: true });
  const blob = await res.blob();
  const cd = res.headers.get("Content-Disposition") || "";
  const m = cd.match(/filename="?([^"]+)"?/);
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = m ? m[1] : fallbackName;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}

/** Upload one file as multipart/form-data (field name "file"). */
export function upload(path, file) {
  const fd = new FormData();
  fd.append("file", file);
  return api(path, { method: "POST", body: fd });
}
