/**
 * Submission safeguards (adapted from the connected-mode frontend work).
 * A synchronous guard blocks a second financial request while one is in flight:
 * React state updates are asynchronous, so a disabled button alone can be double-clicked.
 */
export type SubmitGuard = {tryEnter: () => boolean; exit: () => void; readonly busy: boolean};

export function createSubmitGuard(): SubmitGuard {
  let busy = false;
  return {
    tryEnter() { if (busy) return false; busy = true; return true; },
    exit() { busy = false; },
    get busy() { return busy; },
  };
}

/** Message for a failed request. After dispatch, a lost response means the outcome is unknown. */
export function failureMessage(label: string, status: number, code: string, message: string): string {
  if (status === 0) {
    return `${label}: no response from the API. The request may or may not have been processed. ` +
      'Check Audit & Lifecycle before trying again; do not resubmit blindly. (BACKEND_UNAVAILABLE)';
  }
  if (code === 'LEDGER_OUTCOME_UNKNOWN' || code === 'RECONCILIATION_REQUIRED') {
    return `${label}: ${message} Reconcile it from Audit & Lifecycle; do not resubmit. (${code})`;
  }
  return `${label}: ${message} (${code})`;
}
