/**
 * Fetch wrapper for the IRIS API (`src/iris/api/*`).
 *
 * Base URL comes from `VITE_API_BASE_URL` (see `frontend/.env.example`). All
 * shapes below mirror the FastAPI route/response models exactly as read from
 * `routes_auth.py`, `routes_detections.py` and `routes_admin.py` — do not
 * "improve" field names here without re-checking those files.
 */

const API_BASE_URL: string = (
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "http://localhost:8000"
).replace(/\/+$/, "");

/** The six severities known to the backend (`iris.models.SEVERITY_ORDER`). */
export const SEVERITY_LEVELS = [
  "none",
  "info",
  "low",
  "medium",
  "high",
  "critical",
] as const;

export type SeverityLevel = (typeof SEVERITY_LEVELS)[number];

/** The model's own independent criticality colors (`iris.alibaba._CRITICALITY_COLORS`). */
export const CRITICALITY_COLORS = ["verde", "amarillo", "naranja", "rojo"] as const;
export type CriticalityColor = (typeof CRITICALITY_COLORS)[number];

/** Fields the history view can sort by (mirrors `_SORT_FIELDS` in `routes_detections.py`). */
export const DETECTION_SORT_FIELDS = ["captured_at", "camera_id", "criticidad"] as const;
export type DetectionSortField = (typeof DETECTION_SORT_FIELDS)[number];

/** The only two roles the backend knows about. */
export const ROLES = ["normal", "admin"] as const;
export type Role = (typeof ROLES)[number];

// ---------------------------------------------------------------------------
// Response / request shapes
// ---------------------------------------------------------------------------

export interface LoginResponse {
  access_token: string;
  token_type: string;
  username: string;
  role: string;
}

export interface MeResponse {
  username: string;
  role: string;
}

/** Mirrors `_project_document()` in `routes_detections.py`. */
export interface Detection {
  id: string;
  event_type: string | null;
  camera_id: string | null;
  camera_name: string | null;
  captured_at: string | null;
  completed_at: string | null;
  trigger: string | null;
  risk_score: number | null;
  severity: string | null;
  alert: boolean | null;
  event: string | null;
  summary: string | null;
  confidence: number | null;
  recommended_action: string | null;
  /** Model's own independent color judgment: "verde" | "amarillo" | "naranja" | "rojo". */
  criticidad: string | null;
  has_image: boolean;
}

export interface DetectionsPage {
  items: Detection[];
  total: number;
  page: number;
  page_size: number;
}

export interface DetectionsListParams {
  date_from?: string;
  date_to?: string;
  camera_id?: string;
  severity?: string;
  criticidad?: string;
  sort_by?: DetectionSortField;
  sort_order?: "asc" | "desc";
  page?: number;
  page_size?: number;
}

export interface AdminUserRecord {
  id: number;
  username: string;
  role: string;
  is_active: boolean;
  created_at: string;
}

export interface CreateUserPayload {
  username: string;
  password: string;
  role: string;
}

export interface UpdateUserPayload {
  role?: string;
  is_active?: boolean;
}

export interface SettingsResponse {
  revision: number;
  frame_width: number;
  frame_height: number;
  max_api_calls_per_minute: number;
  jpeg_quality: number;
  save_image_min_severity: string;
  /** 0 disables variation gating: every fresh frame is always analyzed. */
  change_threshold_percent: number;
  /** Master switch, independent from whether the bot/chat are configured. */
  telegram_enabled: boolean;
  /** Read-only: whether both Telegram credentials are configured. */
  telegram_configured: boolean;
  telegram_bot_token_configured: boolean;
  telegram_chat_id: string | null;
  telegram_dedup_cooldown_seconds: number;
  history_chat_enabled: boolean;
  openai_api_key_configured: boolean;
  history_chat_model: string;
  history_chat_max_range_days: number;
  alibaba_api_key_configured: boolean;
  alibaba_base_url: string;
  alibaba_model: string;
  alibaba_timeout_seconds: number;
  alibaba_max_retries: number;
  alibaba_max_completion_tokens: number;
}

/** Mirrors `SettingsUpdateRequest`. */
export type UpdateSettingsPayload = Partial<
  Omit<
    SettingsResponse,
    | "alibaba_api_key_configured"
    | "telegram_configured"
    | "telegram_bot_token_configured"
    | "openai_api_key_configured"
  >
> & {
  /** Write-only. Omit or send an empty value to preserve the configured key. */
  alibaba_api_key?: string;
  /** Write-only. Omit or send an empty value to preserve the configured token. */
  telegram_bot_token?: string;
  /** Write-only. Omit or send an empty value to preserve the configured key. */
  openai_api_key?: string;
};

export interface ChatConfigResponse {
  enabled: boolean;
  configured: boolean;
  model: string;
  max_range_days: number;
  cameras: Array<{ id: string; name: string }>;
}

export interface ChatThread {
  id: string;
  username: string;
  camera_id: string;
  camera_name: string;
  date_from: string;
  date_to: string;
  created_at: string;
  updated_at: string;
}

export interface ChatMessage {
  id: number;
  thread_id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
}

export interface ChatThreadDetail {
  thread: ChatThread;
  messages: ChatMessage[];
}

export interface ChatQueryPayload {
  camera_id: string;
  date_from: string;
  date_to: string;
  question: string;
  language: "es" | "en";
  thread_id?: string;
}

export interface ChatQueryResponse {
  thread_id: string;
  answer: string;
  source_count: number;
  group_count: number;
}

export interface TelegramTestResponse {
  sent: boolean;
  with_image: boolean;
  attempts: number;
  detail: string;
}

export interface MonitorRestartResponse {
  requested: boolean;
  revision: number;
  detail: string;
}

/**
 * Mirrors `CameraResponse` / `_camera_response()` in `routes_admin.py`.
 * The API returns the complete RTSP URL so an admin can inspect and edit it.
 */
export interface AdminCameraRecord {
  index: number;
  id: string;
  name: string;
  rtsp_url: string;
  prompt: string;
  poll_interval_seconds: number;
  /** Minimum severity/risk band required to notify this camera. */
  notification_threshold: string;
  notifications_enabled: boolean;
}

/** Per-camera configuration includes its own polling interval. */
export interface CreateCameraPayload {
  name: string;
  rtsp_url: string;
  prompt: string;
  poll_interval_seconds: number;
  notification_threshold?: string;
  notifications_enabled?: boolean;
}

/** Mirrors `UpdateCameraRequest`. Only send the fields being changed; omitted fields are left untouched. */
export interface UpdateCameraPayload {
  name?: string;
  rtsp_url?: string;
  prompt?: string;
  poll_interval_seconds?: number;
  notification_threshold?: string;
  notifications_enabled?: boolean;
}

/** Non-secret runtime settings returned with the monitoring dashboard. */
export interface DashboardSettings {
  frame_width: number;
  frame_height: number;
  max_api_calls_per_minute: number;
}

export interface DashboardAnalysis {
  severity?: string | null;
  alert?: boolean | null;
  event?: string | null;
  summary?: string | null;
  confidence?: number | null;
  /** Operational urgency estimate. Independent from model confidence. */
  risk_score?: number | null;
  observations?: string[] | null;
  recommended_action?: string | null;
  requires_human_review?: boolean | null;
  /** Model's own independent color judgment: "verde" | "amarillo" | "naranja" | "rojo". */
  criticidad?: string | null;
}

export interface DashboardEvent {
  id: string;
  /** Stable UUID for new SQLite-backed events; null for legacy Mongo rows. */
  event_id: string | null;
  event_type: string | null;
  captured_at: string | null;
  completed_at: string | null;
  trigger: string | null;
  analysis: DashboardAnalysis | null;
  created_at: string | null;
}

export interface DashboardCamera {
  camera_id: string;
  index: number;
  name: string;
  poll_interval_seconds: number;
  status: "online" | "offline" | "waiting" | "unknown";
  last_event: DashboardEvent | null;
  latest_capture_url: string | null;
  latest_capture_at: string | null;
  latest_analysis_status: "completed" | "failed" | "pending" | "none" | "unavailable";
  latest_analysis_at: string | null;
}

export interface DashboardResponse {
  revision: number;
  settings: DashboardSettings;
  cameras: DashboardCamera[];
}

// ---------------------------------------------------------------------------
// Low-level request plumbing
// ---------------------------------------------------------------------------

/** Raised for any non-2xx response; `message` is the backend's own detail text. */
export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

let authToken: string | null = null;

/** Called by AuthContext whenever the session token changes (login/logout/rehydrate). */
export function setAuthToken(token: string | null): void {
  authToken = token;
}

let unauthorizedHandler: (() => void) | null = null;

/**
 * Called by AuthContext to react to ANY 401 from ANY request, not just the
 * initial /auth/me check on load — a token that goes stale mid-session
 * (expiry, revocation) must also force a clean logout instead of leaving the
 * backend's raw "Token inválido o expirado." text sitting in a page's error banner.
 */
export function setUnauthorizedHandler(handler: (() => void) | null): void {
  unauthorizedHandler = handler;
}

function authHeaders(): Record<string, string> {
  return authToken ? { Authorization: `Bearer ${authToken}` } : {};
}

type QueryValue = string | number | boolean | undefined;

function buildUrl(path: string, query?: Record<string, QueryValue>): string {
  const url = new URL(`${API_BASE_URL}${path}`);
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== "") {
        url.searchParams.set(key, String(value));
      }
    }
  }
  return url.toString();
}

/** FastAPI error bodies are `{"detail": "..."}` or, for 422s, `{"detail": [...]}`. */
async function extractErrorMessage(response: Response): Promise<string> {
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    return response.statusText || `HTTP ${response.status}`;
  }
  const detail = (payload as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const messages = detail.map((item) =>
      typeof item === "object" && item !== null && "msg" in item
        ? String((item as { msg: unknown }).msg)
        : JSON.stringify(item),
    );
    return messages.join("; ");
  }
  if (detail !== undefined) return JSON.stringify(detail);
  return response.statusText || `HTTP ${response.status}`;
}

interface RequestOptions {
  method?: string;
  query?: Record<string, QueryValue>;
  body?: unknown;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = { ...authHeaders() };
  let body: string | undefined;
  if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(options.body);
  }

  const response = await fetch(buildUrl(path, options.query), {
    method: options.method ?? "GET",
    headers,
    body,
  });

  if (!response.ok) {
    if (response.status === 401) unauthorizedHandler?.();
    throw new ApiError(response.status, await extractErrorMessage(response));
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

/**
 * Fetches `/detections/{id}/image` as a Blob. `<img src>` can't attach an
 * Authorization header, so callers turn this into an object URL themselves
 * (see `components/DetectionThumbnail.tsx`).
 */
export async function fetchDetectionImageBlob(id: string): Promise<Blob> {
  const response = await fetch(buildUrl(`/detections/${encodeURIComponent(id)}/image`), {
    headers: authHeaders(),
  });
  if (!response.ok) {
    if (response.status === 401) unauthorizedHandler?.();
    throw new ApiError(response.status, await extractErrorMessage(response));
  }
  return response.blob();
}

/**
 * Fetches `/cameras/{cameraId}/latest-frame` as a Blob — the last frame IRIS
 * actually sent to the vision model for this camera, independent of Mongo
 * and of the severity-gated detection history (see `routes_cameras.py`).
 * Same "blob + object URL" pattern as `fetchDetectionImageBlob` above, for
 * the same reason: `<img src>` can't attach an Authorization header.
 *
 * A 404 here is a normal, expected state (camera hasn't completed an
 * analysis cycle yet) rather than a real error — callers should catch
 * `ApiError` and check `.status === 404` to render a neutral placeholder
 * instead of an error banner (see `components/CameraLivePreview.tsx`).
 */
export async function fetchCameraLatestFrameBlob(cameraId: string): Promise<Blob> {
  const response = await fetch(
    buildUrl(`/cameras/${encodeURIComponent(cameraId)}/latest-frame`),
    { headers: authHeaders() },
  );
  if (!response.ok) {
    if (response.status === 401) unauthorizedHandler?.();
    throw new ApiError(response.status, await extractErrorMessage(response));
  }
  return response.blob();
}

/** Fetches an authenticated capture URL returned by `/api/dashboard`. */
export async function fetchDashboardCaptureBlob(captureUrl: string): Promise<Blob> {
  const resolvedUrl = new URL(captureUrl, `${API_BASE_URL}/`).toString();
  const response = await fetch(resolvedUrl, {
    headers: authHeaders(),
    cache: "no-store",
  });
  if (!response.ok) {
    if (response.status === 401) unauthorizedHandler?.();
    throw new ApiError(response.status, await extractErrorMessage(response));
  }
  return response.blob();
}

// ---------------------------------------------------------------------------
// Endpoint helpers
// ---------------------------------------------------------------------------

export function login(username: string, password: string): Promise<LoginResponse> {
  return request<LoginResponse>("/auth/login", {
    method: "POST",
    body: { username, password },
  });
}

export function fetchMe(): Promise<MeResponse> {
  return request<MeResponse>("/auth/me");
}

export function fetchLatestDetections(limit = 20): Promise<Detection[]> {
  return request<Detection[]>("/detections/latest", { query: { limit } });
}

export function fetchDetections(params: DetectionsListParams): Promise<DetectionsPage> {
  return request<DetectionsPage>("/detections", { query: { ...params } });
}

/** Admin-only: removes a detection from the history. Does not delete its JPEG on disk. */
export function deleteDetection(id: string): Promise<void> {
  return request<void>(`/detections/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export function fetchAdminUsers(): Promise<AdminUserRecord[]> {
  return request<AdminUserRecord[]>("/admin/users");
}

export function createAdminUser(payload: CreateUserPayload): Promise<AdminUserRecord> {
  return request<AdminUserRecord>("/admin/users", { method: "POST", body: payload });
}

export function updateAdminUser(
  username: string,
  payload: UpdateUserPayload,
): Promise<AdminUserRecord> {
  return request<AdminUserRecord>(`/admin/users/${encodeURIComponent(username)}`, {
    method: "PATCH",
    body: payload,
  });
}

export function fetchSettings(): Promise<SettingsResponse> {
  return request<SettingsResponse>("/admin/settings");
}

export function updateSettings(payload: UpdateSettingsPayload): Promise<SettingsResponse> {
  return request<SettingsResponse>("/admin/settings", { method: "PATCH", body: payload });
}

export function testTelegramNotification(): Promise<TelegramTestResponse> {
  return request<TelegramTestResponse>("/admin/notifications/telegram/test", { method: "POST" });
}

export function restartMonitorConnections(): Promise<MonitorRestartResponse> {
  return request<MonitorRestartResponse>("/admin/monitor/restart", { method: "POST" });
}

export function fetchChatConfig(): Promise<ChatConfigResponse> {
  return request<ChatConfigResponse>("/chat/config");
}

export function fetchChatThreads(): Promise<ChatThread[]> {
  return request<ChatThread[]>("/chat/threads");
}

export function fetchChatThread(threadId: string): Promise<ChatThreadDetail> {
  return request<ChatThreadDetail>(`/chat/threads/${encodeURIComponent(threadId)}`);
}

export function queryHistoryChat(payload: ChatQueryPayload): Promise<ChatQueryResponse> {
  return request<ChatQueryResponse>("/chat/query", { method: "POST", body: payload });
}

export function fetchAdminCameras(): Promise<AdminCameraRecord[]> {
  return request<AdminCameraRecord[]>("/admin/cameras");
}

export function createAdminCamera(payload: CreateCameraPayload): Promise<AdminCameraRecord> {
  return request<AdminCameraRecord>("/admin/cameras", { method: "POST", body: payload });
}

export function updateAdminCamera(
  index: number,
  payload: UpdateCameraPayload,
): Promise<AdminCameraRecord> {
  return request<AdminCameraRecord>(`/admin/cameras/${index}`, { method: "PATCH", body: payload });
}

/** The backend returns the just-deleted camera's (redacted) record, not an empty 204. */
export function deleteAdminCamera(index: number): Promise<AdminCameraRecord> {
  return request<AdminCameraRecord>(`/admin/cameras/${index}`, { method: "DELETE" });
}

// ---------------------------------------------------------------------------
// Persisted RTSP pipeline + monitoring dashboard (`/api/*`)
// ---------------------------------------------------------------------------

export function fetchDashboard(): Promise<DashboardResponse> {
  return request<DashboardResponse>("/api/dashboard");
}
