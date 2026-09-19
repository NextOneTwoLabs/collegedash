// Storage layout stays behind this adapter; handlers never accept asset paths.
export function assetPath(resource) {
  const { kind, slug } = resource;
  switch (kind) {
    case 'status':
      return '/archive/refresh-state.json';
    case 'programs':
      return '/data/programs/index.json';
    case 'program':
      return `/data/programs/${slug}.json`;
    case 'camps':
      return '/data/camps/index.json';
    case 'trends':
      return '/data/trends/index.json';
    case 'commitments':
      return '/data/commitments/index.json';
    default:
      throw new Error(`Unknown resource kind: ${kind}`);
  }
}

export function readAsset(request, env, resource) {
  const url = new URL(assetPath(resource), request.url);
  // Forward validators only, not cookies, ranges, or arbitrary browser headers.
  const headers = new Headers();
  for (const name of ['if-none-match', 'if-modified-since']) {
    if (request.headers.has(name)) {
      headers.set(name, request.headers.get(name));
    }
  }
  return env.ASSETS.fetch(new Request(url, { method: request.method, headers }));
}
