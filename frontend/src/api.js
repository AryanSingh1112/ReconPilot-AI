const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/+$/, "");

export const api = async (path, opts) => {
  const r = await fetch(`${API_BASE_URL}${path}`, opts);
  const contentType = r.headers.get("content-type") || "";
  if (!contentType.includes("application/json")) {
    throw new Error(
      `Expected JSON from the API but received ${contentType || "an unknown content type"} (${r.status}). Check VITE_API_BASE_URL.`,
    );
  }

  let j;
  try {
    j = await r.json();
  } catch {
    throw new Error(`The API returned invalid JSON (${r.status}).`);
  }
  if (!r.ok) {
    throw new Error(typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail || r.statusText));
  }
  return j;
};

export const apiArray = async (path, opts) => {
  const result = await api(path, opts);
  if (!Array.isArray(result)) {
    throw new Error(`Expected a list from ${path}. Check that the request reached the backend API.`);
  }
  return result;
};

export const post = (p, b) => api(p, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(b)
});