// An allowlist projection, not authentication or proof of Lambda cost/latency.
export type RequestCorrelation = {
  request_id: string | null;
  lambda_request_id: string | null;
  mode: 'lambda-context' | 'no-lambda-context' | 'unavailable';
};

export function requestCorrelation(headers: Record<string, string>): RequestCorrelation {
  const values = Object.fromEntries(Object.entries(headers).map(([key, value]) => [key.toLowerCase(), value]));
  const valid = (value: string | undefined) => typeof value === 'string' && /^[A-Za-z0-9-]{16,80}$/.test(value) ? value : null;
  const request = valid(values['x-merismos-request-id']);
  const lambda = valid(values['x-merismos-lambda-request-id']);
  const mode = values['x-merismos-correlation-mode'];
  if (request && mode === 'lambda-context' && lambda) return {request_id: request, lambda_request_id: lambda, mode};
  if (request && mode === 'no-lambda-context' && !lambda) return {request_id: request, lambda_request_id: null, mode};
  return {request_id: request, lambda_request_id: null, mode: 'unavailable'};
}
