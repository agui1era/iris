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

export function AdminPage() {
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
  const [createCameraError, setCreateCameraError] = useState<string | null>(null);
  const [creatingCamera, setCreatingCamera] = useState(false);

  const [editingCameraIndex, setEditingCameraIndex] = useState<number | null>(null);
  const [editCameraName, setEditCameraName] = useState("");
  const [editCameraRtspUrl, setEditCameraRtspUrl] = useState("");
  const [editCameraPrompt, setEditCameraPrompt] = useState("");
  const [editCameraPollInterval, setEditCameraPollInterval] = useState("30");
  const [editCameraError, setEditCameraError] = useState<string | null>(null);
  const [savingCamera, setSavingCamera] = useState(false);

  const loadUsers = useCallback(async () => {
    setUsersLoading(true);
    try {
      const data = await fetchAdminUsers();
      setUsers(data);
      setUsersError(null);
    } catch (err) {
      setUsersError(err instanceof ApiError ? err.message : "No se pudieron cargar los usuarios.");
    } finally {
      setUsersLoading(false);
    }
  }, []);

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
        err instanceof ApiError ? err.message : "No se pudo cargar la configuración.",
      );
    } finally {
      setSettingsLoading(false);
    }
  }, []);

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
      setUsersError(err instanceof ApiError ? err.message : "No se pudo actualizar el rol.");
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
      setUsersError(err instanceof ApiError ? err.message : "No se pudo actualizar el estado.");
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
      setCreateError(err instanceof ApiError ? err.message : "No se pudo crear el usuario.");
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
        analysis_cooldown_seconds: settings.analysis_cooldown_seconds,
        max_api_calls_per_minute: settings.max_api_calls_per_minute,
        save_image_min_severity: settings.save_image_min_severity,
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
          ? "La configuración cambió en otra sesión. Recarga los valores antes de volver a guardar."
          : err instanceof ApiError
            ? err.message
            : "No se pudo guardar la configuración.",
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
        err instanceof ApiError ? err.message : "No se pudieron cargar las cámaras.",
      );
    } finally {
      setCamerasLoading(false);
    }
  }, []);

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
      };

      await createAdminCamera(payload);
      await loadCameras();
      setNewCameraName("");
      setNewCameraRtspUrl("");
      setNewCameraPrompt("");
      setNewCameraPollInterval("30");
    } catch (err) {
      setCreateCameraError(err instanceof ApiError ? err.message : "No se pudo crear la cámara.");
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

      await updateAdminCamera(index, payload);
      await loadCameras();
      setEditingCameraIndex(null);
    } catch (err) {
      setEditCameraError(
        err instanceof ApiError ? err.message : "No se pudo actualizar la cámara.",
      );
    } finally {
      setSavingCamera(false);
    }
  };

  const handleDeleteCamera = async (camera: AdminCameraRecord) => {
    if (
      !window.confirm(
        `¿Eliminar la cámara "${camera.name}" (${camera.id})? Esta acción no se puede deshacer.`,
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
      setCamerasError(err instanceof ApiError ? err.message : "No se pudo eliminar la cámara.");
    } finally {
      setPendingCameraIndex(null);
    }
  };

  return (
    <div className="page">
      <div className="page-header">
        <h1>Administración</h1>
      </div>

      <section className="panel">
        <h2>Usuarios</h2>
        {usersError && (
          <div className="alert alert-error" role="alert">
            {usersError}
          </div>
        )}

        {usersLoading ? (
          <p className="muted">Cargando…</p>
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Usuario</th>
                  <th>Rol</th>
                  <th>Activo</th>
                  <th>Creado</th>
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
                              {role}
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
                          {target.is_active ? "Activo" : "Inactivo"}
                        </button>
                      </td>
                      <td>{new Date(target.created_at).toLocaleString()}</td>
                    </tr>
                  );
                })}
                {users.length === 0 && (
                  <tr>
                    <td colSpan={4} className="muted">
                      No hay usuarios.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}

        <form className="inline-form" onSubmit={(event) => void handleCreate(event)}>
          <h3>Crear usuario</h3>
          {createError && (
            <div className="alert alert-error" role="alert">
              {createError}
            </div>
          )}
          <div className="field-row">
            <label className="field">
              <span>Usuario</span>
              <input value={newUsername} onChange={(event) => setNewUsername(event.target.value)} required />
            </label>
            <label className="field">
              <span>Contraseña</span>
              <input
                type="password"
                value={newPassword}
                onChange={(event) => setNewPassword(event.target.value)}
                required
              />
            </label>
            <label className="field">
              <span>Rol</span>
              <select value={newRole} onChange={(event) => setNewRole(event.target.value)}>
                {ROLES.map((role) => (
                  <option key={role} value={role}>
                    {role}
                  </option>
                ))}
              </select>
            </label>
            <button type="submit" className="btn btn-primary" disabled={creating}>
              {creating ? "Creando…" : "Crear"}
            </button>
          </div>
        </form>
      </section>

      <section className="panel">
        <h2>Cámaras</h2>
        {camerasError && (
          <div className="alert alert-error" role="alert">
            {camerasError}
          </div>
        )}

        {camerasLoading ? (
          <p className="muted">Cargando…</p>
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Cámara</th>
                  <th>Nombre</th>
                  <th>RTSP</th>
                  <th>Prompt</th>
                  <th>Polling</th>
                  <th>Última captura</th>
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
                                <span>Nombre</span>
                                <input
                                  value={editCameraName}
                                  onChange={(event) => setEditCameraName(event.target.value)}
                                />
                              </label>
                              <label className="field camera-edit-wide">
                                <span>URL RTSP completa</span>
                                <input
                                  type="text"
                                  value={editCameraRtspUrl}
                                  onChange={(event) => setEditCameraRtspUrl(event.target.value)}
                                  autoComplete="off"
                                  spellCheck={false}
                                  required
                                />
                                <span className="field-hint">
                                  Incluye usuario, contraseña, host, puerto y ruta del stream.
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
                                <span>Polling de esta cámara</span>
                                <div className="input-with-unit">
                                  <input
                                    type="number"
                                    min="30"
                                    step="1"
                                    value={editCameraPollInterval}
                                    onChange={(event) =>
                                      setEditCameraPollInterval(event.target.value)
                                    }
                                    required
                                  />
                                  <span>seg</span>
                                </div>
                                <span className="field-hint">
                                  RTSP se lee en paralelo; Alibaba procesa una solicitud global a la
                                  vez.
                                </span>
                              </label>
                              <div className="camera-edit-actions">
                                <button
                                  type="submit"
                                  className="btn btn-primary"
                                  disabled={savingCamera}
                                >
                                  {savingCamera ? "Guardando…" : "Guardar cámara"}
                                </button>
                                <button
                                  type="button"
                                  className="btn btn-ghost"
                                  disabled={savingCamera}
                                  onClick={handleEditCameraCancel}
                                >
                                  Cancelar
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
                                Editar
                              </button>
                              <button
                                type="button"
                                className="btn btn-danger"
                                disabled={isPending}
                                onClick={() => void handleDeleteCamera(camera)}
                              >
                                {isPending ? "Eliminando…" : "Eliminar"}
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
                      No hay cámaras configuradas.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}

        <p className="muted">
          La URL RTSP completa se muestra y se edita aquí. El polling se configura por cámara y no
          puede ser menor a 30 segundos.
        </p>
        <p className="muted">
          "Última captura" muestra el frame más reciente que IRIS obtuvo para esa cámara, no un
          video en vivo. Su antigüedad depende del polling configurado en esa cámara y mostrará un
          diagnóstico mientras la fuente RTSP todavía no entregue imágenes.
        </p>

        <form className="inline-form" onSubmit={(event) => void handleCreateCamera(event)}>
          <h3>Agregar cámara</h3>
          {createCameraError && (
            <div className="alert alert-error" role="alert">
              {createCameraError}
            </div>
          )}
          <div className="field-row">
            <label className="field">
              <span>Nombre</span>
              <input
                value={newCameraName}
                onChange={(event) => setNewCameraName(event.target.value)}
                required
              />
            </label>
            <label className="field">
              <span>Polling</span>
              <div className="input-with-unit">
                <input
                  type="number"
                  min="30"
                  step="1"
                  value={newCameraPollInterval}
                  onChange={(event) => setNewCameraPollInterval(event.target.value)}
                  required
                />
                <span>seg</span>
              </div>
              <span className="field-hint">
                RTSP se lee en paralelo; Alibaba procesa una solicitud global a la vez.
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
              El usuario y la contraseña de la cámara van embebidos en la propia URL, con el
              formato rtsp://usuario:clave@host:554/stream — no hay un campo separado para
              credenciales.
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
              {creatingCamera ? "Creando…" : "Crear"}
            </button>
          </div>
        </form>
      </section>

      <section className="panel analysis-settings-panel">
        <div className="settings-panel-heading">
          <div>
            <span className="eyebrow">CONFIGURACIÓN PERSISTENTE</span>
            <h2>Motor de análisis</h2>
            <p>
              Controla resolución, capacidad de análisis y conexión con Alibaba.
            </p>
          </div>
          {settings && <span className="revision-badge">REVISIÓN {settings.revision}</span>}
        </div>

        {settingsError && (
          <div className="alert alert-error settings-error" role="alert">
            <span>{settingsError}</span>
            <button type="button" className="btn btn-ghost" onClick={() => void loadSettings()}>
              Recargar valores
            </button>
          </div>
        )}

        {settingsLoading ? (
          <div className="settings-loading" aria-label="Cargando configuración">
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
                <legend>Captura general</legend>
                <p>Valores base que aplican a todas las cámaras.</p>
                <div className="settings-field-grid">
                  <label className="field">
                    <span>Calidad JPEG</span>
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
                    <span>Ancho del frame</span>
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
                    <span>Alto del frame</span>
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
                <legend>Capacidad & retención</legend>
                <p>
                  Los lectores RTSP operan en paralelo. Alibaba procesa una sola solicitud global;
                  cada cámara conserva únicamente su candidato más reciente mientras espera turno.
                </p>
                <div className="settings-field-grid">
                  <label className="field">
                    <span>Cooldown de análisis</span>
                    <div className="input-with-unit">
                      <input
                        type="number"
                        min="0"
                        step="0.1"
                        value={settings.analysis_cooldown_seconds}
                        onChange={(event) =>
                          updateSetting("analysis_cooldown_seconds", Number(event.target.value))
                        }
                        required
                      />
                      <span>seg</span>
                    </div>
                  </label>
                  <label className="field">
                    <span>Límite de llamadas</span>
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
                    <span>Severidad para guardar</span>
                    <select
                      value={settings.save_image_min_severity}
                      onChange={(event) =>
                        updateSetting("save_image_min_severity", event.target.value)
                      }
                    >
                      {SEVERITY_LEVELS.map((level) => (
                        <option key={level} value={level}>
                          {level}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
              </fieldset>

              <fieldset className="settings-group alibaba-settings-group">
                <legend>Proveedor Alibaba</legend>
                <p>Credenciales y parámetros de la API de análisis semántico.</p>
                <div className="settings-field-grid">
                  <label className="field field-span-2">
                    <span className="field-label-with-status">
                      API key
                      <span
                        className={`secret-status ${
                          settings.alibaba_api_key_configured ? "is-configured" : ""
                        }`}
                      >
                        {settings.alibaba_api_key_configured ? "Configurada" : "Sin configurar"}
                      </span>
                    </span>
                    <input
                      type="password"
                      value={alibabaApiKey}
                      onChange={(event) => {
                        setAlibabaApiKey(event.target.value);
                        setSettingsSaved(false);
                      }}
                      placeholder="Vacío = conservar la clave actual"
                      autoComplete="new-password"
                    />
                    <span className="field-hint">
                      La clave es de sólo escritura y nunca vuelve al navegador.
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
                    <span>Modelo</span>
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
                    <span>Reintentos</span>
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
                    <span>Máximo de tokens</span>
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
                Una API key vacía conserva el secreto actual. Los cambios se validan antes de
                aplicarse.
              </p>
              <div>
                {settingsSaved && (
                  <span className="save-confirmation" role="status">
                    ✓ Configuración guardada
                  </span>
                )}
                <button type="submit" className="btn btn-primary" disabled={savingSettings}>
                  {savingSettings ? "Guardando…" : "Guardar cambios"}
                </button>
              </div>
            </div>
          </form>
        ) : (
          <div className="empty-inline">
            <p>No se pudo obtener la configuración actual.</p>
            <button type="button" className="btn btn-secondary" onClick={() => void loadSettings()}>
              Reintentar
            </button>
          </div>
        )}
      </section>
    </div>
  );
}
