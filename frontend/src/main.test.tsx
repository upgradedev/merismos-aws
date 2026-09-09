import { expect, it, vi } from 'vitest';
it('mounts the React application with StrictMode', async () => {
  const render = vi.fn(); vi.doMock('react-dom/client', () => ({createRoot:vi.fn(() => ({render}))}));
  document.body.innerHTML='<div id="root"></div>'; await import('./main'); expect(render).toHaveBeenCalledTimes(1);
});
