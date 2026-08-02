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
  restartMonitorConnections,
  SEVERITY_LEVELS,
  testTelegramNotification,
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

const NOTIFICATION_RISK_MINIMUM = {
  none: 0,
  info: 10,
  low: 30,
  medium: 50,
  high: 70,
  critical: 90,
} as const;

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
  const [openaiApiKey, setOpenaiApiKey] = useState("");
  const [telegramBotToken, setTelegramBotToken] = useState("");
  const [testingTelegram, setTestingTelegram] = useState(false);
  const [telegramTestResult, setTelegramTestResult] = useState<string | null>(null);
  const [telegramTestError, setTelegramTestError] = useState<string | null>(null);

  const [cameras, setCameras] = useState<AdminCameraRecord[]>([]);
  const [camerasLoading, setCamerasLoading] = useState(true);
  const [camerasError, setCamerasError] = useState<string | null>(null);
  const [pendingCameraIndex, setPendingCameraIndex] = useState<number | null>(null);
  const [restartingMonitor, setRestartingMonitor] = useState(false);
  const [monitorRestartResult, setMonitorRestartResult] = useState<string | null>(null);
  const [monitorRestartError, setMonitorRestartError] = useState<string | null>(null);

  const [newCameraName, setNewCameraName] = useState("");
  const [newCameraRtspUrl, setNewCameraRtspUrl] = useState("");
  const [newCameraPrompt, setNewCameraPrompt] = useState("");
  const [newCameraPollInterval, setNewCameraPollInterval] = useState("30");
  const [newCameraNotificationThreshold, setNewCameraNotificationThreshold] = useState("high");
  const [newCameraNotificationsEnabled, setNewCameraNotificationsEnabled] = useState(true);
  const [createCameraError, setCreateCameraError] = useState<string | null>(null);
  const [creatingCamera, setCreatingCamera] = useState(false);

  const [editingCameraIndex, setEditingCameraIndex] = useState<number | null>(null);
  const [editCameraName, setEditCameraName] = useState("");
  const [editCameraRtspUrl, setEditCameraRtspUrl] = useState("");
  const [editCameraPrompt, setEditCameraPrompt] = useState("");
  const [editCameraPollInterval, setEditCameraPollInterval] = useState("30");
  const [editCameraNotificationThreshold, setEditCameraNotificationThreshold] = useState("high");
  const [editCameraNotificationsEnabled, setEditCameraNotificationsEnabled] = useState(true);
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
      setOpenaiApiKey("");
      setTelegramBotToken("");
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
        telegram_chat_id: settings.telegram_chat_id,
        telegram_dedup_cooldown_seconds: settings.telegram_dedup_cooldown_seconds,
        history_chat_enabled: settings.history_chat_enabled,
        history_chat_model: settings.history_chat_model,
        history_chat_max_range_days: settings.history_chat_max_range_days,
        alibaba_base_url: settings.alibaba_base_url,
        alibaba_model: settings.alibaba_model,
        alibaba_timeout_seconds: settings.alibaba_timeout_seconds,
        alibaba_max_retries: settings.alibaba_max_retries,
        alibaba_max_completion_tokens: settings.alibaba_max_completion_tokens,
      };
      if (alibabaApiKey.trim()) payload.alibaba_api_key = alibabaApiKey.trim();
      if (telegramBotToken.trim()) payload.telegram_bot_token = telegramBotToken.trim();
      if (openaiApiKey.trim()) payload.openai_api_key = openaiApiKey.trim();
      const updated = await updateSettings(payload);
      setSettings(updated);
      setAlibabaApiKey("");
      setTelegramBotToken("");
      setOpenaiApiKey("");
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

  const handleTelegramTest = async () => {
    setTestingTelegram(true);
    setTelegramTestResult(null);
    setTelegramTestError(null);
    try {
      const result = await testTelegramNotification();
      setTelegramTestResult(
        result.with_image
          ? t(`Prueba enviada con imagen (${result.attempts} intento).`, `Test sent with an image (${result.attempts} attempt).`)
          : t(`Prueba enviada como mensaje de respaldo (${result.attempts} intento).`, `Test sent as a fallback message (${result.attempts} attempt).`),
      );
    } catch (err) {
      setTelegramTestError(
        err instanceof ApiError
          ? err.message
          : t("No se pudo enviar la notificación de prueba.", "Could not send the test notification."),
      );
    } finally {
      setTestingTelegram(false);
    }
  };

  const handleMonitorRestart = async () => {
    const confirmed = window.confirm(
      t(
        "¿Reiniciar las conexiones RTSP? Las cámaras pueden quedar fuera de línea durante unos segundos.",
        "Restart the RTSP connections? Cameras may appear offline for a few seconds.",
      ),
    );
    if (!confirmed) return;
    setRestartingMonitor(true);
    setMonitorRestartResult(null);
    setMonitorRestartError(null);
    try {
      const result = await restartMonitorConnections();
      setMonitorRestartResult(
        t(
          `Reinicio solicitado (revisión ${result.revision}).`,
          `Restart requested (revision ${result.revision}).`,
        ),
      );
    } catch (err) {
      setMonitorRestartError(
        err instanceof ApiError
          ? err.message
          : t("No se pudo solicitar el reinicio.", "Could not request the restart."),
      );
    } finally {
      setRestartingMonitor(false);
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
        notifications_enabled: newCameraNotificationsEnabled,
      };

      await createAdminCamera(payload);
      await loadCameras();
      setNewCameraName("");
      setNewCameraRtspUrl("");
      setNewCameraPrompt("");
      setNewCameraPollInterval("30");
      setNewCameraNotificationThreshold("high");
      setNewCameraNotificationsEnabled(true);
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
    setEditCameraNotificationsEnabled(camera.notifications_enabled);
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
      payload.notifications_enabled = editCameraNotificationsEnabled;

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
        <div className="camera-admin-heading">
          <div>
            <h2>{t("Cámaras", "Cameras")}</h2>
            <p className="muted">
              {t("Administra las fuentes y recupera sus conexiones RTSP.", "Manage sources and recover their RTSP connections.")}
            </p>
          </div>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => void handleMonitorRestart()}
            disabled={restartingMonitor || cameras.length === 0}
          >
            {restartingMonitor ? t("Reiniciando conexiones…", "Restarting connections…") : t("Reiniciar conexiones RTSP", "Restart RTSP connections")}
          </button>
        </div>
        {monitorRestartResult && (
          <div className="alert alert-success" role="status">{monitorRestartResult}</div>
        )}
        {monitorRestartError && (
          <div className="alert alert-error" role="alert">{monitorRestartError}</div>
        )}
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
                  <th>{t("Canales", "Channels")}</th>
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
                        <td colSpan={7}>
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
                                  {t("RTSP se lee en paralelo; el motor procesa una solicitud global a la vez.", "RTSP is read in parallel; the engine processes one global request at a time.")}
                                </span>
                              </label>
                              <div className="camera-channel-config camera-edit-wide">
                                <div className="camera-channel-config-heading">
                                  <strong>{t("Canales de esta cámara", "Channels for this camera")}</strong>
                                  <span>{t("Cada canal se activa y configura por separado.", "Each channel is enabled and configured separately.")}</span>
                                </div>
                                <div className="camera-channel-row">
                                  <label className="checkbox-field channel-toggle">
                                    <span>
                                      <input
                                        type="checkbox"
                                        checked={editCameraNotificationsEnabled}
                                        onChange={(event) =>
                                          setEditCameraNotificationsEnabled(event.target.checked)
                                        }
                                      />
                                      Telegram
                                    </span>
                                    <span className="field-hint">
                                      {editCameraNotificationsEnabled
                                        ? t("Activo para esta cámara", "Active for this camera")
                                        : t("Desactivado para esta cámara", "Disabled for this camera")}
                                    </span>
                                  </label>
                                  <label className="field">
                                    <span>{t("Enviar desde riesgo", "Send from risk")}</span>
                                    <select
                                      value={editCameraNotificationThreshold}
                                      disabled={!editCameraNotificationsEnabled}
                                      onChange={(event) =>
                                        setEditCameraNotificationThreshold(event.target.value)
                                      }
                                    >
                                      {SEVERITY_LEVELS.map((level) => (
                                        <option key={level} value={level}>
                                          {NOTIFICATION_RISK_MINIMUM[level]}+ / 100 · {t(({ none: "Cualquier riesgo", info: "Informativo", low: "Bajo", medium: "Medio", high: "Alto", critical: "Crítico" } as const)[level], ({ none: "Any risk", info: "Informational", low: "Low", medium: "Medium", high: "High", critical: "Critical" } as const)[level])}
                                        </option>
                                      ))}
                                    </select>
                                    <span className="field-hint">
                                      {t("Al alcanzar el puntaje, envía mensaje e imagen.", "When the score is reached, send the message and image.")}
                                    </span>
                                  </label>
                                </div>
                              </div>
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
                            <span className={`camera-channel-summary ${camera.notifications_enabled ? "is-active" : ""}`}>
                              Telegram · {camera.notifications_enabled
                                ? `${NOTIFICATION_RISK_MINIMUM[camera.notification_threshold as keyof typeof NOTIFICATION_RISK_MINIMUM] ?? 70}+`
                                : t("Desactivado", "Disabled")}
                            </span>
                          </td>
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
                    <td colSpan={8} className="muted">
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
                {t("RTSP se lee en paralelo; el motor procesa una solicitud global a la vez.", "RTSP is read in parallel; the engine processes one global request at a time.")}
              </span>
            </label>
          </div>
          <div className="camera-channel-config">
            <div className="camera-channel-config-heading">
              <strong>{t("Canales de esta cámara", "Channels for this camera")}</strong>
              <span>{t("Activa cada canal y define desde qué riesgo debe enviar.", "Enable each channel and choose the risk level that triggers delivery.")}</span>
            </div>
            <div className="camera-channel-row">
              <label className="checkbox-field channel-toggle">
                <span>
                  <input
                    type="checkbox"
                    checked={newCameraNotificationsEnabled}
                    onChange={(event) => setNewCameraNotificationsEnabled(event.target.checked)}
                  />
                  Telegram
                </span>
                <span className="field-hint">
                  {newCameraNotificationsEnabled
                    ? t("Activo para esta cámara", "Active for this camera")
                    : t("Desactivado para esta cámara", "Disabled for this camera")}
                </span>
              </label>
              <label className="field">
                <span>{t("Enviar desde riesgo", "Send from risk")}</span>
                <select
                  value={newCameraNotificationThreshold}
                  disabled={!newCameraNotificationsEnabled}
                  onChange={(event) => setNewCameraNotificationThreshold(event.target.value)}
                >
                  {SEVERITY_LEVELS.map((level) => (
                    <option key={level} value={level}>
                      {NOTIFICATION_RISK_MINIMUM[level]}+ / 100 · {t(({ none: "Cualquier riesgo", info: "Informativo", low: "Bajo", medium: "Medio", high: "Alto", critical: "Crítico" } as const)[level], ({ none: "Any risk", info: "Informational", low: "Low", medium: "Medium", high: "High", critical: "Critical" } as const)[level])}
                    </option>
                  ))}
                </select>
                <span className="field-hint">
                  {t("Al alcanzar el puntaje, envía mensaje e imagen.", "When the score is reached, send the message and image.")}
                </span>
              </label>
            </div>
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
              {t("Controla resolución, capacidad y conexión del motor de análisis.", "Control resolution, capacity, and the analysis engine connection.")}
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
              <fieldset className="settings-group capture-settings-group">
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
                  {t("Los lectores RTSP operan en paralelo. El motor procesa una sola solicitud global; cada cámara conserva únicamente su candidato más reciente mientras espera turno.", "RTSP readers run in parallel. The engine processes one global request at a time; each camera keeps only its newest candidate while waiting.")}
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
                  <label className="field field-span-2">
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
                </div>
              </fieldset>

              <fieldset className="settings-group notification-channels-group">
                <legend>{t("Canales de notificación", "Notification channels")}</legend>
                <p>
                  {t("Agrega y configura los canales disponibles. Cada cámara decide cuáles usa y desde qué nivel de riesgo.", "Add and configure available channels. Each camera decides which ones to use and its minimum risk level.")}
                </p>
                <div className="notification-channels-grid">
                  <section className="notification-channel-card">
                    <div className="notification-channel-heading">
                      <div>
                        <h3>Telegram</h3>
                        <p>{t("Bot global para enviar una foto y el resumen del evento.", "Global bot for sending a photo and event summary.")}</p>
                      </div>
                      <span className={`channel-status ${settings.telegram_enabled && settings.telegram_configured ? "is-active" : ""}`}>
                        {settings.telegram_enabled && settings.telegram_configured
                          ? t("Activo", "Active")
                          : t("Inactivo", "Inactive")}
                      </span>
                    </div>
                    <div className="settings-field-grid">
                  <label className="field checkbox-field field-span-2 telegram-master-switch">
                    <span>
                      <input
                        type="checkbox"
                        checked={settings.telegram_enabled}
                        onChange={(event) =>
                          updateSetting("telegram_enabled", event.target.checked)
                        }
                      />
                      {t("Habilitar notificaciones", "Enable notifications")}
                    </span>
                    <span className="field-hint">
                      {settings.telegram_configured
                        ? t("Bot y chat configurados. Desactivar pausa todos los envíos sin borrar las credenciales.", "Bot and chat configured. Disabling pauses all delivery without deleting credentials.")
                        : t("Configura el token y el ID del chat para comenzar a enviar.", "Configure the token and chat ID to start sending.")}
                    </span>
                  </label>
                  <label className="field">
                    <span className="field-label-with-status">
                      {t("Token del bot", "Bot token")}
                      <span
                        className={`secret-status ${
                          settings.telegram_bot_token_configured ? "is-configured" : ""
                        }`}
                      >
                        {settings.telegram_bot_token_configured
                          ? t("Configurado", "Configured")
                          : t("Sin configurar", "Not configured")}
                      </span>
                    </span>
                    <input
                      type="password"
                      value={telegramBotToken}
                      onChange={(event) => {
                        setTelegramBotToken(event.target.value);
                        setSettingsSaved(false);
                      }}
                      placeholder={t("Vacío = conservar el token actual", "Empty = keep current token")}
                      autoComplete="new-password"
                    />
                    <span className="field-hint">
                      {t("Es de solo escritura y nunca vuelve al navegador.", "It is write-only and is never returned to the browser.")}
                    </span>
                  </label>
                  <label className="field">
                    <span>{t("ID del chat o canal", "Chat or channel ID")}</span>
                    <input
                      value={settings.telegram_chat_id ?? ""}
                      maxLength={200}
                      onChange={(event) => updateSetting("telegram_chat_id", event.target.value)}
                      placeholder="-1001234567890"
                      autoComplete="off"
                    />
                    <span className="field-hint">
                      {t("Para canales, agrega el bot como administrador y usa el ID que comienza con -100.", "For channels, add the bot as an administrator and use the ID beginning with -100.")}
                    </span>
                  </label>
                  <label className="field">
                    <span>{t("Agrupar repeticiones durante", "Group repeats for")}</span>
                    <div className="input-with-unit">
                      <input
                        type="number"
                        min="0"
                        max="604800"
                        value={settings.telegram_dedup_cooldown_seconds}
                        onChange={(event) =>
                          updateSetting(
                            "telegram_dedup_cooldown_seconds",
                            Number(event.target.value),
                          )
                        }
                        required
                      />
                      <span>seg</span>
                    </div>
                    <span className="field-hint">
                      {t("El primer evento se envía de inmediato. Un evento distinto o un riesgo mayor no espera. 0 desactiva la agrupación.", "The first event is sent immediately. A different event or higher risk does not wait. 0 disables grouping.")}
                    </span>
                  </label>
                    </div>
                    <div className="telegram-test-actions">
                      <div aria-live="polite">
                        {telegramTestResult && <span className="save-confirmation">✓ {telegramTestResult}</span>}
                        {telegramTestError && <span className="field-error">{telegramTestError}</span>}
                        {!telegramTestResult && !telegramTestError && (
                          <span className="field-hint">
                            {t("Usa las credenciales guardadas y la captura más reciente. Si no hay imagen, envía un mensaje de respaldo.", "Uses the saved credentials and newest capture. If no image is available, it sends a fallback message.")}
                          </span>
                        )}
                      </div>
                      <button
                        type="button"
                        className="btn btn-secondary"
                        onClick={() => void handleTelegramTest()}
                        disabled={testingTelegram || !settings.telegram_configured}
                      >
                        {testingTelegram ? t("Enviando prueba…", "Sending test…") : t("Enviar notificación de prueba", "Send test notification")}
                      </button>
                    </div>
                  </section>
                </div>
              </fieldset>

              <fieldset className="settings-group provider-settings-group">
                <legend>{t("Asistente histórico", "Historical assistant")}</legend>
                <p>
                  {t("Consulta una cámara y un rango de fechas. Las detecciones repetidas se agregan antes de llamar al modelo.", "Query one camera and date range. Repeated detections are aggregated before calling the model.")}
                </p>
                <div className="settings-field-grid">
                  <label className="field checkbox-field provider-wide-field">
                    <span>
                      <input
                        type="checkbox"
                        checked={settings.history_chat_enabled}
                        onChange={(event) =>
                          updateSetting("history_chat_enabled", event.target.checked)
                        }
                      />
                      {t("Habilitar chat histórico", "Enable historical chat")}
                    </span>
                  </label>
                  <label className="field provider-wide-field">
                    <span className="field-label-with-status">
                      OpenAI API key
                      <span className={`secret-status ${settings.openai_api_key_configured ? "is-configured" : ""}`}>
                        {settings.openai_api_key_configured ? t("Configurada", "Configured") : t("Sin configurar", "Not configured")}
                      </span>
                    </span>
                    <input
                      type="password"
                      value={openaiApiKey}
                      onChange={(event) => {
                        setOpenaiApiKey(event.target.value);
                        setSettingsSaved(false);
                      }}
                      placeholder={t("Vacío = conservar la clave actual", "Empty = keep current key")}
                      autoComplete="new-password"
                    />
                    <span className="field-hint">
                      {t("Es de solo escritura y nunca vuelve al navegador.", "It is write-only and is never returned to the browser.")}
                    </span>
                  </label>
                  <label className="field">
                    <span>{t("Modelo", "Model")}</span>
                    <input
                      value={settings.history_chat_model}
                      maxLength={100}
                      onChange={(event) => updateSetting("history_chat_model", event.target.value)}
                      required
                    />
                  </label>
                  <label className="field">
                    <span>{t("Rango máximo", "Maximum range")}</span>
                    <div className="input-with-unit">
                      <input
                        type="number"
                        min="1"
                        max="366"
                        value={settings.history_chat_max_range_days}
                        onChange={(event) =>
                          updateSetting("history_chat_max_range_days", Number(event.target.value))
                        }
                        required
                      />
                      <span>{t("días", "days")}</span>
                    </div>
                  </label>
                </div>
              </fieldset>

              <fieldset className="settings-group alibaba-settings-group provider-settings-group">
                <legend>{t("Proveedor de análisis", "Analysis provider")}</legend>
                <p>{t("Credenciales y parámetros de la API de análisis semántico.", "Credentials and parameters for the semantic analysis API.")}</p>
                <div className="settings-field-grid">
                  <label className="field provider-wide-field">
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
                  <label className="field provider-wide-field">
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
