import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";

import {
  ApiError,
  fetchChatConfig,
  fetchChatThread,
  fetchChatThreads,
  queryHistoryChat,
  type ChatConfigResponse,
  type ChatMessage,
  type ChatThread,
} from "../api/client";
import { useLanguage } from "../i18n/useLanguage";

function toLocalInput(date: Date): string {
  const offset = date.getTimezoneOffset() * 60_000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 16);
}

function initialDates(): [string, string] {
  const now = new Date();
  const start = new Date(now);
  start.setHours(0, 0, 0, 0);
  return [toLocalInput(start), toLocalInput(now)];
}

export function ChatPage() {
  const { language, locale, t } = useLanguage();
  const [[initialFrom, initialTo]] = useState(initialDates);
  const [config, setConfig] = useState<ChatConfigResponse | null>(null);
  const [threads, setThreads] = useState<ChatThread[]>([]);
  const [threadId, setThreadId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [cameraId, setCameraId] = useState("");
  const [dateFrom, setDateFrom] = useState(initialFrom);
  const [dateTo, setDateTo] = useState(initialTo);
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastStats, setLastStats] = useState<{ sources: number; groups: number } | null>(null);

  const loadThreads = useCallback(async () => {
    try {
      setThreads(await fetchChatThreads());
    } catch {
      // The primary config error is more useful than a secondary sidebar error.
    }
  }, []);

  useEffect(() => {
    let active = true;
    Promise.all([fetchChatConfig(), fetchChatThreads()])
      .then(([nextConfig, nextThreads]) => {
        if (!active) return;
        setConfig(nextConfig);
        setThreads(nextThreads);
        setCameraId(nextConfig.cameras[0]?.id ?? "");
      })
      .catch((err) => {
        if (active) setError(err instanceof ApiError ? err.message : t("No se pudo cargar el asistente.", "Could not load the assistant."));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [t]);

  const startNew = () => {
    setThreadId(null);
    setMessages([]);
    setLastStats(null);
    setError(null);
  };

  const changeScope = (change: () => void) => {
    change();
    startNew();
  };

  const openThread = async (selected: ChatThread) => {
    setError(null);
    try {
      const detail = await fetchChatThread(selected.id);
      setThreadId(selected.id);
      setMessages(detail.messages);
      setCameraId(selected.camera_id);
      setDateFrom(toLocalInput(new Date(selected.date_from)));
      setDateTo(toLocalInput(new Date(selected.date_to)));
      setLastStats(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("No se pudo abrir la conversación.", "Could not open the conversation."));
    }
  };

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    const cleanQuestion = question.trim();
    if (!cleanQuestion || !cameraId || invalidRange || exceedsMaximum) return;
    setSending(true);
    setError(null);
    const optimistic: ChatMessage = {
      id: -Date.now(),
      thread_id: threadId ?? "new",
      role: "user",
      content: cleanQuestion,
      created_at: new Date().toISOString(),
    };
    setMessages((current) => [...current, optimistic]);
    setQuestion("");
    try {
      const response = await queryHistoryChat({
        camera_id: cameraId,
        date_from: new Date(dateFrom).toISOString(),
        date_to: new Date(dateTo).toISOString(),
        question: cleanQuestion,
        language,
        ...(threadId ? { thread_id: threadId } : {}),
      });
      setThreadId(response.thread_id);
      setMessages((current) => [
        ...current,
        {
          id: Date.now(),
          thread_id: response.thread_id,
          role: "assistant",
          content: response.answer,
          created_at: new Date().toISOString(),
        },
      ]);
      setLastStats({ sources: response.source_count, groups: response.group_count });
      void loadThreads();
    } catch (err) {
      setMessages((current) => current.filter((message) => message.id !== optimistic.id));
      setQuestion(cleanQuestion);
      setError(err instanceof ApiError ? err.message : t("No se pudo completar la consulta.", "Could not complete the query."));
    } finally {
      setSending(false);
    }
  };

  const selectedCamera = useMemo(
    () => config?.cameras.find((camera) => camera.id === cameraId),
    [cameraId, config],
  );
  const selectedRangeDays = useMemo(() => {
    const milliseconds = new Date(dateTo).getTime() - new Date(dateFrom).getTime();
    return Number.isFinite(milliseconds) ? milliseconds / 86_400_000 : Number.NaN;
  }, [dateFrom, dateTo]);
  const invalidRange = !Number.isFinite(selectedRangeDays) || selectedRangeDays <= 0;
  const exceedsMaximum =
    !invalidRange && selectedRangeDays > (config?.max_range_days ?? 31);
  const largeRange = !invalidRange && selectedRangeDays > 7 && !exceedsMaximum;

  if (loading) return <div className="panel chat-loading">{t("Cargando asistente…", "Loading assistant…")}</div>;

  return (
    <section className="chat-page">
      <header className="monitor-page-heading">
        <div>
          <span className="eyebrow">{t("CONSULTA HISTÓRICA", "HISTORICAL INQUIRY")}</span>
          <h1>{t("Analiza un rango con IA", "Analyze a range with AI")}</h1>
          <p>{t("Una cámara por conversación; el historial conserva 20 mensajes completos y resume los anteriores.", "One camera per conversation; history keeps 20 full messages and summarizes older ones.")}</p>
        </div>
      </header>

      {error && <div className="alert alert-error" role="alert">{error}</div>}
      {config && (!config.enabled || !config.configured) && (
        <div className="alert alert-warning">
          {!config.enabled
            ? t("El administrador deshabilitó el chat histórico.", "The administrator disabled historical chat.")
            : t("Falta configurar la API key de OpenAI en Administración.", "The OpenAI API key must be configured in Administration.")}
        </div>
      )}

      <div className="chat-layout">
        <aside className="panel chat-threads">
          <div className="chat-threads-heading">
            <h2>{t("Conversaciones", "Conversations")}</h2>
            <button type="button" className="btn btn-secondary" onClick={startNew}>{t("Nueva", "New")}</button>
          </div>
          {threads.length === 0 ? (
            <p className="field-hint">{t("Todavía no hay consultas guardadas.", "No saved inquiries yet.")}</p>
          ) : threads.map((thread) => (
            <button
              type="button"
              key={thread.id}
              className={`chat-thread-item ${thread.id === threadId ? "active" : ""}`}
              onClick={() => void openThread(thread)}
            >
              <strong>{thread.camera_name}</strong>
              <span>{new Date(thread.updated_at).toLocaleString(locale)}</span>
            </button>
          ))}
        </aside>

        <div className="panel chat-workspace">
          <div className="chat-scope-grid">
            <label className="field">
              <span>{t("Cámara", "Camera")}</span>
              <select value={cameraId} onChange={(event) => changeScope(() => setCameraId(event.target.value))} disabled={sending}>
                {config?.cameras.map((camera) => <option key={camera.id} value={camera.id}>{camera.name} ({camera.id})</option>)}
              </select>
            </label>
            <label className="field">
              <span>{t("Desde", "From")}</span>
              <input type="datetime-local" value={dateFrom} onChange={(event) => changeScope(() => setDateFrom(event.target.value))} disabled={sending} />
            </label>
            <label className="field">
              <span>{t("Hasta", "To")}</span>
              <input type="datetime-local" value={dateTo} onChange={(event) => changeScope(() => setDateTo(event.target.value))} disabled={sending} />
            </label>
          </div>
          {(invalidRange || exceedsMaximum || largeRange) && (
            <div
              className={`chat-range-warning ${invalidRange || exceedsMaximum ? "is-error" : ""}`}
              role="alert"
            >
              <strong>⚠ {t("Revisa el rango seleccionado", "Check the selected range")}</strong>
              <span>
                {invalidRange
                  ? t("La fecha final debe ser posterior a la inicial.", "The end date must be after the start date.")
                  : exceedsMaximum
                    ? t(`Elegiste ${Math.ceil(selectedRangeDays)} días y el máximo permitido es ${config?.max_range_days ?? 31}.`, `You selected ${Math.ceil(selectedRangeDays)} days and the allowed maximum is ${config?.max_range_days ?? 31}.`)
                    : t(`Elegiste ${Math.ceil(selectedRangeDays)} días. La consulta puede tardar más porque revisará todas las detecciones del rango.`, `You selected ${Math.ceil(selectedRangeDays)} days. The query may take longer because it will inspect every detection in the range.`)}
              </span>
            </div>
          )}

          <div className="chat-messages" aria-live="polite">
            {messages.length === 0 ? (
              <div className="chat-empty">
                <strong>{selectedCamera?.name ?? t("Selecciona una cámara", "Select a camera")}</strong>
                <p>{t("Pregunta, por ejemplo: “¿Qué eventos de mayor riesgo ocurrieron y en qué horarios?”", "Ask, for example: “Which highest-risk events occurred and at what times?”")}</p>
              </div>
            ) : messages.map((message) => (
              <article key={`${message.id}-${message.created_at}`} className={`chat-message ${message.role}`}>
                <span>{message.role === "user" ? t("Tú", "You") : "IRIS"}</span>
                <p>{message.content}</p>
              </article>
            ))}
            {sending && <div className="chat-thinking">{t("Agrupando detecciones y analizando…", "Grouping detections and analyzing…")}</div>}
          </div>

          {lastStats && (
            <p className="chat-stats">
              {t(`${lastStats.sources} detecciones resumidas en ${lastStats.groups} grupos.`, `${lastStats.sources} detections summarized into ${lastStats.groups} groups.`)}
            </p>
          )}
          <form className="chat-composer" onSubmit={(event) => void handleSubmit(event)}>
            <textarea
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              placeholder={t("Escribe una pregunta sobre este rango…", "Ask a question about this range…")}
              maxLength={2000}
              rows={3}
              disabled={sending || !config?.enabled || !config.configured}
            />
            <button type="submit" className="btn btn-primary" disabled={sending || !question.trim() || !cameraId || !config?.enabled || !config.configured || invalidRange || exceedsMaximum}>
              {sending ? t("Analizando…", "Analyzing…") : t("Enviar consulta", "Send inquiry")}
            </button>
          </form>
          <p className="field-hint">{t(`Modelo: ${config?.model ?? "—"}. Rango máximo: ${config?.max_range_days ?? "—"} días.`, `Model: ${config?.model ?? "—"}. Maximum range: ${config?.max_range_days ?? "—"} days.`)}</p>
        </div>
      </div>
    </section>
  );
}
