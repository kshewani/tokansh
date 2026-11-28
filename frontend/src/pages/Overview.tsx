import {useState} from 'react';
import {ChevronRight, FileClock, RefreshCw} from 'lucide-react';
import {Link} from 'react-router-dom';
import {useApi, useApp} from '../app/context';
import {route} from '../api/contracts';
import type {AssetEvent, Dashboard, Distribution, Page, Portfolio as PortfolioData, Wallet} from '../api/contracts';
import {inr, integer, shortRef, when} from '../lib/format';
import {Card, EmptyState, Metric, SectionHeading} from '../components/ui/card';
import {Button} from '../components/ui/button';
import {Loading, QueryError, Source, Status} from '../components/ui/status';
import {ReviewDialog} from '../components/ui/dialog';
import {DataRow, Field} from '../components/ui/form';
import {Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis} from 'recharts';
import {PropertyThumb} from './RealEstate';
import type {Holding} from '../api/contracts';

const AVAILABLE = '#1769AA', PLEDGED = '#D08C1E';  // validated pair (CVD ΔE 26.7); exact figures in the table below

/** Available vs pledged ANSH per holding, from the committed-ledger projection. */
function AllocationChart({rows}: {rows: Holding[]}) {
  const chartData = rows.map(h => ({name: h.ansh_symbol, property: h.property_name, available: h.available_units, pledged: h.pledged_units}));
  return <div role="img" aria-label={'ANSH units by holding: ' + rows.map(h => `${h.ansh_symbol} ${h.available_units} available, ${h.pledged_units} pledged`).join('; ')}>
    <ResponsiveContainer width="100%" height={Math.max(120, 56 * rows.length + 60)}>
      <BarChart data={chartData} layout="vertical" margin={{top: 4, right: 16, bottom: 4, left: 8}} barCategoryGap="30%">
        <CartesianGrid horizontal={false} stroke="#E2E8F0"/>
        <XAxis type="number" allowDecimals={false} tick={{fontSize: 11, fill: '#64748B'}} axisLine={false} tickLine={false}
          tickFormatter={v => integer(v)}/>
        <YAxis type="category" dataKey="name" width={120} tick={{fontSize: 11, fill: '#334155'}} axisLine={false} tickLine={false}/>
        <Tooltip cursor={{fill: 'rgba(148,163,184,.12)'}} formatter={(v, k) => [integer(Number(v)) + ' ANSH', String(k) === 'available' ? 'Available' : 'Pledged'] as [string, string]}
          labelFormatter={label => chartData.find(d => d.name === label)?.property ?? String(label)}/>
        <Legend iconType="square" wrapperStyle={{fontSize: 12}} formatter={v => v === 'available' ? 'Available (transferable)' : 'Pledged (transfer-restricted)'}/>
        <Bar dataKey="available" stackId="u" fill={AVAILABLE} stroke="#fff" strokeWidth={2}/>
        <Bar dataKey="pledged" stackId="u" fill={PLEDGED} stroke="#fff" strokeWidth={2} radius={[0, 4, 4, 0]}/>
      </BarChart>
    </ResponsiveContainer>
  </div>;
}

function QuickLink({to, label}: {to: string; label: string}) {
  return <Button asChild variant="secondary" size="sm"><Link to={to}>{label}<ChevronRight size={15}/></Link></Button>;
}

export function Overview() {
  const {role, session} = useApp();
  const dash = useApi<Dashboard>(route.dashboard);
  const events = useApi<Page<AssetEvent>>(route.assetEvents + '?page_size=8');
  const portfolio = useApi<PortfolioData>(role === 'INVESTOR' && session ? `${route.portfolios}/${session.userId}` : null);
  const isIssuer = role === 'ISSUER', isLender = role === 'LENDER';
  const d = dash.data;
  return <>
    <SectionHeading title={isIssuer ? 'Platform Overview' : isLender ? 'Financing Overview' : 'Investor Dashboard'}
      description="Live figures from the TokANSH API. ANSH figures are projections of committed DRUNIX operations."
      action={<QuickLink to={isIssuer ? '/registry' : isLender ? '/lending' : '/marketplace'} label={isIssuer ? 'Property registry' : isLender ? 'Loan applications' : 'Explore ANSH'}/>}/>
    {dash.error ? <QueryError error={dash.error}/> : <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
      <Metric label="Approved illustrative valuation" value={d ? inr(d.properties.illustrative_approved_valuation, true) : '…'} description="Synthetic · not a market valuation"/>
      <Metric label="ANSH issued (committed)" value={d ? integer(d.ansh.issued) : '…'} description={d ? 'Approved supply ' + integer(d.ansh.approved_supply) : ''}/>
      {role === 'INVESTOR'
        ? <Metric label="My ANSH (owned / available)" value={portfolio.data ? `${integer(portfolio.data.summary.ansh.owned_units)} / ${integer(portfolio.data.summary.ansh.available_units)}` : '…'} description="Available = owned − pledged"/>
        : <Metric label="ANSH pledged" value={d ? integer(d.ansh.pledged) : '…'} description="Transfer-restricted on DRUNIX"/>}
      <Metric label="Ledger operations" value={d ? `${d.ledger.committed} committed` : '…'} description={d ? `${d.ledger.failed} failed · ${d.ledger.unresolved} awaiting reconciliation` : ''}/>
    </div>}
    <div className="mt-5 grid gap-5 xl:grid-cols-2">
      <Card title="Business summary" description="Counts from the application database">
        {!d ? <Loading/> : <div className="grid gap-4 sm:grid-cols-2">
          {[['Properties', `${d.properties.total} total · ${d.properties.approved} approved`], ['Pending review', integer(d.properties.pending_review)],
            ['Outstanding simulated loans', inr(d.financing.outstanding)], ['Unresolved ledger outcomes', integer(d.ledger.unresolved)]].map(([k, v]) =>
            <div key={k} className="rounded-lg bg-slate-50 p-4"><p className="text-xs text-slate-500">{k}</p><p className="font-financial mt-2 text-lg font-bold text-[#102B4E]">{v}</p></div>)}
        </div>}
      </Card>
      <Card title="Latest lifecycle activity" description="Each event shows its source" action={<QuickLink to="/transactions" label="All events"/>}>
        {events.isLoading ? <Loading/> : !events.data?.items.length ? <EmptyState title="No events yet" description="Onboard a property to begin."/> :
          <div className="divide-y divide-slate-100">{events.data.items.map(e => <div key={e.id} className="flex items-start gap-3 py-3">
            <div className="mt-1 rounded-lg bg-slate-100 p-2 text-[#1769AA]"><FileClock size={16}/></div>
            <div className="flex-1"><p className="text-xs font-semibold text-slate-700">{e.description}</p>
              <p className="mt-1 text-[11px] text-slate-500">{e.event_type} · {when(e.occurred_at)}{e.ledger_transaction_id ? ' · tx ' + shortRef(e.ledger_transaction_id) : ''}</p></div>
            <Source value={e.source} simulated={e.simulated}/></div>)}</div>}
      </Card>
    </div>
  </>;
}

const cash = /^\d{1,13}(\.\d{1,2})?$/;

/** Simulated demo cash: loan disbursements land here and repayments come from here. */
export function WalletCard() {
  const {run, submitting} = useApp();
  const w = useApi<Wallet>(route.wallet);
  const [amount, setAmount] = useState('120000');
  const [open, setOpen] = useState<null | 'fund' | 'withdraw'>(null);
  return <Card title="Demo wallet" description="SIMULATED INR cash: no bank and no real money" action={<Source value="PAYMENT_SIMULATOR" simulated/>}>
    {w.isLoading ? <Loading/> : w.error ? <QueryError error={w.error}/> : <>
      <p className="font-financial text-2xl font-extrabold text-[#102B4E]">{inr(w.data?.balance)}</p>
      <form className="mt-4 flex flex-wrap items-end gap-2" onSubmit={e => e.preventDefault()}>
        <div className="min-w-[160px] flex-1"><Field label="Amount (INR)" id="wallet-amount" inputMode="decimal" value={amount} onChange={e => setAmount(e.target.value)}
          error={cash.test(amount) ? undefined : 'Up to two decimal places'}/></div>
        <Button type="button" size="sm" disabled={!cash.test(amount) || submitting} onClick={() => setOpen('fund')}>Add demo funds</Button>
        <Button type="button" size="sm" variant="secondary" disabled={!cash.test(amount) || submitting} onClick={() => setOpen('withdraw')}>Withdraw</Button>
      </form>
      {!!w.data?.entries.length && <dl className="mt-4">{w.data.entries.slice(0, 5).map(e => <DataRow key={e.id}
        label={`${e.kind.replaceAll('_', ' ').toLowerCase()} · ${when(e.created_at)}`}
        value={`${['WITHDRAWAL', 'REPAYMENT', 'PURCHASE_PAYMENT'].includes(e.kind) ? '−' : '+'}${inr(e.amount)} → ${inr(e.balance_after)}`}/>)}</dl>}
    </>}
    <ReviewDialog open={!!open} onOpenChange={v => !v && setOpen(null)} busy={submitting} confirmLabel="Confirm"
      title={open === 'fund' ? 'Add demo funds' : 'Withdraw demo cash'} description="Simulated cash only. No bank account is contacted."
      onConfirm={async () => { if (open) await run({path: `${route.wallet}/${open}`, label: open === 'fund' ? 'Demo funds' : 'Withdrawal', body: {amount}}); setOpen(null); }}>
      <dl><DataRow label="Amount" value={inr(amount)}/><DataRow label="Current balance" value={inr(w.data?.balance)}/></dl>
    </ReviewDialog>
  </Card>;
}

export function Portfolio() {
  const {session} = useApp();
  const [verify, setVerify] = useState(false);
  const pf = useApi<PortfolioData>(session ? `${route.portfolios}/${session.userId}${verify ? '?verify=true' : ''}` : null);
  const dists = useApi<Page<Distribution>>(route.distributions + '?page_size=50');
  const s = pf.data?.summary;
  const income = (dists.data?.items ?? []).filter(d => d.my_entitlement);
  return <>
    <SectionHeading title="Investor Portfolio" description="ANSH economic interests (DRUNIX projection) and separate, simulated REIT holdings."
      action={<Button variant="secondary" size="sm" onClick={() => setVerify(true)}><RefreshCw size={14}/> Verify against DRUNIX</Button>}/>
    {pf.error && <QueryError error={pf.error}/>}
    <div className="grid gap-4 md:grid-cols-4">
      <Metric label="ANSH owned" value={s ? integer(s.ansh.owned_units) : '…'} description="Not proof of legal title"/>
      <Metric label="Available ANSH" value={s ? integer(s.ansh.available_units) : '…'} description="Owned minus pledged"/>
      <Metric label="Pledged ANSH" value={s ? integer(s.ansh.pledged_units) : '…'} description="Cannot be transferred"/>
      <Metric label="Acquisition cost" value={s ? inr(s.ansh.acquisition_cost) : '…'} description={s ? 'Illustrative value ' + inr(s.ansh.illustrative_value) : ''}/>
    </div>
    {!!pf.data?.ansh.length && <Card className="mt-5" title="ANSH allocation" description="Units per holding · available vs pledged · DRUNIX projection (exact figures in the table below)">
      <AllocationChart rows={pf.data.ansh}/></Card>}
    <Card className="mt-5" title="ANSH positions" description="Source: projection of committed DRUNIX operations, with its transaction reference">
      {pf.isLoading ? <Loading/> : !pf.data?.ansh.length ? <EmptyState title="No ANSH yet" description="Buy ANSH in the marketplace."/> :
        <div className="data-table-wrap"><table className="data-table w-full">
          <thead><tr><th>Asset</th><th className="money">Owned</th><th className="money">Available</th><th className="money">Pledged</th>
            <th className="money">Acquisition cost</th><th className="money">Illustrative value</th><th>Ledger reference</th><th>Verification</th></tr></thead>
          <tbody>{pf.data.ansh.map(h => <tr key={h.issuance_id}>
            <td><div className="flex items-center gap-3"><PropertyThumb name={h.property_name} symbol={h.ansh_symbol}/><div><p className="font-semibold">{h.property_name}</p>
              <p className="text-[11px] font-semibold text-slate-600">{h.ansh_symbol}</p><code className="text-[10px] text-slate-500">{h.ansh_asset_id}</code></div></div></td>
            <td className="money">{integer(h.owned_units)}</td><td className="money font-semibold text-green-800">{integer(h.available_units)}</td>
            <td className="money text-amber-800">{integer(h.pledged_units)}</td><td className="money">{inr(h.acquisition_cost)}</td>
            <td className="money">{inr(h.illustrative_value)}<p className="text-[10px] text-slate-400">simulated valuation</p></td>
            <td><code className="text-[10px]" title={h.ledger_reference}>{shortRef(h.ledger_reference, 14)}</code><p className="text-[10px] text-slate-400">{when(h.as_of)}</p></td>
            <td>{h.ledger_verification ? <Status value={h.ledger_verification.status}/> : <Status value={h.reconciliation_status === 'ACTIVE' ? 'PROJECTION' : h.reconciliation_status}/>}</td>
          </tr>)}</tbody></table></div>}
    </Card>
    <div className="mt-5 grid gap-5 xl:grid-cols-2">
      <Card title="Rental income" description="Entitlements from verified record-date holdings · payouts simulated">
        {!income.length ? <EmptyState title="No entitlements yet" description="Appear after the issuer calculates a distribution."/> :
          <dl>{income.map(d => <div key={d.id} className="flex items-center justify-between gap-3 border-b border-slate-100 py-2.5 last:border-0">
            <div><p className="text-sm font-semibold">{d.period_label}</p><p className="text-[11px] text-slate-500">{d.property_name} · record date {d.record_date} · {integer(d.my_entitlement!.eligible_quantity)} eligible ANSH</p></div>
            <div className="text-right"><p className="font-financial font-bold">{inr(d.my_entitlement!.amount)}</p><Status value={d.my_entitlement!.status}/></div></div>)}</dl>}
      </Card>
      <WalletCard/>
      <Card title="External REIT holdings" description="Separate asset class · simulated data · not eligible as ANSH collateral">
        {!pf.data?.reits.length ? <EmptyState title="No REIT holdings" description="—"/> :
          <div className="data-table-wrap"><table className="data-table w-full"><thead><tr><th>REIT</th><th className="money">Units</th><th className="money">Cost</th><th className="money">Illustrative value</th><th>Source</th></tr></thead>
            <tbody>{pf.data.reits.map(r => <tr key={r.id}><td className="font-semibold">{r.reit_name}</td><td className="money">{integer(r.quantity)}</td>
              <td className="money">{inr(r.purchase_value)}</td><td className="money">{inr(r.illustrative_market_value)}</td><td><Source value="EXTERNAL_SIMULATOR" simulated/></td></tr>)}</tbody></table></div>}
      </Card>
    </div>
  </>;
}
