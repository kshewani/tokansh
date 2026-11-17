import {AlertCircle, CheckCircle2, Clock3, Info, ShieldAlert} from 'lucide-react';
import type {LedgerOperation} from '../../api/contracts';
import {cn} from '../../utils/cn';
import {shortRef, when} from '../../lib/format';

const GOOD = ['COMMITTED', 'CONFIRMED', 'COMPLETED', 'ACTIVE', 'APPROVED', 'RELEASED', 'PAID', 'REPAID', 'CONNECTED', 'VERIFIED', 'SUCCESS', 'FILLED', 'ELIGIBLE'];
const BAD = ['FAILED', 'REJECTED', 'RECONCILIATION_REQUIRED', 'UNAVAILABLE', 'PAYMENT_FAILED', 'MISMATCH', 'DEGRADED', 'INELIGIBLE', 'CANCELLED'];
const WARN = ['PENDING', 'PROCESSING', 'SUBMITTED', 'UNKNOWN', 'PAYMENT_PENDING', 'TRANSFER_PENDING', 'UNDER_REVIEW', 'REQUESTED',
  'DECLARED', 'PARTIALLY_REPAID', 'RELEASE_PENDING', 'PARTIALLY_FILLED', 'DISBURSED', 'VALIDATING', 'CALCULATED', 'PAYMENT_SUCCEEDED'];

export function Status({value}: {value: string | null | undefined}) {
  const v = value || 'UNKNOWN';
  const good = GOOD.includes(v), bad = BAD.includes(v), warn = WARN.includes(v);
  const Icon = good ? CheckCircle2 : bad ? ShieldAlert : warn ? Clock3 : Info;
  return <span className={cn('inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2.5 py-1 text-[10px] font-bold',
    good ? 'border-green-200 bg-green-50 text-green-800' : bad ? 'border-red-200 bg-red-50 text-red-700'
      : warn ? 'border-amber-200 bg-amber-50 text-amber-800' : 'border-slate-200 bg-slate-100 text-slate-700')}>
    <Icon size={12} aria-hidden/>{v.replaceAll('_', ' ')}</span>;
}

/** Source label: keeps DRUNIX, application and simulated records visibly distinct (ADR-020). */
export function Source({value, simulated}: {value: string; simulated?: boolean}) {
  const sim = simulated || value.endsWith('SIMULATOR');
  const label = value === 'DRUNIX_LEDGER' ? 'DRUNIX' : sim ? 'SIMULATED' : value === 'APPLICATION' ? 'APPLICATION' : value.replaceAll('_', ' ');
  return <span className={cn('inline-flex rounded border px-1.5 py-0.5 text-[10px] font-bold uppercase',
    value === 'DRUNIX_LEDGER' ? 'border-indigo-200 bg-indigo-50 text-indigo-800' : sim ? 'border-orange-200 bg-orange-50 text-orange-800'
      : 'border-slate-200 bg-white text-slate-600')}>{label}</span>;
}

/** Ledger evidence for one operation: status plus the DRUNIX transaction id exactly as returned. */
export function LedgerRef({op, empty = 'Not submitted'}: {op: LedgerOperation | null | undefined; empty?: string}) {
  if (!op) return <span className="text-xs text-slate-400">{empty}</span>;
  return <span className="inline-flex flex-col items-end gap-1">
    <Status value={op.status}/>
    {op.ledger_transaction_id
      ? <code className="text-[10px] text-slate-600" title={op.ledger_transaction_id}>tx {shortRef(op.ledger_transaction_id, 14)}{op.block_number !== null ? ` · block ${op.block_number}` : ''}</code>
      : <span className="text-[10px] text-slate-400">{op.error_code ?? 'No transaction id'}</span>}
    {op.confirmed_at && <span className="text-[10px] text-slate-400">{when(op.confirmed_at)}</span>}
  </span>;
}

export function TrustNotice({compact = false}: {compact?: boolean}) {
  return <div className={cn('flex items-start gap-3 rounded-lg border border-blue-200 bg-blue-50 text-[#154b7a]', compact ? 'px-3 py-2 text-xs' : 'p-4 text-sm')}>
    <AlertCircle className="mt-0.5 shrink-0" size={16} aria-hidden/>
    <p><strong>Synthetic demonstration.</strong> Payments, lending and valuations are simulated. ANSH ledger states come from DRUNIX through the backend; a COMMITTED state always carries the DRUNIX transaction id. ANSH is an economic interest, not legal title.</p>
  </div>;
}
export function InlineError({message}: {message: string}) {
  return <p role="alert" className="mt-2 flex items-center gap-1 text-xs font-medium text-red-700"><AlertCircle size={14}/>{message}</p>;
}
export function Loading({label = 'Loading…'}: {label?: string}) {
  return <p role="status" className="py-6 text-center text-sm text-slate-500">{label}</p>;
}
export function QueryError({error}: {error: unknown}) {
  const msg = error instanceof Error ? error.message : 'Request failed.';
  return <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800">{msg}</div>;
}
