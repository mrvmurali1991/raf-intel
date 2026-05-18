/**
 * Client-side CSV generation and download utility.
 *
 * Filename pattern: raf-{slug}-YYYY-MM-DD.csv
 *   - Always prefixed with "raf-" for easy identification.
 *   - Slug has any leading "raf-" de-duplicated so callers don't need to worry.
 *   - Date is ISO YYYY-MM-DD (UTC) appended automatically.
 *
 * Data rules enforced here so callers only need to pass clean values:
 *   - ICD codes and other alpha-numeric strings are quoted to prevent
 *     Excel auto-date conversion (e.g. "E11.9" stays a code, not a date).
 *   - Currency columns must be passed as plain numbers (no $ sign) so
 *     Excel SUM works correctly. Callers should strip formatting.
 *   - Date columns should be YYYY-MM-DD strings.
 *   - Percentage values are best passed as raw numbers (50 not "50%").
 *   - CSV injection prevention: dangerous leading chars (=+-@\t\r) are
 *     prefixed with a single-quote so spreadsheet formulas cannot execute.
 */

export function downloadCSV(data: Record<string, unknown>[], filename: string) {
  if (!data.length) return;

  // Normalise filename: strip any existing "raf-" prefix to avoid "raf-raf-…"
  const slug = filename.replace(/^raf-/i, "");
  const isoDate = new Date().toISOString().slice(0, 10);
  const finalFilename = `raf-${slug}-${isoDate}.csv`;

  const headers = Object.keys(data[0]);
  const csvRows = [
    // Always quote headers to handle spaces/special chars cleanly.
    headers.map((h) => `"${h.replace(/"/g, '""')}"`).join(","),
    ...data.map((row) =>
      headers.map((h) => {
        const val = row[h];
        if (val == null) return "";
        const str = String(val);
        // CSV injection prevention — prefix dangerous leading characters
        const sanitized = /^[=+\-@\t\r]/.test(str) ? `'${str}` : str;
        // Force-quote any value that contains a comma, quote, newline, or that
        // could be misinterpreted as a date/number by spreadsheet software.
        // In particular: ICD-10 codes like "E11.9" must be quoted so Excel does
        // not silently convert them to dates.
        const forceQuote =
          sanitized.includes(",") ||
          sanitized.includes('"') ||
          sanitized.includes("\n") ||
          // Looks like an ICD code: letter(s) then digits then optional dot-suffix
          /^[A-Za-z]\d/.test(sanitized) ||
          // Looks like a date Excel might mangle (M/D format like "11.9")
          /^\d+\.\d+$/.test(sanitized);
        if (forceQuote) {
          return `"${sanitized.replace(/"/g, '""')}"`;
        }
        return sanitized;
      }).join(",")
    ),
  ];

  const bom = "﻿"; // UTF-8 BOM — ensures Excel opens accented chars correctly
  const blob = new Blob([bom + csvRows.join("\n")], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = finalFilename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}
