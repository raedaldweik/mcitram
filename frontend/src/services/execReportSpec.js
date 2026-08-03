// Pulls render_report executive-report specs out of an agent query result.
// Same deep-scan approach as chartSpec.js — the tool tags its output with
// `kind: "exec_report"`.

const KIND = 'exec_report';
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
    if (value.kind === KIND && Array.isArray(value.sections)) {
      out.push(value);
      return;
    }
    for (const key of Object.keys(value)) collect(value[key], out, depth + 1);
  }
}

/** Returns every executive-report spec found in a normalized response. */
export function extractExecReports(data) {
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
        const key = JSON.stringify([s.title, s.date, s.sections?.length]);
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
      });
    }
  }
  return [];
}
