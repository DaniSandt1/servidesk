import { useEffect, useRef } from 'react';
import { MOCKED_SERVICES } from '../api';
import { onMockEvents } from '../mocks/events';

/** Intervalo de refresco con el backend real (los consumidores SQS tardan unos segundos). */
export const LIVE_POLL_MS = 15_000;

/**
 * Mantiene la vista al día con lo que hacen los eventos (incidentes automáticos, problemas
 * creados por recurrencia, notificaciones…).
 *
 * - Modo demo: recarga cuando el bus simulado procesa un evento de este tenant.
 * - Backend real: vuelve a consultar cada LIVE_POLL_MS mientras la pestaña está visible, y al
 *   volver a la pestaña. Los datos se mantienen en pantalla durante la recarga.
 */
export function useLiveRefresh(tenantId: string, ...reloads: (() => void)[]) {
  const fns = useRef(reloads);
  fns.current = reloads;
  useEffect(() => {
    const run = () => fns.current.forEach((r) => r());

    if (!MOCKED_SERVICES.length) {
      const tick = () => {
        if (document.visibilityState === 'visible') run();
      };
      const interval = setInterval(tick, LIVE_POLL_MS);
      document.addEventListener('visibilitychange', tick);
      return () => {
        clearInterval(interval);
        document.removeEventListener('visibilitychange', tick);
      };
    }

    let t: ReturnType<typeof setTimeout>;
    const off = onMockEvents((id) => {
      if (id !== tenantId) return;
      clearTimeout(t);
      t = setTimeout(run, 300);
    });
    return () => {
      off();
      clearTimeout(t);
    };
  }, [tenantId]);
}
