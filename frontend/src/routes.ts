import { filters, type Filter } from './workspaceModel';

export function parseRoute(value: string) {
  const normalized = !value ? '' : value.startsWith('/') ? value : '/' + value;
  const [path, search = ''] = normalized.split('?');
  const params = new URLSearchParams(search);
  const legacyOffer = path.startsWith('/offers/') && path !== '/offers/new' ? path.slice(8) : '';
  let offer = params.get('offer') || legacyOffer;
  try { offer = decodeURIComponent(offer); } catch { /* Invalid identifiers remain visibly missing. */ }
  const filter = params.get('filter') || 'all';
  return { path: path || '/dashboard', offer, pickup: params.get('pickup') || '', unit: params.get('unit') || '', query: params.get('q') || '',
    filter: (Object.hasOwn(filters, filter) ? filter : 'all') as Filter,
    page: path === '/workspace' || legacyOffer ? 'workspace' : path === '/records' || path === '/offers' ? 'records' : path === '/history' ? 'history' : path === '/pickups' ? 'pickups' : path === '/offers/new' ? 'intake' : path === '/landing' || path === '/overview' ? 'landing' : path === '/journeys' ? 'journeys' : path === '/architecture' ? 'architecture' : path === '/impact' ? 'impact' : !path || path === '/dashboard' ? 'dashboard' : 'missing' };
}
export function routeLink(path: string, options: { offer?: string; filter?: Filter; unit?: string; query?: string; pickup?: string } = {}) {
  const params = new URLSearchParams();
  if (options.offer) params.set('offer', options.offer);
  if (options.filter && options.filter !== 'all') params.set('filter', options.filter);
  if (options.unit) params.set('unit', options.unit);
  if (options.query) params.set('q', options.query);
  if (options.offer && options.pickup) params.set('pickup', options.pickup);
  return `#${path}${params.size ? `?${params}` : ''}`;
}
