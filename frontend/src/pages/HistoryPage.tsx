import { useEffect, useState, type FormEvent } from "react";

import { ApiError, fetchDetections, SEVERITY_LEVELS, type Detection } from "../api/client";
import { DetectionCard } from "../components/DetectionCard";

const PAGE_SIZE_OPTIONS = [10, 20, 50, 100];

interface Filters {
  dateFrom: string;
  dateTo: string;
  cameraId: string;
  severity: string;
}

const EMPTY_FILTERS: Filters = { dateFrom: "", dateTo: "", cameraId: "", severity: "" };

export function HistoryPage() {
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);
  const [appliedFilters, setAppliedFilters] = useState<Filters>(EMPTY_FILTERS);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  const [items, setItems] = useState<Detection[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);

    fetchDetections({
      date_from: appliedFilters.dateFrom || undefined,
      date_to: appliedFilters.dateTo || undefined,
      camera_id: appliedFilters.cameraId || undefined,
      severity: appliedFilters.severity || undefined,
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
        setError(err instanceof ApiError ? err.message : "No se pudo cargar el historial.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [appliedFilters, page, pageSize]);

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

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  return (
    <div className="page">
      <div className="page-header">
        <h1>Historial</h1>
      </div>

      <form className="filters" onSubmit={handleSubmit}>
        <label className="field">
          <span>Desde</span>
          <input
            type="datetime-local"
            value={filters.dateFrom}
            onChange={(event) => setFilters((f) => ({ ...f, dateFrom: event.target.value }))}
          />
        </label>
        <label className="field">
          <span>Hasta</span>
          <input
            type="datetime-local"
            value={filters.dateTo}
            onChange={(event) => setFilters((f) => ({ ...f, dateTo: event.target.value }))}
          />
        </label>
        <label className="field">
          <span>Cámara</span>
          <input
            type="text"
            placeholder="cam1"
            value={filters.cameraId}
            onChange={(event) => setFilters((f) => ({ ...f, cameraId: event.target.value }))}
          />
        </label>
        <label className="field">
          <span>Severidad</span>
          <select
            value={filters.severity}
            onChange={(event) => setFilters((f) => ({ ...f, severity: event.target.value }))}
          >
            <option value="">Todas</option>
            {SEVERITY_LEVELS.map((level) => (
              <option key={level} value={level}>
                {level}
              </option>
            ))}
          </select>
        </label>
        <div className="filter-actions">
          <button type="submit" className="btn btn-primary">
            Filtrar
          </button>
          <button type="button" className="btn btn-ghost" onClick={handleReset}>
            Limpiar
          </button>
        </div>
      </form>

      {error && (
        <div className="alert alert-error" role="alert">
          {error}
        </div>
      )}

      {loading ? (
        <p className="muted">Cargando…</p>
      ) : items.length === 0 ? (
        <p className="muted">No hay resultados para estos filtros.</p>
      ) : (
        <div className="detection-grid">
          {items.map((detection) => (
            <DetectionCard key={detection.id} detection={detection} />
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
          Anterior
        </button>
        <span className="pagination-info">
          Página {page} de {totalPages} · {total} resultado{total === 1 ? "" : "s"}
        </span>
        <button
          type="button"
          className="btn btn-ghost"
          disabled={page >= totalPages}
          onClick={() => setPage((p) => p + 1)}
        >
          Siguiente
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
              {size} / página
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}
