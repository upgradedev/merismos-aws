import { expect, it } from 'vitest';
import { requestCorrelation } from './requestCorrelation';

const request = '12345678-1234-1234-1234-123456789012';
const lambda = '87654321-4321-4321-4321-210987654321';
const valid = {'x-merismos-request-id': request, 'x-merismos-lambda-request-id': lambda, 'x-merismos-correlation-mode': 'lambda-context'};

it('projects only server correlation values, never tokens or arbitrary headers', () => {
  expect(requestCorrelation({...valid, authorization: 'secret', 'set-cookie': 'secret'})).toEqual({request_id: request, lambda_request_id: lambda, mode: 'lambda-context'});
  expect(requestCorrelation({'X-Merismos-Request-ID': request, 'X-Merismos-Correlation-Mode': 'no-lambda-context'})).toEqual({request_id: request, lambda_request_id: null, mode: 'no-lambda-context'});
});
const invalid: Record<string, string>[] = [
  {}, {...valid, 'x-merismos-correlation-mode': 'unknown'},
  {...valid, 'x-merismos-lambda-request-id': ''},
  {...valid, 'x-merismos-lambda-request-id': 'x'.repeat(81)},
  {...valid, 'x-merismos-lambda-request-id': 'bad\r\nheader'},
  {...valid, 'x-merismos-request-id': 'bad'},
  {...valid, 'x-merismos-correlation-mode': 'no-lambda-context'},
];
it.each(invalid)('retains missing/inconsistent identity as unavailable, never inferred AWS proof %#', headers => {
  expect(requestCorrelation(headers)).toMatchObject({lambda_request_id: null, mode: 'unavailable'});
});
