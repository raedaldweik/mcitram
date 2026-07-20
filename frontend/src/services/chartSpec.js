// Pulls render_chart specs out of an agent query result.
//
// The `render_chart` MCP tool returns a spec object tagged with `kind: "chart"`
// (type, title, data rows, xKey, yKeys, stacked). Depending on how the backend surfaces
// the tool-call output, the spec can arrive as a nested object
// (structuredContent / _meta) or as a JSON string inside a text content block —
// so we deep-scan each tool call for it. The agent may emit several charts in
// one answer, so we collect them all (mapSpec.js returns just the first map).

const CHART_KIND = 'chart';
const MAX_DEPTH = 8;

function collectChartSpecs(value, out, depth = 0) {
  if (value == null || depth > MAX_DEPTH) return;

  if (typeof value === 'string') {
    const s = value.trim();
    if (s.startsWith('{') && s.includes(CHART_KIND)) {
      try { collectChartSpecs(JSON.parse(s), out, depth + 1); } catch { /* not JSON */ }
    }
    return;
  }

  if (Array.isArray(value)) {
    for (const item of value) collectChartSpecs(item, out, depth + 1);
    return;
  }

  if (typeof value === 'object') {
    // A valid chart spec is tagged kind:"chart" and carries data rows + yKeys.
    if (value.kind === CHART_KIND && Array.isArray(value.data) && Array.isArray(value.yKeys)) {
      out.push(value);
      return; // don't recurse into a matched spec (its rows have no nested specs)
    }
    for (const key of Object.keys(value)) collectChartSpecs(value[key], out, depth + 1);
  }
}

/** Returns every chart spec found in a normalized response (in order), de-duplicated. */
export function extractChartSpecs(data) {
  if (!data) return [];
  // Prefer the trace tool calls — they carry tool *outputs* (where the chart
  // spec lives). The embedded response.toolCalls may omit them. Use the
  // first call set that yields any charts so we don't double-count.
  const callSets = [data.trace?.toolCalls, data.toolCalls];
  for (const calls of callSets) {
    if (!Array.isArray(calls)) continue;
    const specs = [];
    for (const call of calls) {
      collectChartSpecs(call.output ?? call.structuredContent ?? call._meta ?? call, specs);
    }
    if (specs.length) {
      const seen = new Set();
      return specs.filter((s) => {
        const key = JSON.stringify([s.type, s.title, s.xKey, s.yKeys, s.data]);
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
      });
    }
  }
  return [];
}
