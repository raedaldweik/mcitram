// Pulls a TomTom render-map spec out of a RAM query result.
//
// The `tomtom-render-map` MCP tool returns a spec object tagged with
// `kind: "tomtom.map"`. Depending on how RAM surfaces the tool-call output, the
// spec can arrive as a nested object (structuredContent / _meta) or as a JSON
// string inside a text content block — so we deep-scan each tool call for it.

const MAP_KIND = 'tomtom.map';
const MAX_DEPTH = 8;

function deepFindMapSpec(value, depth = 0) {
  if (value == null || depth > MAX_DEPTH) return null;

  if (typeof value === 'string') {
    const s = value.trim();
    if (s.startsWith('{') && s.includes(MAP_KIND)) {
      try { return deepFindMapSpec(JSON.parse(s), depth + 1); } catch { return null; }
    }
    return null;
  }

  if (Array.isArray(value)) {
    for (const item of value) {
      const found = deepFindMapSpec(item, depth + 1);
      if (found) return found;
    }
    return null;
  }

  if (typeof value === 'object') {
    if (value.kind === MAP_KIND) return value;
    for (const key of Object.keys(value)) {
      const found = deepFindMapSpec(value[key], depth + 1);
      if (found) return found;
    }
  }

  return null;
}

/** Returns the first tomtom.map spec found in a normalized RAM response, or null. */
export function extractMapSpec(data) {
  if (!data) return null;
  // Prefer the trace tool calls — they carry tool *outputs* (where the
  // render-map spec lives). RAM's embedded response.toolCalls often omits them.
  const callSets = [data.trace?.toolCalls, data.toolCalls];
  for (const calls of callSets) {
    if (!Array.isArray(calls)) continue;
    for (const call of calls) {
      // The map spec only appears in tool *output*, never in input (no `kind` key),
      // so scanning the whole call object is safe.
      const found = deepFindMapSpec(call.output ?? call.structuredContent ?? call._meta ?? call);
      if (found) return found;
    }
  }
  return null;
}
