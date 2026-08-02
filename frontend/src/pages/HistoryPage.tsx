import { useCallback, useEffect, useState, type FormEvent } from "react";

import {
  ApiError,
  CRITICALITY_COLORS,
  deleteDetection,
  fetchDetections,
  SEVERITY_LEVELS,
  type Detection,
  type DetectionSortField,
} from "../api/client";
import { DetectionCard } from "../components/DetectionCard";
import { useAuth } from "../auth/useAuth";
import { useLanguage } from "../i18n/useLanguage";

const PAGE_SIZE_OPTIONS = [10, 20, 50, 100];

interface Filters {
  dateFrom: string;
  dateTo: string;
  cameraId: string;
  severity: string;
  criticidad: string;
}

const EMPTY_FILTERS: Filters = {
  dateFrom: "",
  dateTo: "",
  cameraId: "",
  severity: "",
  criticidad: "",
};

export function HistoryPage() {
  const { user } = useAuth();
  const { t } = useLanguage();
  const isAdmin = user?.role === "admin";

  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);
  const [appliedFilters, setAppliedFilters] = useState<Filters>(EMPTY_FILTERS);
  const [sortBy, setSortBy] = useState<DetectionSortField>("captured_at");
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("desc");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  const [items, setItems] = useState<Detection[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const load = useCallback(() => {
    let cancelled = false;
    setLoading(true);

    fetchDetections({
      date_from: appliedFilters.dateFrom || undefined,
      date_to: appliedFilters.dateTo || undefined,
      camera_id: appliedFilters.cameraId || undefined,
      severity: appliedFilters.severity || undefined,
      criticidad: appliedFilters.criticidad || undefined,
      sort_by: sortBy,
      sort_order: sortOrder,
      page,
      page_size: pageSize,
    })
      .then((data) => {
        if (cancelled) return;
        setItems(data.items);
        setTotal(data.total);
        setPage(data.page);
        setPageSize(data.page_size);
        setError(null);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : t("No se pudo cargar el historial.", "Could not load history."));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [appliedFilters, sortBy, sortOrder, page, pageSize, t]);

  useEffect(() => load(), [load]);

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setPage(1);
    setAppliedFilters(filters);
  };

  const handleReset = () => {
    setFilters(EMPTY_FILTERS);
    setAppliedFilters(EMPTY_FILTERS);
    setPage(1);
  };

  const handleDelete = async (detection: Detection) => {
    const label = detection.camera_name ?? detection.camera_id ?? detection.id;
    if (
      !window.confirm(
        t(`¿Eliminar esta detección de "${label}"? Esta acción no se puede deshacer.`, `Delete this detection from "${label}"? This action cannot be undone.`),
      )
    ) {
      return;
    }
    setDeletingId(detection.id);
    try {
      await deleteDetection(detection.id);
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("No se pudo eliminar la detección.", "Could not delete the detection."));
    } finally {
      setDeletingId(null);
    }
  };

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  return (
    <div className="page">
      <div className="page-header">
        <h1>{t("Historial", "History")}</h1>
      </div>

      <form className="filters" onSubmit={handleSubmit}>
        <label className="field">
          <span>{t("Desde", "From")}</span>
          <input
            type="datetime-local"
            value={filters.dateFrom}
            onChange={(event) => setFilters((f) => ({ ...f, dateFrom: event.target.value }))}
          />
        </label>
        <label className="field">
          <span>{t("Hasta", "To")}</span>
          <input
            type="datetime-local"
            value={filters.dateTo}
            onChange={(event) => setFilters((f) => ({ ...f, dateTo: event.target.value }))}
          />
        </label>
        <label className="field">
          <span>{t("Cámara", "Camera")}</span>
          <input
            type="text"
            placeholder="cam1"
            value={filters.cameraId}
            onChange={(event) => setFilters((f) => ({ ...f, cameraId: event.target.value }))}
          />
        </label>
        <label className="field">
          <span>{t("Severidad", "Severity")}</span>
          <select
            value={filters.severity}
            onChange={(event) => setFilters((f) => ({ ...f, severity: event.target.value }))}
          >
            <option value="">{t("Todas", "All")}</option>
            {SEVERITY_LEVELS.map((level) => (
              <option key={level} value={level}>
                {t(
                  ({ none: "Ninguna", info: "Info", low: "Baja", medium: "Media", high: "Alta", critical: "Crítica" } as const)[level],
                  ({ none: "None", info: "Info", low: "Low", medium: "Medium", high: "High", critical: "Critical" } as const)[level],
                )}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>{t("Criticidad", "Criticality")}</span>
          <select
            value={filters.criticidad}
            onChange={(event) => setFilters((f) => ({ ...f, criticidad: event.target.value }))}
          >
            <option value="">{t("Todas", "All")}</option>
            {CRITICALITY_COLORS.map((color) => (
              <option key={color} value={color}>
                {t(
                  ({ verde: "Verde", amarillo: "Amarillo", naranja: "Naranja", rojo: "Rojo" } as const)[color],
                  ({ verde: "Green", amarillo: "Yellow", naranja: "Orange", rojo: "Red" } as const)[color],
                )}
              </option>
            ))}
          </select>
        </label>
        <div className="filter-actions">
          <button type="submit" className="btn btn-primary">
            {t("Filtrar", "Filter")}
          </button>
          <button type="button" className="btn btn-ghost" onClick={handleReset}>
            {t("Limpiar", "Clear")}
          </button>
        </div>
      </form>

      <div className="filters sort-controls">
        <label className="field">
          <span>{t("Ordenar por", "Sort by")}</span>
          <select
            value={sortBy}
            onChange={(event) => {
              setSortBy(event.target.value as DetectionSortField);
              setPage(1);
            }}
          >
            {(["captured_at", "camera_id", "criticidad"] as DetectionSortField[]).map((field) => (
              <option key={field} value={field}>
                {field === "captured_at" ? t("Fecha", "Date") : field === "camera_id" ? t("Cámara", "Camera") : t("Criticidad", "Criticality")}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>{t("Orden", "Order")}</span>
          <select
            value={sortOrder}
            onChange={(event) => {
              setSortOrder(event.target.value as "asc" | "desc");
              setPage(1);
            }}
          >
            <option value="desc">{t("Descendente", "Descending")}</option>
            <option value="asc">{t("Ascendente", "Ascending")}</option>
          </select>
        </label>
      </div>

      {error && (
        <div className="alert alert-error" role="alert">
          {error}
        </div>
      )}

      {loading ? (
        <p className="muted">{t("Cargando…", "Loading…")}</p>
      ) : items.length === 0 ? (
        <p className="muted">{t("No hay resultados para estos filtros.", "No results match these filters.")}</p>
      ) : (
        <div className="detection-grid">
          {items.map((detection) => (
            <DetectionCard
              key={detection.id}
              detection={detection}
              onDelete={isAdmin ? () => void handleDelete(detection) : undefined}
              deleting={deletingId === detection.id}
            />
          ))}
        </div>
      )}

      <div className="pagination">
        <button
          type="button"
          className="btn btn-ghost"
          disabled={page <= 1}
          onClick={() => setPage((p) => Math.max(1, p - 1))}
        >
          {t("Anterior", "Previous")}
        </button>
        <span className="pagination-info">
          {t(`Página ${page} de ${totalPages} · ${total} resultado${total === 1 ? "" : "s"}`, `Page ${page} of ${totalPages} · ${total} result${total === 1 ? "" : "s"}`)}
        </span>
        <button
          type="button"
          className="btn btn-ghost"
          disabled={page >= totalPages}
          onClick={() => setPage((p) => p + 1)}
        >
          {t("Siguiente", "Next")}
        </button>
        <select
          value={pageSize}
          onChange={(event) => {
            setPageSize(Number(event.target.value));
            setPage(1);
          }}
        >
          {PAGE_SIZE_OPTIONS.map((size) => (
            <option key={size} value={size}>
              {size} / {t("página", "page")}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}
