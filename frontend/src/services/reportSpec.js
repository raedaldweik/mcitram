// Pulls Visual Analytics report-image specs out of an agent query result.
//
// VA tools tag their outputs with `kind: "report_image"` and carry an
// imageUrl (served by the backend image cache), plus report metadata and an
// optional viewerUrl for opening the live report in SAS Visual Analytics.
// Same deep-scan approach as chartSpec.js.

const KIND = 'report_image';
const MAX_DEPTH = 8;

function collect(value, out, depth = 0) {
  if (value == null || depth > MAX_DEPTH) return;

  if (typeof value === 'string') {
    const s = value.trim();
    if (s.startsWith('{') && s.includes(KIND)) {
      try { collect(JSON.parse(s), out, depth + 1); } catch { /* not JSON */ }
    }
    return;
  }

  if (Array.isArray(value)) {
    for (const item of value) collect(item, out, depth + 1);
    return;
  }

  if (typeof value === 'object') {
    if (value.kind === KIND && typeof value.imageUrl === 'string') {
      out.push(value);
      return;
    }
    for (const key of Object.keys(value)) collect(value[key], out, depth + 1);
  }
}

/** Returns every report-image spec found in a normalized response, de-duplicated. */
export function extractReportImages(data) {
  if (!data) return [];
  const callSets = [data.trace?.toolCalls, data.toolCalls];
  for (const calls of callSets) {
    if (!Array.isArray(calls)) continue;
    const specs = [];
    for (const call of calls) {
      collect(call.output ?? call, specs);
    }
    if (specs.length) {
      const seen = new Set();
      return specs.filter((s) => {
        if (seen.has(s.imageUrl)) return false;
        seen.add(s.imageUrl);
        return true;
      });
    }
  }
  return [];
}
