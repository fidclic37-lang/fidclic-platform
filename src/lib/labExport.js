/**
 * FidClic Lab (user, 2026-10-29): a shop's anonymous history, fetched in
 * parts (one Vercel answer is capped at 4.5 MB) and saved as one JSON file
 * for lab/fidclic_lab.py. The same assembly as api/features/lab_export.py
 * `assemble()`.
 */
import { adminAPI } from './api';

const KINDS = ['customers', 'visits', 'campaigns', 'automation_log', 'push'];

export function assemble(parts) {
  const data = { format: 'fidclic-lab/1', shop: null, exported_at: null, counts: null };
  KINDS.forEach((k) => { data[k] = []; });
  [...parts].sort((a, b) => (a.part || 0) - (b.part || 0)).forEach((p) => {
    if (p.kind === 'shop') Object.assign(data, { shop: p.shop, exported_at: p.exported_at, counts: p.counts });
    else if (KINDS.includes(p.kind)) data[p.kind].push(...(p.rows || []));
  });
  return data;
}

/** Fetches every part, then hands the browser one file. Returns the counts. */
export async function downloadLabExport(tenantId, onProgress) {
  const { data: s } = await adminAPI.labExportStart(tenantId);
  const parts = [];
  for (let n = 0; n < s.parts; n += 1) {
    if (onProgress) onProgress(n + 1, s.parts);
    // eslint-disable-next-line no-await-in-loop
    parts.push((await adminAPI.labExportPart(s.id, n)).data);
  }
  const data = assemble(parts);
  const day = (data.exported_at || new Date().toISOString()).slice(0, 10);
  const blob = new Blob([JSON.stringify(data)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `fidclic-lab-${data.shop?.activity || 'commerce'}-${day}.json`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
  return data.counts || {};
}
