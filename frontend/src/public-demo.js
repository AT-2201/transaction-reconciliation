const base = import.meta.env.BASE_URL;
export const publicDemo = import.meta.env.VITE_PUBLIC_DEMO === '1';
export const exceptionExport = publicDemo ? base + 'snapshot/exceptions.csv' : '/api/exports/exceptions.csv';
const cache = new Map();

function snapshot(path) {
  if (!cache.has(path)) {
    cache.set(path, fetch(base + 'snapshot' + path + '.json').then(response => {
      if (!response.ok) throw new Error('Demo data could not be loaded.');
      return response.json();
    }).catch(error => {
      cache.delete(path);
      throw error;
    }));
  }
  return cache.get(path);
}

export async function demoApi(path, options) {
  if (options.method && options.method !== 'GET') throw new Error('The public demo is read-only.');
  const [route, query] = path.split('?');
  if (route === '/me') return { role: 'reviewer', display_name: 'Public demo' };
  if (route === '/evidence-files' || route.endsWith('/rejections')) return [];
  const data = await snapshot(route);
  const params = new URLSearchParams(query);
  const offset = Number(params.get('offset') || 0);
  const limit = Number(params.get('limit') || (route === '/checks' ? 50 : 25));
  if (route.startsWith('/sources/')) return { ...data, items: data.items.slice(offset, offset + limit) };
  if (route !== '/exceptions' && route !== '/checks') return data;

  const stage = params.get('stage');
  const status = params.get('status');
  const search = (params.get('search') || '').toLowerCase();
  const items = data.filter(row => {
    if (stage && row.stage !== stage) return false;
    if (status === 'active' && ['resolved', 'dismissed'].includes(row.status)) return false;
    if (status && status !== 'active' && row.status !== status) return false;
    const searchable = route === '/exceptions' ? [row.entity_id, row.id, row.type] : [row.entity_id];
    return !search || searchable.some(value => value?.toLowerCase().includes(search));
  });
  return { items: items.slice(offset, offset + limit), total: items.length };
}
