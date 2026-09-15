import { describe, expect, it, vi } from 'vitest';

import { apiRequest } from './client';
import { NexusApiError } from './error';

describe('apiRequest', () => {
  it('serializes JSON requests through the configured API base URL', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );

    const result = await apiRequest<{ ok: boolean }>('/resource', {
      method: 'POST',
      body: { name: 'NEXUS' },
    });

    expect(result).toEqual({ ok: true });
    expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:8000/api/v1/resource',
      expect.objectContaining({ method: 'POST', body: JSON.stringify({ name: 'NEXUS' }) }),
    );
    const headers = fetchMock.mock.calls[0][1]?.headers as Headers;
    expect(headers.get('Content-Type')).toBe('application/json');
  });

  it('throws a normalized NexusApiError for failed responses', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({ error: { code: 'FORBIDDEN', message: 'Denied', request_id: 'req_9' } }),
        { status: 403, headers: { 'Content-Type': 'application/json' } },
      ),
    );

    await expect(apiRequest('/resource')).rejects.toMatchObject<NexusApiError>({
      status: 403,
      code: 'FORBIDDEN',
      requestId: 'req_9',
    });
  });

  it('supports successful responses without content', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(null, { status: 204 }));

    await expect(apiRequest('/resource', { method: 'DELETE' })).resolves.toBeUndefined();
  });
});
