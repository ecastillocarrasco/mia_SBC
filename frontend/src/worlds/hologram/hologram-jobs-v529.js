/**
 * Seguimiento REAL de informes, alineado con Job Manager de 2D.
 * La consulta de estado usa GET; jamás reenvía el prompt de generación.
 */
export class HologramJobError extends Error {
  constructor(code, detail='') { super(detail || code); this.name='HologramJobError'; this.code=code; }
}
const obj = (x) => x !== null && typeof x === 'object' && !Array.isArray(x);
const VALID_STATES = new Set(['queued','running','completed','failed','cancelled']);
const ACTIVE_STATES = new Set(['queued','running']);
export function extractHologramJob(raw) {
  const candidate = raw?.data?.job || raw?.job;
  if (!obj(candidate) || typeof candidate.job_id !== 'string' ||
      !candidate.job_id.trim() || candidate.job_id.length > 256) return null;
  return { status:'queued',progress:0, ...candidate, job_id:candidate.job_id.trim() };
}
export function jobIsActive(job) { return ACTIVE_STATES.has(job?.status); }
export function reportDownloadHref(job) {
  const id = job?.status === 'completed' ? job?.report_id : null;
  if (typeof id !== 'string' || !id.trim() || id.length > 256) return '';
  return '/api/reports/' + encodeURIComponent(id);
}
export function getJobStatusLabel(status) {
  return {queued:'En cola',running:'En curso',completed:'Completado',
    failed:'No se ha podido completar',cancelled:'Cancelado'}[status] || 'Estado desconocido';
}
function sleepAbort(ms, signal, setTimeoutFn = setTimeout) {
  return new Promise((resolve,reject) => {
    if (signal?.aborted) return reject(new HologramJobError('cancelled'));
    const timer = setTimeoutFn(() => {cleanup();resolve();},ms);
    const stop = () => {clearTimeout(timer);cleanup();reject(new HologramJobError('cancelled'));};
    const cleanup = () => signal?.removeEventListener?.('abort',stop);
    signal?.addEventListener?.('abort',stop,{once:true});
  });
}
export async function pollHologramJob(jobId, {
  fetchImpl=fetch, signal=null, onUpdate=()=>{}, pollMs=2500,
  maxMs=600000, maxConsecutiveFailures=4, requestTimeoutMs=15000,
  now=Date.now, sleep=sleepAbort,
} = {}) {
  if (typeof jobId !== 'string' || !jobId.trim() || jobId.length>256)
    throw new HologramJobError('invalid-job');
  const begin=now();
  let consecutiveFailures=0;
  while (!signal?.aborted && now() - begin < maxMs) {
    try {
      const controller = new AbortController();
      let timer = null;
      const abort = () => controller.abort();
      let cancelListener = null;
      signal?.addEventListener?.('abort',abort,{once:true});
      try {
        const operation = Promise.resolve().then(async() => {
          const response = await fetchImpl('/api/jobs/'+encodeURIComponent(jobId),{
            method:'GET',headers:{'Accept':'application/json'},signal:controller.signal,cache:'no-store',
          });
          if (!response.ok) throw new HologramJobError('status-http',`HTTP ${response.status}`);
          return response.json();
        });
        const timeout = new Promise((_,reject)=>{
          timer=setTimeout(()=>{
            controller.abort();
            reject(new HologramJobError('status-timeout'));
          },requestTimeoutMs);
        });
        const cancellation = new Promise((_,reject)=>{
          cancelListener = () => reject(new HologramJobError('cancelled'));
          if (signal?.aborted) cancelListener();
          else signal?.addEventListener?.('abort',cancelListener,{once:true});
        });
        var job = await Promise.race([operation,timeout,cancellation]);
      } finally {
        clearTimeout(timer);
        signal?.removeEventListener?.('abort',abort);
        if (cancelListener) signal?.removeEventListener?.('abort',cancelListener);
        controller.abort();
      }
      if (!obj(job) || job.job_id !== jobId || !VALID_STATES.has(job.status))
        throw new HologramJobError('invalid-status');
      consecutiveFailures=0;
      onUpdate(job);
      if (!jobIsActive(job)) return job;
    } catch (error) {
      if (signal?.aborted) throw new HologramJobError('cancelled');
      if (++consecutiveFailures >= maxConsecutiveFailures)
        throw new HologramJobError('poll-unavailable');
      onUpdate(null,{retry:true});
    }
    await sleep(pollMs,signal);
  }
  if (signal?.aborted) throw new HologramJobError('cancelled');
  throw new HologramJobError('poll-deadline');
}
