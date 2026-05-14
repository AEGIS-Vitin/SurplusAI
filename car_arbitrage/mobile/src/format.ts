export const fmtEur = (n?: number | null) =>
  n == null || isNaN(n)
    ? '—'
    : new Intl.NumberFormat('es-ES', {
        style: 'currency',
        currency: 'EUR',
        maximumFractionDigits: 0,
      }).format(n);

export const fmtPct = (n?: number | null) =>
  n == null || isNaN(n) ? '—' : `${(n * 100).toFixed(1)}%`;

export const fmtDays = (n?: number | null) =>
  n == null || isNaN(n) ? '—' : `${Math.round(n)} d`;
