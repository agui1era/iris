import { useCallback, useEffect, useState, type FormEvent } from "react";

import {
  ApiError,
  createAdminCamera,
  createAdminUser,
  deleteAdminCamera,
  fetchAdminCameras,
  fetchAdminUsers,
  fetchSettings,
  ROLES,
  SEVERITY_LEVELS,
  updateAdminCamera,
  updateAdminUser,
  updateSettings,
  type AdminCameraRecord,
  type AdminUserRecord,
  type CreateCameraPayload,
  type SettingsResponse,
  type UpdateCameraPayload,
  type UpdateSettingsPayload,
} from "../api/client";
import { CameraLivePreview } from "../components/CameraLivePreview";
import { useLanguage } from "../i18n/useLanguage";

export function AdminPage() {
  const { locale, t } = useLanguage();
  const [users, setUsers] = useState<AdminUserRecord[]>([]);
  const [usersLoading, setUsersLoading] = useState(true);
  const [usersError, setUsersError] = useState<string | null>(null);
  const [pendingUsername, setPendingUsername] = useState<string | null>(null);

  const [newUsername, setNewUsername] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newRole, setNewRole] = useState<string>("normal");
  const [createError, setCreateError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const [settings, setSettings] = useState<SettingsResponse | null>(null);
  const [settingsLoading, setSettingsLoading] = useState(true);
  const [settingsError, setSettingsError] = useState<string | null>(null);
  const [savingSettings, setSavingSettings] = useState(false);
  const [settingsSaved, setSettingsSaved] = useState(false);
  const [alibabaApiKey, setAlibabaApiKey] = useState("");

  const [cameras, setCameras] = useState<AdminCameraRecord[]>([]);
  const [camerasLoading, setCamerasLoading] = useState(true);
  const [camerasError, setCamerasError] = useState<string | null>(null);
  const [pendingCameraIndex, setPendingCameraIndex] = useState<number | null>(null);

  const [newCameraName, setNewCameraName] = useState("");
  const [newCameraRtspUrl, setNewCameraRtspUrl] = useState("");
  const [newCameraPrompt, setNewCameraPrompt] = useState("");
  const [newCameraPollInterval, setNewCameraPollInterval] = useState("30");
  const [newCameraNotificationThreshold, setNewCameraNotificationThreshold] = useState("high");
  const [createCameraError, setCreateCameraError] = useState<string | null>(null);
  const [creatingCamera, setCreatingCamera] = useState(false);

  const [editingCameraIndex, setEditingCameraIndex] = useState<number | null>(null);
  const [editCameraName, setEditCameraName] = useState("");
  const [editCameraRtspUrl, setEditCameraRtspUrl] = useState("");
  const [editCameraPrompt, setEditCameraPrompt] = useState("");
  const [editCameraPollInterval, setEditCameraPollInterval] = useState("30");
  const [editCameraNotificationThreshold, setEditCameraNotificationThreshold] = useState("high");
  const [editCameraError, setEditCameraError] = useState<string | null>(null);
  const [savingCamera, setSavingCamera] = useState(false);

  const loadUsers = useCallback(async () => {
    setUsersLoading(true);
    try {
      const data = await fetchAdminUsers();
      setUsers(data);
      setUsersError(null);
    } catch (err) {
      setUsersError(err instanceof ApiError ? err.message : t("No se pudieron cargar los usuarios.", "Could not load users."));
    } finally {
      setUsersLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void loadUsers();
  }, [loadUsers]);

  const loadSettings = useCallback(async () => {
    setSettingsLoading(true);
    try {
      const data = await fetchSettings();
      setSettings(data);
      setAlibabaApiKey("");
      setSettingsError(null);
    } catch (err) {
      setSettingsError(
        err instanceof ApiError ? err.message : t("No se pudo cargar la configuración.", "Could not load settings."),
      );
    } finally {
      setSettingsLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void loadSettings();
  }, [loadSettings]);

  const updateSetting = <Key extends keyof SettingsResponse,>(
    key: Key,
    value: SettingsResponse[Key],
  ) => {
    setSettings((current) => (current ? { ...current, [key]: value } : current));
    setSettingsSaved(false);
  };

  const handleRoleChange = async (username: string, role: string) => {
    setPendingUsername(username);
    try {
      const updated = await updateAdminUser(username, { role });
      setUsers((prev) => prev.map((u) => (u.username === username ? updated : u)));
      setUsersError(null);
    } catch (err) {
      setUsersError(err instanceof ApiError ? err.message : t("No se pudo actualizar el rol.", "Could not update the role."));
    } finally {
      setPendingUsername(null);
    }
  };

  const handleToggleActive = async (target: AdminUserRecord) => {
    setPendingUsername(target.username);
    try {
      const updated = await updateAdminUser(target.username, { is_active: !target.is_active });
      setUsers((prev) => prev.map((u) => (u.username === target.username ? updated : u)));
      setUsersError(null);
    } catch (err) {
      setUsersError(err instanceof ApiError ? err.message : t("No se pudo actualizar el estado.", "Could not update the status."));
    } finally {
      setPendingUsername(null);
    }
  };

  const handleCreate = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setCreateError(null);
    setCreating(true);
    try {
      const created = await createAdminUser({
        username: newUsername,
        password: newPassword,
        role: newRole,
      });
      setUsers((prev) => [...prev, created]);
      setNewUsername("");
      setNewPassword("");
      setNewRole("normal");
    } catch (err) {
      setCreateError(err instanceof ApiError ? err.message : t("No se pudo crear el usuario.", "Could not create the user."));
    } finally {
      setCreating(false);
    }
  };

  const handleSettingsSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!settings) return;
    setSettingsError(null);
    setSavingSettings(true);
    setSettingsSaved(false);
    try {
      const payload: UpdateSettingsPayload = {
        revision: settings.revision,
        frame_width: settings.frame_width,
        frame_height: settings.frame_height,
        jpeg_quality: settings.jpeg_quality,
        max_api_calls_per_minute: settings.max_api_calls_per_minute,
        save_image_min_severity: settings.save_image_min_severity,
        change_threshold_percent: settings.change_threshold_percent,
        telegram_enabled: settings.telegram_enabled,
        alibaba_base_url: settings.alibaba_base_url,
        alibaba_model: settings.alibaba_model,
        alibaba_timeout_seconds: settings.alibaba_timeout_seconds,
        alibaba_max_retries: settings.alibaba_max_retries,
        alibaba_max_completion_tokens: settings.alibaba_max_completion_tokens,
      };
      if (alibabaApiKey.trim()) payload.alibaba_api_key = alibabaApiKey.trim();
      const updated = await updateSettings(payload);
      setSettings(updated);
      setAlibabaApiKey("");
      setSettingsSaved(true);
    } catch (err) {
      setSettingsError(
        err instanceof ApiError && err.status === 409
          ? t("La configuración cambió en otra sesión. Recarga los valores antes de volver a guardar.", "Settings changed in another session. Reload the values before saving again.")
          : err instanceof ApiError
            ? err.message
            : t("No se pudo guardar la configuración.", "Could not save settings."),
      );
    } finally {
      setSavingSettings(false);
    }
  };

  const loadCameras = useCallback(async () => {
    setCamerasLoading(true);
    try {
      const data = await fetchAdminCameras();
      setCameras(data);
      setCamerasError(null);
    } catch (err) {
      setCamerasError(
        err instanceof ApiError ? err.message : t("No se pudieron cargar las cámaras.", "Could not load cameras."),
      );
    } finally {
      setCamerasLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void loadCameras();
  }, [loadCameras]);

  const handleCreateCamera = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setCreateCameraError(null);
    setCreatingCamera(true);
    try {
      const payload: CreateCameraPayload = {
        name: newCameraName,
        rtsp_url: newCameraRtspUrl,
        prompt: newCameraPrompt,
        poll_interval_seconds: Number(newCameraPollInterval),
        notification_threshold: newCameraNotificationThreshold,
      };

      await createAdminCamera(payload);
      await loadCameras();
      setNewCameraName("");
      setNewCameraRtspUrl("");
      setNewCameraPrompt("");
      setNewCameraPollInterval("30");
      setNewCameraNotificationThreshold("high");
    } catch (err) {
      setCreateCameraError(err instanceof ApiError ? err.message : t("No se pudo crear la cámara.", "Could not create the camera."));
    } finally {
      setCreatingCamera(false);
    }
  };

  const handleEditCameraStart = (camera: AdminCameraRecord) => {
    setEditingCameraIndex(camera.index);
    setEditCameraName(camera.name);
    setEditCameraRtspUrl(camera.rtsp_url);
    setEditCameraPrompt(camera.prompt);
    setEditCameraPollInterval(String(camera.poll_interval_seconds));
    setEditCameraNotificationThreshold(camera.notification_threshold);
    setEditCameraError(null);
  };

  const handleEditCameraCancel = () => {
    setEditingCameraIndex(null);
    setEditCameraError(null);
  };

  const handleEditCameraSubmit = async (event: FormEvent<HTMLFormElement>, index: number) => {
    event.preventDefault();
    setEditCameraError(null);
    setSavingCamera(true);
    try {
      const payload: UpdateCameraPayload = {};
      if (editCameraName.trim() !== "") payload.name = editCameraName.trim();
      if (editCameraRtspUrl.trim() !== "") payload.rtsp_url = editCameraRtspUrl.trim();
      if (editCameraPrompt.trim() !== "") payload.prompt = editCameraPrompt;
      if (editCameraPollInterval.trim() !== "") {
        payload.poll_interval_seconds = Number(editCameraPollInterval);
      }
      payload.notification_threshold = editCameraNotificationThreshold;

      await updateAdminCamera(index, payload);
      await loadCameras();
      setEditingCameraIndex(null);
    } catch (err) {
      setEditCameraError(
        err instanceof ApiError ? err.message : t("No se pudo actualizar la cámara.", "Could not update the camera."),
      );
    } finally {
      setSavingCamera(false);
    }
  };

  const handleDeleteCamera = async (camera: AdminCameraRecord) => {
    if (
      !window.confirm(
        t(`¿Eliminar la cámara "${camera.name}" (${camera.id})? Esta acción no se puede deshacer.`, `Delete camera "${camera.name}" (${camera.id})? This action cannot be undone.`),
      )
    ) {
      return;
    }
    setPendingCameraIndex(camera.index);
    try {
      await deleteAdminCamera(camera.index);
      await loadCameras();
      setCamerasError(null);
    } catch (err) {
      setCamerasError(err instanceof ApiError ? err.message : t("No se pudo eliminar la cámara.", "Could not delete the camera."));
    } finally {
      setPendingCameraIndex(null);
    }
  };

  return (
    <div className="page">
      <div className="page-header">
        <h1>{t("Administración", "Administration")}</h1>
      </div>

      <section className="panel">
        <h2>{t("Usuarios", "Users")}</h2>
        {usersError && (
          <div className="alert alert-error" role="alert">
            {usersError}
          </div>
        )}

        {usersLoading ? (
          <p className="muted">{t("Cargando…", "Loading…")}</p>
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>{t("Usuario", "Username")}</th>
                  <th>{t("Rol", "Role")}</th>
                  <th>{t("Activo", "Active")}</th>
                  <th>{t("Creado", "Created")}</th>
                </tr>
              </thead>
              <tbody>
                {users.map((target) => {
                  const isPending = pendingUsername === target.username;
                  return (
                    <tr key={target.username}>
                      <td>{target.username}</td>
                      <td>
                        <select
                          value={target.role}
                          disabled={isPending}
                          onChange={(event) => void handleRoleChange(target.username, event.target.value)}
                        >
                          {ROLES.map((role) => (
                            <option key={role} value={role}>
                              {role === "admin" ? t("Administrador", "Administrator") : t("Normal", "Standard")}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td>
                        <button
                          type="button"
                          className={`btn btn-toggle ${target.is_active ? "is-active" : "is-inactive"}`}
                          disabled={isPending}
                          onClick={() => void handleToggleActive(target)}
                        >
                          {target.is_active ? t("Activo", "Active") : t("Inactivo", "Inactive")}
                        </button>
                      </td>
                      <td>{new Date(target.created_at).toLocaleString(locale)}</td>
                    </tr>
                  );
                })}
                {users.length === 0 && (
                  <tr>
                    <td colSpan={4} className="muted">
                      {t("No hay usuarios.", "There are no users.")}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}

        <form className="inline-form" onSubmit={(event) => void handleCreate(event)}>
          <h3>{t("Crear usuario", "Create user")}</h3>
          {createError && (
            <div className="alert alert-error" role="alert">
              {createError}
            </div>
          )}
          <div className="field-row">
            <label className="field">
              <span>{t("Usuario", "Username")}</span>
              <input value={newUsername} onChange={(event) => setNewUsername(event.target.value)} required />
            </label>
            <label className="field">
              <span>{t("Contraseña", "Password")}</span>
              <input
                type="password"
                value={newPassword}
                onChange={(event) => setNewPassword(event.target.value)}
                required
              />
            </label>
            <label className="field">
              <span>{t("Rol", "Role")}</span>
              <select value={newRole} onChange={(event) => setNewRole(event.target.value)}>
                {ROLES.map((role) => (
                  <option key={role} value={role}>
                    {role === "admin" ? t("Administrador", "Administrator") : t("Normal", "Standard")}
                  </option>
                ))}
              </select>
            </label>
            <button type="submit" className="btn btn-primary" disabled={creating}>
              {creating ? t("Creando…", "Creating…") : t("Crear", "Create")}
            </button>
          </div>
        </form>
      </section>

      <section className="panel">
        <h2>{t("Cámaras", "Cameras")}</h2>
        {camerasError && (
          <div className="alert alert-error" role="alert">
            {camerasError}
          </div>
        )}

        {camerasLoading ? (
          <p className="muted">{t("Cargando…", "Loading…")}</p>
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>{t("Cámara", "Camera")}</th>
                  <th>{t("Nombre", "Name")}</th>
                  <th>RTSP</th>
                  <th>Prompt</th>
                  <th>{t("Polling", "Polling")}</th>
                  <th>{t("Última captura", "Latest capture")}</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {cameras.map((camera) => {
                  const isEditing = editingCameraIndex === camera.index;
                  const isPending = pendingCameraIndex === camera.index;
                  return (
                    <tr key={camera.index}>
                      <td>
                        {camera.id} (#{camera.index})
                      </td>
                      {isEditing ? (
                        <td colSpan={6}>
                          <form
                            className="inline-edit-form"
                            onSubmit={(event) => void handleEditCameraSubmit(event, camera.index)}
                          >
                            {editCameraError && (
                              <div className="alert alert-error" role="alert">
                                {editCameraError}
                              </div>
                            )}
                            <div className="camera-edit-grid">
                              <label className="field">
                                <span>{t("Nombre", "Name")}</span>
                                <input
                                  value={editCameraName}
                                  onChange={(event) => setEditCameraName(event.target.value)}
                                />
                              </label>
                              <label className="field camera-edit-wide">
                                <span>{t("URL RTSP completa", "Full RTSP URL")}</span>
                                <input
                                  type="text"
                                  value={editCameraRtspUrl}
                                  onChange={(event) => setEditCameraRtspUrl(event.target.value)}
                                  autoComplete="off"
                                  spellCheck={false}
                                  required
                                />
                                <span className="field-hint">
                                  {t("Incluye usuario, contraseña, host, puerto y ruta del stream.", "Include the username, password, host, port, and stream path.")}
                                </span>
                              </label>
                              <label className="field camera-edit-wide">
                                <span>Prompt</span>
                                <textarea
                                  className="camera-prompt-input"
                                  value={editCameraPrompt}
                                  onChange={(event) => setEditCameraPrompt(event.target.value)}
                                  rows={6}
                                  required
                                />
                              </label>
                              <label className="field">
                                <span>{t("Polling de esta cámara", "Camera polling")}</span>
                                <div className="input-with-unit">
                                  <input
                                    type="number"
                                    min="10"
                                    step="1"
                                    value={editCameraPollInterval}
                                    onChange={(event) =>
                                      setEditCameraPollInterval(event.target.value)
                                    }
                                    required
                                  />
                                  <span>{t("seg", "sec")}</span>
                                </div>
                                <span className="field-hint">
                                  {t("RTSP se lee en paralelo; Alibaba procesa una solicitud global a la vez.", "RTSP is read in parallel; Alibaba processes one global request at a time.")}
                                </span>
                              </label>
                              <label className="field">
                                <span>{t("Umbral de notificación", "Notification threshold")}</span>
                                <select
                                  value={editCameraNotificationThreshold}
                                  onChange={(event) =>
                                    setEditCameraNotificationThreshold(event.target.value)
                                  }
                                >
                                  {SEVERITY_LEVELS.map((level) => (
                                    <option key={level} value={level}>
                                      {t(({ none: "Ninguna", info: "Info", low: "Baja", medium: "Media", high: "Alta", critical: "Crítica" } as const)[level], ({ none: "None", info: "Info", low: "Low", medium: "Medium", high: "High", critical: "Critical" } as const)[level])}
                                    </option>
                                  ))}
                                </select>
                                <span className="field-hint">
                                  {t("Severidad mínima para notificar (Telegram, próximamente). Por ahora sólo guarda el umbral.", "Minimum severity for notifications (Telegram, coming soon). For now, only the threshold is saved.")}
                                </span>
                              </label>
                              <div className="camera-edit-actions">
                                <button
                                  type="submit"
                                  className="btn btn-primary"
                                  disabled={savingCamera}
                                >
                                  {savingCamera ? t("Guardando…", "Saving…") : t("Guardar cámara", "Save camera")}
                                </button>
                                <button
                                  type="button"
                                  className="btn btn-ghost"
                                  disabled={savingCamera}
                                  onClick={handleEditCameraCancel}
                                >
                                  {t("Cancelar", "Cancel")}
                                </button>
                              </div>
                            </div>
                          </form>
                        </td>
                      ) : (
                        <>
                          <td>{camera.name}</td>
                          <td className="rtsp-cell"><code>{camera.rtsp_url}</code></td>
                          <td className="prompt-cell">{camera.prompt}</td>
                          <td>{camera.poll_interval_seconds}s</td>
                          <td>
                            <CameraLivePreview
                              cameraId={camera.id}
                              pollIntervalSeconds={camera.poll_interval_seconds}
                            />
                          </td>
                          <td>
                            <div className="row-actions">
                              <button
                                type="button"
                                className="btn"
                                disabled={isPending}
                                onClick={() => handleEditCameraStart(camera)}
                              >
                                {t("Editar", "Edit")}
                              </button>
                              <button
                                type="button"
                                className="btn btn-danger"
                                disabled={isPending}
                                onClick={() => void handleDeleteCamera(camera)}
                              >
                                {isPending ? t("Eliminando…", "Deleting…") : t("Eliminar", "Delete")}
                              </button>
                            </div>
                          </td>
                        </>
                      )}
                    </tr>
                  );
                })}
                {cameras.length === 0 && (
                  <tr>
                    <td colSpan={7} className="muted">
                      {t("No hay cámaras configuradas.", "No cameras are configured.")}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}

        <p className="muted">
          {t("La URL RTSP completa se muestra y se edita aquí. El polling se configura por cámara y no puede ser menor a 30 segundos.", "The full RTSP URL is displayed and edited here. Polling is configured per camera and cannot be less than 30 seconds.")}
        </p>
        <p className="muted">
          {t('"Última captura" muestra el frame más reciente que IRIS obtuvo para esa cámara, no un video en vivo. Su antigüedad depende del polling configurado en esa cámara y mostrará un diagnóstico mientras la fuente RTSP todavía no entregue imágenes.', '"Latest capture" shows the most recent frame IRIS obtained for that camera, not live video. Its age depends on the camera polling interval, and a diagnostic appears until the RTSP source delivers images.')}
        </p>

        <form className="inline-form" onSubmit={(event) => void handleCreateCamera(event)}>
          <h3>{t("Agregar cámara", "Add camera")}</h3>
          {createCameraError && (
            <div className="alert alert-error" role="alert">
              {createCameraError}
            </div>
          )}
          <div className="field-row">
            <label className="field">
              <span>{t("Nombre", "Name")}</span>
              <input
                value={newCameraName}
                onChange={(event) => setNewCameraName(event.target.value)}
                required
              />
            </label>
            <label className="field">
              <span>{t("Polling", "Polling")}</span>
              <div className="input-with-unit">
                <input
                  type="number"
                  min="10"
                  step="1"
                  value={newCameraPollInterval}
                  onChange={(event) => setNewCameraPollInterval(event.target.value)}
                  required
                />
                <span>{t("seg", "sec")}</span>
              </div>
              <span className="field-hint">
                {t("RTSP se lee en paralelo; Alibaba procesa una solicitud global a la vez.", "RTSP is read in parallel; Alibaba processes one global request at a time.")}
              </span>
            </label>
            <label className="field">
              <span>{t("Umbral de notificación", "Notification threshold")}</span>
              <select
                value={newCameraNotificationThreshold}
                onChange={(event) => setNewCameraNotificationThreshold(event.target.value)}
              >
                {SEVERITY_LEVELS.map((level) => (
                  <option key={level} value={level}>
                    {t(({ none: "Ninguna", info: "Info", low: "Baja", medium: "Media", high: "Alta", critical: "Crítica" } as const)[level], ({ none: "None", info: "Info", low: "Low", medium: "Medium", high: "High", critical: "Critical" } as const)[level])}
                  </option>
                ))}
              </select>
              <span className="field-hint">
                {t("Severidad mínima para notificar (Telegram, próximamente). Por ahora sólo guarda el umbral.", "Minimum severity for notifications (Telegram, coming soon). For now, only the threshold is saved.")}
              </span>
            </label>
          </div>
          <label className="field">
            <span>URL RTSP</span>
            <input
              type="text"
              value={newCameraRtspUrl}
              onChange={(event) => setNewCameraRtspUrl(event.target.value)}
              placeholder="rtsp://usuario:clave@host:554/stream"
              autoComplete="off"
              spellCheck={false}
              required
            />
            <span className="field-hint">
              {t("El usuario y la contraseña de la cámara van embebidos en la propia URL, con el formato rtsp://usuario:clave@host:554/stream — no hay un campo separado para credenciales.", "The camera username and password are embedded in the URL using the format rtsp://username:password@host:554/stream — there is no separate credentials field.")}
            </span>
          </label>
          <label className="field">
            <span>Prompt</span>
            <textarea
              className="camera-prompt-input"
              value={newCameraPrompt}
              onChange={(event) => setNewCameraPrompt(event.target.value)}
              rows={6}
              required
            />
          </label>

          <div>
            <button type="submit" className="btn btn-primary" disabled={creatingCamera}>
              {creatingCamera ? t("Creando…", "Creating…") : t("Crear", "Create")}
            </button>
          </div>
        </form>
      </section>

      <section className="panel analysis-settings-panel">
        <div className="settings-panel-heading">
          <div>
            <span className="eyebrow">{t("CONFIGURACIÓN PERSISTENTE", "PERSISTENT SETTINGS")}</span>
            <h2>{t("Motor de análisis", "Analysis engine")}</h2>
            <p>
              {t("Controla resolución, capacidad de análisis y conexión con Alibaba.", "Control resolution, analysis capacity, and the Alibaba connection.")}
            </p>
          </div>
          {settings && <span className="revision-badge">{t("REVISIÓN", "REVISION")} {settings.revision}</span>}
        </div>

        {settingsError && (
          <div className="alert alert-error settings-error" role="alert">
            <span>{settingsError}</span>
            <button type="button" className="btn btn-ghost" onClick={() => void loadSettings()}>
              {t("Recargar valores", "Reload values")}
            </button>
          </div>
        )}

        {settingsLoading ? (
          <div className="settings-loading" aria-label={t("Cargando configuración", "Loading settings")}>
            <span />
            <span />
            <span />
          </div>
        ) : settings ? (
          <form
            className="analysis-settings-form"
            onSubmit={(event) => void handleSettingsSubmit(event)}
          >
            <div className="settings-groups">
              <fieldset className="settings-group">
                <legend>{t("Captura general", "General capture")}</legend>
                <p>{t("Valores base que aplican a todas las cámaras.", "Base values that apply to every camera.")}</p>
                <div className="settings-field-grid">
                  <label className="field">
                    <span>{t("Calidad JPEG", "JPEG quality")}</span>
                    <div className="input-with-unit">
                      <input
                        type="number"
                        min="1"
                        max="100"
                        value={settings.jpeg_quality}
                        onChange={(event) =>
                          updateSetting("jpeg_quality", Number(event.target.value))
                        }
                        required
                      />
                      <span>%</span>
                    </div>
                  </label>
                  <label className="field">
                    <span>{t("Ancho del frame", "Frame width")}</span>
                    <div className="input-with-unit">
                      <input
                        type="number"
                        min="32"
                        max="8192"
                        value={settings.frame_width}
                        onChange={(event) =>
                          updateSetting("frame_width", Number(event.target.value))
                        }
                        required
                      />
                      <span>px</span>
                    </div>
                  </label>
                  <label className="field">
                    <span>{t("Alto del frame", "Frame height")}</span>
                    <div className="input-with-unit">
                      <input
                        type="number"
                        min="32"
                        max="8192"
                        value={settings.frame_height}
                        onChange={(event) =>
                          updateSetting("frame_height", Number(event.target.value))
                        }
                        required
                      />
                      <span>px</span>
                    </div>
                  </label>
                </div>
              </fieldset>

              <fieldset className="settings-group">
                <legend>{t("Capacidad y retención", "Capacity and retention")}</legend>
                <p>
                  {t("Los lectores RTSP operan en paralelo. Alibaba procesa una sola solicitud global; cada cámara conserva únicamente su candidato más reciente mientras espera turno.", "RTSP readers run in parallel. Alibaba processes one global request at a time; each camera keeps only its newest candidate while waiting.")}
                </p>
                <div className="settings-field-grid">
                  <label className="field">
                    <span>{t("Límite de llamadas", "Request limit")}</span>
                    <div className="input-with-unit">
                      <input
                        type="number"
                        min="0"
                        max="100000"
                        value={settings.max_api_calls_per_minute}
                        onChange={(event) =>
                          updateSetting("max_api_calls_per_minute", Number(event.target.value))
                        }
                        required
                      />
                      <span>RPM</span>
                    </div>
                  </label>
                  <label className="field">
                    <span>{t("Severidad para guardar", "Severity required to save")}</span>
                    <select
                      value={settings.save_image_min_severity}
                      onChange={(event) =>
                        updateSetting("save_image_min_severity", event.target.value)
                      }
                    >
                      {SEVERITY_LEVELS.map((level) => (
                        <option key={level} value={level}>
                          {t(({ none: "Ninguna", info: "Info", low: "Baja", medium: "Media", high: "Alta", critical: "Crítica" } as const)[level], ({ none: "None", info: "Info", low: "Low", medium: "Medium", high: "High", critical: "Critical" } as const)[level])}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="field">
                    <span>{t("Umbral de variación", "Variation threshold")}</span>
                    <div className="input-with-unit">
                      <input
                        type="number"
                        min="0"
                        max="100"
                        step="0.5"
                        value={settings.change_threshold_percent}
                        onChange={(event) =>
                          updateSetting("change_threshold_percent", Number(event.target.value))
                        }
                        required
                      />
                      <span>%</span>
                    </div>
                    <span className="field-hint">
                      {t("0 analiza siempre. Por encima de 0, un frame que varía menos que este porcentaje respecto al último analizado se omite — salvo que la última severidad conocida de esa cámara sea media o superior, en cuyo caso siempre se reanaliza.", "0 always analyzes. Above 0, a frame that differs by less than this percentage from the last analyzed frame is skipped—unless that camera's last known severity is medium or higher, in which case it is always analyzed again.")}
                    </span>
                  </label>
                  <label className="field checkbox-field">
                    <span>
                      <input
                        type="checkbox"
                        checked={settings.telegram_enabled}
                        onChange={(event) =>
                          updateSetting("telegram_enabled", event.target.checked)
                        }
                      />
                      {t("Notificaciones Telegram", "Telegram notifications")}
                    </span>
                    <span className="field-hint">
                      {settings.telegram_configured
                        ? t("Bot y chat configurados. Desmarcar apaga el envío sin borrar las credenciales.", "Bot and chat configured. Unchecking disables delivery without deleting credentials.")
                        : t("Todavía no hay bot/chat configurados (TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID, sólo por entorno); este interruptor no tiene efecto hasta que existan.", "No bot/chat is configured yet (TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID, environment only); this switch has no effect until they exist.")}
                      {" "}{t("Notifica por cámara según su umbral configurado.", "Notifications are sent per camera according to its configured threshold.")}
                    </span>
                  </label>
                </div>
              </fieldset>

              <fieldset className="settings-group alibaba-settings-group">
                <legend>{t("Proveedor Alibaba", "Alibaba provider")}</legend>
                <p>{t("Credenciales y parámetros de la API de análisis semántico.", "Credentials and parameters for the semantic analysis API.")}</p>
                <div className="settings-field-grid">
                  <label className="field field-span-2">
                    <span className="field-label-with-status">
                      API key
                      <span
                        className={`secret-status ${
                          settings.alibaba_api_key_configured ? "is-configured" : ""
                        }`}
                      >
                        {settings.alibaba_api_key_configured ? t("Configurada", "Configured") : t("Sin configurar", "Not configured")}
                      </span>
                    </span>
                    <input
                      type="password"
                      value={alibabaApiKey}
                      onChange={(event) => {
                        setAlibabaApiKey(event.target.value);
                        setSettingsSaved(false);
                      }}
                      placeholder={t("Vacío = conservar la clave actual", "Empty = keep current key")}
                      autoComplete="new-password"
                    />
                    <span className="field-hint">
                      {t("La clave es de sólo escritura y nunca vuelve al navegador.", "The key is write-only and is never returned to the browser.")}
                    </span>
                  </label>
                  <label className="field field-span-2">
                    <span>Base URL</span>
                    <input
                      type="url"
                      value={settings.alibaba_base_url}
                      maxLength={2048}
                      onChange={(event) =>
                        updateSetting("alibaba_base_url", event.target.value)
                      }
                      required
                    />
                  </label>
                  <label className="field">
                    <span>{t("Modelo", "Model")}</span>
                    <input
                      value={settings.alibaba_model}
                      maxLength={200}
                      onChange={(event) =>
                        updateSetting("alibaba_model", event.target.value)
                      }
                      required
                    />
                  </label>
                  <label className="field">
                    <span>Timeout</span>
                    <div className="input-with-unit">
                      <input
                        type="number"
                        min="1"
                        max="300"
                        step="0.1"
                        value={settings.alibaba_timeout_seconds}
                        onChange={(event) =>
                          updateSetting("alibaba_timeout_seconds", Number(event.target.value))
                        }
                        required
                      />
                      <span>seg</span>
                    </div>
                  </label>
                  <label className="field">
                    <span>{t("Reintentos", "Retries")}</span>
                    <div className="input-with-unit">
                      <input
                        type="number"
                        min="0"
                        max="10"
                        value={settings.alibaba_max_retries}
                        onChange={(event) =>
                          updateSetting("alibaba_max_retries", Number(event.target.value))
                        }
                        required
                      />
                      <span>int.</span>
                    </div>
                  </label>
                  <label className="field">
                    <span>{t("Máximo de tokens", "Maximum tokens")}</span>
                    <div className="input-with-unit">
                      <input
                        type="number"
                        min="32"
                        max="32768"
                        value={settings.alibaba_max_completion_tokens}
                        onChange={(event) =>
                          updateSetting(
                            "alibaba_max_completion_tokens",
                            Number(event.target.value),
                          )
                        }
                        required
                      />
                      <span>tok.</span>
                    </div>
                  </label>
                </div>
              </fieldset>
            </div>

            <div className="settings-save-bar">
              <p>
                {t("Una API key vacía conserva el secreto actual. Los cambios se validan antes de aplicarse.", "An empty API key keeps the current secret. Changes are validated before being applied.")}
              </p>
              <div>
                {settingsSaved && (
                  <span className="save-confirmation" role="status">
                    ✓ {t("Configuración guardada", "Settings saved")}
                  </span>
                )}
                <button type="submit" className="btn btn-primary" disabled={savingSettings}>
                  {savingSettings ? t("Guardando…", "Saving…") : t("Guardar cambios", "Save changes")}
                </button>
              </div>
            </div>
          </form>
        ) : (
          <div className="empty-inline">
            <p>{t("No se pudo obtener la configuración actual.", "Could not retrieve current settings.")}</p>
            <button type="button" className="btn btn-secondary" onClick={() => void loadSettings()}>
              {t("Reintentar", "Retry")}
            </button>
          </div>
        )}
      </section>
    </div>
  );
}
