/**
 * Client-side CSV generation and download utility.
 */

export function downloadCSV(data: Record<string, any>[], filename: string) {
  if (!data.length) return;

  const headers = Object.keys(data[0]);
  const csvRows = [
    headers.join(","),
    ...data.map(row =>
      headers.map(h => {
        const val = row[h];
        if (val == null) return "";
        const str = String(val);
        // CSV injection prevention — prefix dangerous leading characters
        const sanitized = /^[=+\-@\t\r]/.test(str) ? `'${str}` : str;
        // Escape quotes and wrap in quotes if contains comma/quote/newline
        if (sanitized.includes(",") || sanitized.includes('"') || sanitized.includes("\n")) {
          return `"${sanitized.replace(/"/g, '""')}"`;
        }
        return sanitized;
      }).join(",")
    )
  ];

  const blob = new Blob([csvRows.join("\n")], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${filename}_${new Date().toISOString().slice(0, 10)}.csv`;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}
