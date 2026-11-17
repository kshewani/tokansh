import {useState} from 'react';
import {Info} from 'lucide-react';
import {Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis} from 'recharts';
import {useApi, useApp} from '../app/context';
import {route} from '../api/contracts';
import type {AuditEvent, Distribution, Entitlement, Issuance, LedgerOperation, Page, Portfolio} from '../api/contracts';
import {inr, integer, shortRef, todayIso, when} from '../lib/format';
import {Button} from '../components/ui/button';
import {Card, EmptyState, Metric, SectionHeading} from '../components/ui/card';
import {DataRow, Field, SelectField} from '../components/ui/form';
import {ReviewDialog} from '../components/ui/dialog';
import {LedgerRef, Loading, QueryError, Source, Status} from '../components/ui/status';
import {useProperties} from './RealEstate';

export function Distributions() {
  const {role, run, submitting} = useApp();
  const isIssuer = role === 'ISSUER';
  const issuances = useApi<Page<Issuance>>(route.issuances + '?page_size=50');
  const dists = useApi<Page<Distribution>>(route.distributions + '?page_size=50');
  const confirmed = (issuances.data?.items ?? []).filter(i => i.status === 'CONFIRMED');
  const [issuanceId, setIssuanceId] = useState('');
  const iss = confirmed.find(i => i.id === issuanceId) ?? confirmed[0];
  const [form, setForm] = useState({period_label: 'November 2026 rent', total_amount: '1000000', record_date: todayIso(), distribution_date: todayIso()});
  const [open, setOpen] = useState<null | 'declare' | {kind: 'calculate' | 'pay'; d: Distribution}>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const ents = useApi<{items: Entitlement[]}>(selected ? `${route.distributions}/${selected}/entitlements` : null);

  async function confirm() {
    if (open === 'declare' && iss) await run({path: route.distributions, label: 'Distribution declaration', body: {...form, issuance_id: iss.id, currency: 'INR'}});
    if (open && typeof open === 'object') {
      await run({path: `${route.distributions}/${open.d.id}/${open.kind === 'calculate' ? 'calculate' : 'simulate-payment'}`,
        label: open.kind === 'calculate' ? 'Entitlement calculation' : 'Simulated payout'});
      setSelected(open.d.id);
    }
    setOpen(null);
  }

  return <>
    <SectionHeading title="Rental Distributions" description="Entitlement = eligible ANSH at the record date ÷ total eligible × amount. Holdings are reconstructed from committed DRUNIX operations, never from current balances. Payouts are simulated."/>
    <div className="grid gap-5 xl:grid-cols-[1fr_1.5fr]">
      {isIssuer && <Card title="Declare a distribution" description="Calculation is allowed once the record date is reached">
        {!confirmed.length ? <EmptyState title="No issued asset" description="Issue ANSH first."/> :
          <form className="space-y-4" onSubmit={e => { e.preventDefault(); setOpen('declare'); }}>
            <SelectField label="Asset" id="dist-asset" value={iss?.id} onChange={e => setIssuanceId(e.target.value)}>
              {confirmed.map(i => <option key={i.id} value={i.id}>{i.property_name}</option>)}</SelectField>
            <Field label="Period" id="dist-period" value={form.period_label} onChange={e => setForm({...form, period_label: e.target.value})}/>
            <Field label="Total amount (INR)" id="dist-amount" inputMode="decimal" value={form.total_amount} onChange={e => setForm({...form, total_amount: e.target.value})}/>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Record date" id="dist-record" type="date" value={form.record_date} onChange={e => setForm({...form, record_date: e.target.value})}/>
              <Field label="Distribution date" id="dist-date" type="date" value={form.distribution_date} onChange={e => setForm({...form, distribution_date: e.target.value})}/></div>
            <Button type="submit" disabled={submitting}>Review declaration</Button>
          </form>}
      </Card>}
      <Card title="Distributions" description="Snapshot method and verification are shown for every calculation" className={isIssuer ? '' : 'xl:col-span-2'}>
        {dists.isLoading ? <Loading/> : dists.error ? <QueryError error={dists.error}/> : !dists.data?.items.length
          ? <EmptyState title="No distributions" description="—"/> : <div className="data-table-wrap"><table className="data-table w-full">
            <thead><tr><th>Period</th><th className="money">Total</th><th>Record date</th><th>Snapshot</th><th>Status</th>{!isIssuer && <th className="money">My entitlement</th>}<th/></tr></thead>
            <tbody>{dists.data.items.map(d => <tr key={d.id}>
              <td><p className="font-semibold">{d.period_label}</p><p className="text-[11px] text-slate-500">{d.property_name}</p></td>
              <td className="money">{inr(d.total_amount)}</td><td>{d.record_date}</td>
              <td>{d.snapshot ? <><Status value={d.snapshot.is_verified ? 'VERIFIED' : 'UNKNOWN'}/><p className="text-[10px] text-slate-500">{d.snapshot.method} · {integer(d.snapshot.total_eligible_quantity)} ANSH · tx {shortRef(d.snapshot.ledger_reference)}</p></> : <span className="text-xs text-slate-400">Not calculated</span>}</td>
              <td><Status value={d.status}/></td>
              {!isIssuer && <td className="money">{d.my_entitlement ? inr(d.my_entitlement.amount) : '—'}</td>}
              <td><div className="flex flex-wrap gap-1.5">
                {isIssuer && d.status === 'DECLARED' && <Button size="sm" onClick={() => setOpen({kind: 'calculate', d})}>Calculate</Button>}
                {isIssuer && d.status === 'PROCESSING' && <Button size="sm" onClick={() => setOpen({kind: 'pay', d})}>Simulate payout</Button>}
                {d.entitlement_count > 0 && <Button size="sm" variant="secondary" onClick={() => setSelected(d.id)}>Entitlements</Button>}</div></td>
            </tr>)}</tbody></table></div>}
      </Card>
    </div>
    {selected && <Card className="mt-5" title="Entitlements" description="Floor to the paisa; residual paise by largest remainder (deterministic)">
      {ents.isLoading ? <Loading/> : !ents.data?.items.length ? <EmptyState title="No entitlements visible" description="—"/> :
        <div className="data-table-wrap"><table className="data-table w-full"><thead><tr><th>Holder</th><th className="money">Eligible ANSH</th><th className="money">Total eligible</th><th className="money">Amount</th><th>Status</th><th>Payout reference</th></tr></thead>
          <tbody>{ents.data.items.map(e => <tr key={e.id}><td>{e.investor.name}</td><td className="money">{integer(e.eligible_quantity)}</td>
            <td className="money">{integer(e.total_eligible_quantity)}</td><td className="money font-semibold">{inr(e.amount)}</td><td><Status value={e.status}/></td>
            <td>{e.payment_reference ? <><code className="text-[10px]">{e.payment_reference}</code> <Source value="PAYMENT_SIMULATOR" simulated/></> : '—'}</td></tr>)}</tbody></table></div>}
    </Card>}
    <ReviewDialog open={!!open} onOpenChange={v => !v && setOpen(null)} onConfirm={confirm} busy={submitting} confirmLabel="Confirm"
      title={open === 'declare' ? 'Declare distribution' : open && open.kind === 'calculate' ? 'Calculate entitlements' : 'Simulated payout'}
      description={open === 'declare' ? 'Declaration only; no calculation or payment yet.' : open && open.kind === 'calculate' ? 'Uses holdings committed on DRUNIX up to the end of the record date. Fails if they cannot be verified against the issued supply.' : 'Marks entitlements paid with simulated payment references.'}>
      {open === 'declare' ? <dl><DataRow label="Asset" value={iss?.property_name}/><DataRow label="Amount" value={inr(form.total_amount)}/><DataRow label="Record date" value={form.record_date}/></dl>
        : open && <dl><DataRow label="Period" value={open.d.period_label}/><DataRow label="Amount" value={inr(open.d.total_amount)}/></dl>}
    </ReviewDialog>
  </>;
}

export function Audit({mode = 'audit'}: {mode?: 'audit' | 'transactions'}) {
  const {role, session, run, submitting} = useApp();
  const canSeeLedger = role !== 'INVESTOR';
  const audit = useApi<Page<AuditEvent>>(route.audit + '?page_size=100');
  const ops = useApi<Page<LedgerOperation>>(canSeeLedger ? route.ledgerOps + '?page_size=100' : null);
  const mine = useApi<{ledger_operations: LedgerOperation[]}>(!canSeeLedger && session ? `${route.portfolios}/${session.userId}/transactions` : null);
  const ledgerOps = canSeeLedger ? ops.data?.items ?? [] : mine.data?.ledger_operations ?? [];
  const unresolved = ledgerOps.filter(o => ['SUBMITTED', 'UNKNOWN', 'RECONCILIATION_REQUIRED'].includes(o.status));
  const [reconcile, setReconcile] = useState<LedgerOperation | null>(null);
  return <>
    <SectionHeading title={mode === 'audit' ? 'Audit & Lifecycle' : 'Transactions'} description="Application events, simulator events and DRUNIX ledger operations, each labelled with its source."/>
    <div className="grid gap-4 md:grid-cols-3">
      <Metric label="Ledger operations" value={integer(ledgerOps.length)} description="Submitted through the gateway adapter"/>
      <Metric label="Committed on DRUNIX" value={integer(ledgerOps.filter(o => o.status === 'COMMITTED').length)} description="Each with a DRUNIX transaction id"/>
      <Metric label="Awaiting reconciliation" value={integer(unresolved.length)} description="Never resubmitted blindly"/>
    </div>
    <Card className="mt-5" title="Ledger operations" description="Status exactly as established from DRUNIX">
      {!ledgerOps.length ? <EmptyState title="No ledger operations" description="—"/> : <div className="data-table-wrap"><table className="data-table w-full">
        <thead><tr><th>Operation</th><th>Function</th><th>Status · transaction</th><th>Error</th><th>Created</th><th/></tr></thead>
        <tbody>{ledgerOps.map(o => <tr key={o.operation_id}>
          <td><p className="font-semibold">{o.operation_type.replaceAll('_', ' ')}</p><code className="text-[10px] text-slate-500">{shortRef(o.operation_id)}</code></td>
          <td><code className="text-xs">{o.function}</code></td><td><LedgerRef op={o}/></td>
          <td className="max-w-[240px] text-xs text-red-700">{o.error_code}{o.error_message ? ': ' + o.error_message : ''}</td><td className="text-xs">{when(o.created_at)}</td>
          <td>{role === 'ISSUER' && ['SUBMITTED', 'UNKNOWN', 'RECONCILIATION_REQUIRED'].includes(o.status) && <Button size="sm" onClick={() => setReconcile(o)}>Reconcile</Button>}</td>
        </tr>)}</tbody></table></div>}
    </Card>
    <Card className="mt-5" title="Audit trail" description="Append-only application audit; not a blockchain record">
      {audit.isLoading ? <Loading/> : audit.error ? <QueryError error={audit.error}/> : !audit.data?.items.length ? <EmptyState title="No events" description="—"/> :
        <div className="data-table-wrap"><table className="data-table w-full">
          <thead><tr><th>Time</th><th>Event</th><th>Entity</th><th>Actor</th><th>Transition</th><th>Outcome</th><th>Source</th><th>DRUNIX tx</th></tr></thead>
          <tbody>{audit.data.items.map(e => <tr key={e.id}><td className="whitespace-nowrap text-xs">{when(e.occurred_at)}</td>
            <td className="font-semibold">{e.operation_type.replaceAll('_', ' ')}</td><td className="text-xs">{e.entity_type}</td><td>{e.actor?.name ?? 'System'}</td>
            <td className="text-xs">{e.previous_state ?? '—'} → {e.new_state ?? '—'}</td><td><Status value={e.outcome}/></td>
            <td><Source value={e.source} simulated={e.simulated}/></td><td><code className="text-[10px]">{shortRef(e.ledger_transaction_id)}</code></td></tr>)}</tbody></table></div>}
    </Card>
    <ReviewDialog open={!!reconcile} onOpenChange={v => !v && setReconcile(null)} busy={submitting} confirmLabel="Query DRUNIX status"
      title="Reconcile ledger operation" description="Queries the commit status by transaction id. The operation is never resubmitted."
      onConfirm={async () => { if (reconcile) await run({path: `${route.ledgerOps}/${reconcile.operation_id}/reconcile`, label: 'Reconciliation'}); setReconcile(null); }}>
      <dl><DataRow label="Operation" value={reconcile?.operation_type}/><DataRow label="Transaction id" value={reconcile?.ledger_transaction_id ?? 'None returned'}/></dl>
    </ReviewDialog>
  </>;
}

export function Intelligence() {
  const props = useProperties();
  const name = props.data?.items[0]?.name ?? 'Selected property';
  const [occupancy, setOccupancy] = useState(94), [valuation, setValuation] = useState(100), [rental, setRental] = useState(8.2);
  const data = [{name: 'Current', value: 100}, {name: 'Scenario', value: valuation}];
  return <>
    <SectionHeading title="Asset Intelligence" description="Illustrative what-if assumptions. Synthetic analytics only: no guaranteed returns or verified valuations."/>
    <div className="grid gap-5 xl:grid-cols-[1fr_1.2fr]">
      <Card title="Scenario inputs" description="Synthetic analytics, not a risk assessment">
        <div className="space-y-5">
          <Field id="intel-value" type="number" min={50} max={150} label="Illustrative valuation (₹ crore)" value={valuation} onChange={e => setValuation(Number(e.target.value))}/>
          <Field id="intel-occ" type="number" min={0} max={100} label="Occupancy assumption (%)" value={occupancy} onChange={e => setOccupancy(Number(e.target.value))}/>
          <Field id="intel-yield" type="number" min={0} max={30} step={0.1} label="Indicative rental yield (%)" value={rental} onChange={e => setRental(Number(e.target.value))}/>
        </div>
        <div className="mt-6 rounded-lg bg-slate-50 p-4 text-xs text-slate-600"><strong>Assumptions:</strong> these inputs do not change approved collateral values, ledger holdings or entitlements.</div>
      </Card>
      <Card title="Valuation sensitivity" description="₹ crore · synthetic two-point comparison">
        <div className="h-64"><ResponsiveContainer width="100%" height="100%"><BarChart data={data} layout="vertical" margin={{left: 12, right: 20, bottom: 10, top: 10}}>
          <CartesianGrid stroke="#e5eaf0" strokeDasharray="3 5"/><XAxis type="number" domain={[0, Math.max(155, valuation + 10)]} tickFormatter={(n: number) => '₹' + n} fontSize={11}/>
          <YAxis type="category" dataKey="name" width={70} fontSize={11}/><Tooltip formatter={(n) => ['₹' + String(n) + ' crore', 'Illustrative valuation']}/>
          <Bar dataKey="value" radius={[0, 4, 4, 0]}><Cell fill="#607D9B"/><Cell fill="#1769AA"/></Bar></BarChart></ResponsiveContainer></div>
        <dl><DataRow label="Property" value={name}/><DataRow label="Indicative scenario value" value={inr(Math.max(0, valuation) * 10000000)}/>
          <DataRow label="Occupancy" value={occupancy + '%'}/><DataRow label="Assumed annual yield" value={rental + '%'}/></dl>
      </Card>
    </div>
  </>;
}

export function System() {
  const {systemStatus, backendReady, ledgerStatus} = useApp();
  return <>
    <SectionHeading title="System Status" description="Live component status from the TokANSH API. A healthy API does not imply DRUNIX can commit."/>
    <div className="grid gap-4 md:grid-cols-3">
      <Metric label="Python API" value={backendReady ? 'Responding' : 'Not reachable'} description="FastAPI application"/>
      <Metric label="DRUNIX gateway" value={ledgerStatus} description="Reported by the gateway adapter"/>
      <Metric label="Unresolved ledger operations" value={systemStatus ? integer(systemStatus.unresolved_ledger_operations) : '—'} description="Require reconciliation"/>
    </div>
    <Card className="mt-5" title="Components" description="No secrets, certificates or internal topology are exposed">
      {!systemStatus ? <EmptyState title="API not reachable" description="Start the backend (see backend/README.md)."/> :
        <div className="data-table-wrap"><table className="data-table w-full"><thead><tr><th>Component</th><th>Status</th><th>Detail</th></tr></thead>
          <tbody>{systemStatus.components.map(c => <tr key={c.name}><td className="font-semibold">{c.name}</td><td><Status value={c.status}/></td><td className="text-xs">{c.detail}</td></tr>)}</tbody></table></div>}
      {systemStatus?.last_ledger_operation && <dl className="mt-4"><DataRow label="Last ledger operation" value={<LedgerRef op={systemStatus.last_ledger_operation}/>}/></dl>}
    </Card>
    <div className="mt-5 rounded-lg border border-blue-200 bg-blue-50 p-4 text-sm leading-6 text-blue-900"><div className="flex items-center gap-2 font-semibold"><Info size={18}/> Integration boundary</div>
      <p className="mt-1 text-xs">The frontend talks only to the Python API. The API reaches DRUNIX only through the Go gateway adapter. There is no simulator fallback: when DRUNIX is unavailable, ledger operations fail safely and are shown as such.</p></div>
  </>;
}
