import {useState} from 'react';
import {AlertTriangle} from 'lucide-react';
import {useApi, useApp} from '../app/context';
import {route} from '../api/contracts';
import type {DemoUser, LenderInstitution, Loan, Page, Pledge, Portfolio} from '../api/contracts';
import {inr, integer} from '../lib/format';
import {Button} from '../components/ui/button';
import {Card, EmptyState, Metric, SectionHeading} from '../components/ui/card';
import {ReviewDialog} from '../components/ui/dialog';
import {DataRow, Field, SelectField} from '../components/ui/form';
import {LedgerRef, Loading, QueryError, Status} from '../components/ui/status';

const money = /^\d{1,15}(\.\d{1,2})?$/;

export function Collateral() {
  const {role, session, run, submitting} = useApp();
  const isInvestor = role === 'INVESTOR';
  const pf = useApi<Portfolio>(isInvestor && session ? `${route.portfolios}/${session.userId}` : null);
  const pledges = useApi<Page<Pledge>>(route.pledges + '?page_size=50');
  const users = useApi<{items: DemoUser[]}>(route.users);
  const holdings = pf.data?.ansh ?? [];
  const [issuanceId, setIssuanceId] = useState('');
  const h = holdings.find(x => x.issuance_id === issuanceId) ?? holdings[0];
  const [qty, setQty] = useState(200);
  const [transferQty, setTransferQty] = useState(350);
  const recipients = (users.data?.items ?? []).filter(u => u.id !== session?.userId);
  const [to, setTo] = useState('');
  const recipient = recipients.find(u => u.id === to) ?? recipients.find(u => u.role === 'ISSUER') ?? recipients[0];
  const [open, setOpen] = useState<null | 'pledge' | 'transfer' | Pledge>(null);
  const valid = !!h && Number.isSafeInteger(qty) && qty > 0 && qty <= h.available_units;

  async function confirm() {
    if (open === 'pledge' && h) await run({path: route.pledges, label: 'Pledge', body: {issuance_id: h.issuance_id, quantity: qty}});
    if (open === 'transfer' && h && recipient) await run({path: route.transfers, label: 'ANSH transfer',
      body: {issuance_id: h.issuance_id, to_user_id: recipient.id, quantity: transferQty}});
    if (open && typeof open === 'object') await run({path: `${route.pledges}/${open.id}/release`, label: 'Collateral release'});
    setOpen(null);
  }

  return <>
    <SectionHeading title="Collateral Management" description="Pledges and releases are DRUNIX operations. Pledged units stay owned and income-eligible but cannot be transferred."/>
    {isInvestor && <div className="grid gap-4 md:grid-cols-3">
      <Metric label="Owned ANSH" value={h ? integer(h.owned_units) : '0'} description={h?.property_name ?? 'No holding'}/>
      <Metric label="Available ANSH" value={h ? integer(h.available_units) : '0'} description="Owned − pledged"/>
      <Metric label="Pledged ANSH" value={h ? integer(h.pledged_units) : '0'} description="Locked on DRUNIX"/>
    </div>}
    {isInvestor && <div className="mt-5 grid gap-5 xl:grid-cols-2">
      <Card title="Pledge ANSH" description="Collateral value uses the approved collateral valuation, not the market value">
        {!holdings.length ? <EmptyState title="No ANSH to pledge" description="Buy ANSH first."/> :
          <form className="space-y-4" onSubmit={e => { e.preventDefault(); if (valid) setOpen('pledge'); }}>
            <SelectField label="Asset" id="pledge-asset" value={h?.issuance_id} onChange={e => setIssuanceId(e.target.value)}>
              {holdings.map(x => <option key={x.issuance_id} value={x.issuance_id}>{x.property_name}</option>)}</SelectField>
            <Field id="pledge-qty" label="ANSH to pledge" type="number" min={1} max={h?.available_units} step={1} value={qty}
              onChange={e => setQty(Number(e.target.value))} error={h && qty > h.available_units ? 'Exceeds available ANSH' : undefined}/>
            <dl><DataRow label="Collateral value" value="Quantity × approved collateral unit value (calculated by the backend)"/>
              <DataRow label="Market value used?" value="No (Rule 8.3)"/></dl>
            <Button type="submit" disabled={!valid || submitting}>Review pledge</Button>
          </form>}
      </Card>
      <Card title="Transfer ANSH" description="Transfers beyond available units are rejected by the backend and by the chaincode">
        {!holdings.length ? <EmptyState title="No ANSH to transfer" description="—"/> : <form className="space-y-4" onSubmit={e => { e.preventDefault(); setOpen('transfer'); }}>
          <SelectField label="Recipient" id="transfer-to" value={recipient?.id} onChange={e => setTo(e.target.value)}>
            {recipients.map(u => <option key={u.id} value={u.id}>{u.name} · {u.role}</option>)}</SelectField>
          <Field id="transfer-qty" label="Quantity" type="number" min={1} step={1} value={transferQty} onChange={e => setTransferQty(Number(e.target.value))}/>
          {h && transferQty > h.available_units && <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
            <div className="flex items-center gap-2 font-semibold"><AlertTriangle size={15}/> Expected: rejected</div>
            {integer(transferQty)} exceeds the {integer(h.available_units)} available ANSH. You can still submit to see the backend enforce it.</div>}
          <Button type="submit" variant="secondary" disabled={submitting || !(transferQty > 0)}>Review transfer</Button>
        </form>}
      </Card>
    </div>}
    <Card className="mt-5" title="Pledges" description="Release requires the secured loan to be fully repaid; units become transferable after the release commits">
      {pledges.isLoading ? <Loading/> : pledges.error ? <QueryError error={pledges.error}/> : !pledges.data?.items.length
        ? <EmptyState title="No pledges" description="—"/> : <div className="data-table-wrap"><table className="data-table w-full">
          <thead><tr><th>Asset</th><th>Investor</th><th className="money">Qty</th><th className="money">Collateral value</th><th>Status</th><th>Pledge (DRUNIX)</th><th>Release (DRUNIX)</th><th/></tr></thead>
          <tbody>{pledges.data.items.map(p => <tr key={p.id}>
            <td className="font-semibold">{p.property_name}</td><td>{p.investor.name}</td><td className="money">{integer(p.quantity)}</td>
            <td className="money">{inr(p.collateral_value)}</td><td><Status value={p.status}/></td>
            <td className="text-right"><LedgerRef op={p.pledge_operation}/></td><td className="text-right"><LedgerRef op={p.release_operation} empty="—"/></td>
            <td>{p.status === 'ACTIVE' && <Button size="sm" variant="secondary" onClick={() => setOpen(p)}>Release</Button>}</td>
          </tr>)}</tbody></table></div>}
    </Card>
    <ReviewDialog open={!!open} onOpenChange={v => !v && setOpen(null)} onConfirm={confirm} busy={submitting} confirmLabel="Submit"
      title={open === 'pledge' ? 'Review pledge' : open === 'transfer' ? 'Review transfer' : 'Release collateral'}
      description={open === 'pledge' ? 'PledgeANSH is submitted to DRUNIX. Units are restricted only after the commit.' : open === 'transfer' ? 'TransferANSH is submitted only if your available balance on DRUNIX covers it.' : 'ReleasePledge is submitted to DRUNIX after the backend confirms full repayment.'}>
      <dl>{open === 'pledge' && <><DataRow label="Asset" value={h?.property_name}/><DataRow label="Quantity" value={integer(qty)}/></>}
        {open === 'transfer' && <><DataRow label="Recipient" value={recipient?.name}/><DataRow label="Quantity" value={integer(transferQty)}/><DataRow label="Your available ANSH" value={integer(h?.available_units)}/></>}
        {open && typeof open === 'object' && <><DataRow label="Pledge" value={open.property_name + ' · ' + integer(open.quantity) + ' ANSH'}/><DataRow label="Loan" value={open.loan_id ? 'Must be repaid' : 'None'}/></>}</dl>
    </ReviewDialog>
  </>;
}

type LoanAction = {kind: 'apply'} | {kind: 'assess' | 'approve' | 'reject' | 'disburse' | 'repay'; loan: Loan};

export function Lending() {
  const {role, run, submitting} = useApp();
  const isLender = role === 'LENDER';
  const loans = useApi<Page<Loan>>(route.loans + '?page_size=50');
  const pledges = useApi<Page<Pledge>>(route.pledges + '?status=ACTIVE&page_size=50');
  const available = (pledges.data?.items ?? []).filter(p => !p.loan_id);
  const [pledgeId, setPledgeId] = useState('');
  const pledge = available.find(p => p.id === pledgeId) ?? available[0];
  const [principal, setPrincipal] = useState('1200000');
  const catalogue = useApi<{items: LenderInstitution[]}>(isLender ? null : route.lenders);
  const institutions = catalogue.data?.items ?? [];
  const [lenderId, setLenderId] = useState('');
  const lender = institutions.find(l => l.id === lenderId) ?? institutions[0];
  const offer = lender?.offers[0];
  const [termChoice, setTermChoice] = useState<number | null>(null);
  const termMonths = offer && termChoice !== null && offer.tenures_months.includes(termChoice) ? termChoice
    : offer?.tenures_months.includes(12) ? 12 : offer?.tenures_months[0] ?? 12;
  const [repay, setRepay] = useState('');
  const [action, setAction] = useState<LoanAction | null>(null);

  async function confirm() {
    if (!action) return;
    if (action.kind === 'apply' && pledge) await run({path: route.loanApplications, label: 'Loan application (simulated)',
      body: {pledge_id: pledge.id, principal, currency: 'INR', lender_id: lender?.id, offer_id: offer?.id,
        interest_rate_bps: offer?.annual_rate_bps, term_months: termMonths}});
    else if (action.kind === 'repay') await run({path: `${route.loans}/${action.loan.id}/repayments`, label: 'Repayment (simulated)', body: {amount: repay || action.loan.total_outstanding, currency: 'INR'}});
    else if (action.kind !== 'apply') await run({path: `${route.loans}/${action.loan.id}/${action.kind}`, label: `Loan ${action.kind} (simulated)`, body: {}});
    setAction(null);
  }

  return <>
    <SectionHeading title={isLender ? 'Lender Console' : 'Loan Applications'} description="SIMULATED LENDING: no real credit decision, funds transfer or loan contract. LTV = outstanding ÷ collateral value × 100 (indicative)."/>
    {!isLender && <Card title="Apply for a simulated loan" description="Requires a pledge confirmed on DRUNIX">
      {!available.length ? <EmptyState title="No eligible pledge" description="Pledge ANSH first; each pledge can secure one loan."/> :
        <form className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5" onSubmit={e => { e.preventDefault(); if (money.test(principal)) setAction({kind: 'apply'}); }}>
          <SelectField label="Pledge" id="loan-pledge" value={pledge?.id} onChange={e => setPledgeId(e.target.value)}>
            {available.map(p => <option key={p.id} value={p.id}>{p.property_name} · {integer(p.quantity)} ANSH · {inr(p.collateral_value)}</option>)}</SelectField>
          <Field label="Principal (INR)" id="loan-principal" inputMode="decimal" value={principal} onChange={e => setPrincipal(e.target.value)}
            error={money.test(principal) ? undefined : 'Up to two decimal places'}/>
          <SelectField label="Lender (fictional)" id="loan-lender" value={lender?.id ?? ''} onChange={e => { setLenderId(e.target.value); setTermChoice(null); }}>
            {institutions.map(l => <option key={l.id} value={l.id}>{l.name} · {l.offers[0]?.annual_rate_percent}% · max LTV {l.offers[0]?.effective_max_ltv_percent}%</option>)}</SelectField>
          <SelectField label="Term" id="loan-term" value={termMonths} onChange={e => setTermChoice(Number(e.target.value))}>
            {(offer?.tenures_months ?? [12]).map(t => <option key={t} value={t}>{t} months</option>)}</SelectField>
          <div className="flex items-end"><Button type="submit" disabled={submitting}>Review application</Button></div>
        </form>}
    </Card>}
    <Card className="mt-5" title={isLender ? 'Loans assigned to you' : 'My loans'} description="All loan records are simulated">
      {loans.isLoading ? <Loading/> : loans.error ? <QueryError error={loans.error}/> : !loans.data?.items.length
        ? <EmptyState title="No loans" description="—"/> : <div className="data-table-wrap"><table className="data-table w-full">
          <thead><tr><th>Borrower</th><th className="money">Principal</th><th className="money">Interest</th><th className="money">Outstanding</th><th className="money">Collateral</th><th className="money">LTV</th><th>Status</th><th>Actions</th></tr></thead>
          <tbody>{loans.data.items.map(l => <tr key={l.id}>
            <td>{l.borrower.name}<p className="text-[10px] text-slate-400">lender {l.lender.name}</p></td><td className="money">{inr(l.principal)}</td>
            <td className="money">{inr(l.interest_quote)}<p className="text-[10px] text-slate-400">{l.interest_rate_percent}% · {l.term_months} mo</p></td>
            <td className="money">{inr(l.total_outstanding)}<p className="text-[10px] text-slate-400">principal {inr(l.outstanding)}</p></td><td className="money">{inr(l.collateral_value)}</td>
            <td className="money">{l.ltv_percent}%<p className="text-[10px] text-slate-400">max {l.max_ltv_percent}%</p></td>
            <td><Status value={l.status}/><p className="mt-1 text-[10px] text-orange-700">SIMULATED</p></td>
            <td><div className="flex flex-wrap gap-1.5">{isLender ? <>
              {['REQUESTED', 'UNDER_REVIEW'].includes(l.status) && <Button size="sm" variant="secondary" onClick={() => setAction({kind: 'assess', loan: l})}>Assess</Button>}
              {l.status === 'UNDER_REVIEW' && <Button size="sm" onClick={() => setAction({kind: 'approve', loan: l})}>Approve</Button>}
              {['REQUESTED', 'UNDER_REVIEW', 'APPROVED'].includes(l.status) && <Button size="sm" variant="secondary" onClick={() => setAction({kind: 'reject', loan: l})}>Reject</Button>}
              {l.status === 'APPROVED' && <Button size="sm" onClick={() => setAction({kind: 'disburse', loan: l})}>Disburse</Button>}
            </> : ['ACTIVE', 'PARTIALLY_REPAID'].includes(l.status) && <Button size="sm" onClick={() => { setRepay(l.total_outstanding); setAction({kind: 'repay', loan: l}); }}>Repay</Button>}</div></td>
          </tr>)}</tbody></table></div>}
    </Card>
    <ReviewDialog open={!!action} onOpenChange={v => !v && setAction(null)} onConfirm={confirm} busy={submitting} confirmLabel="Confirm"
      title={action ? (action.kind === 'apply' ? 'Simulated loan application' : `Simulated loan: ${action.kind}`) : ''}
      description="Lender-simulator workflow. No real money moves.">
      {action?.kind === 'apply' && <dl><DataRow label="Collateral" value={inr(pledge?.collateral_value)}/><DataRow label="Principal" value={inr(principal)}/>
        <DataRow label="Lender" value={lender ? `${lender.name} · ${offer?.name} offer` : '—'}/>
        <DataRow label="Terms" value={`${offer?.annual_rate_percent ?? '—'}% simple interest · ${termMonths} months · max LTV ${offer?.effective_max_ltv_percent ?? '—'}%`}/>
        <DataRow label="Interest and total" value="Calculated by the backend"/></dl>}
      {action && action.kind !== 'apply' && <dl><DataRow label="Borrower" value={action.loan.borrower.name}/><DataRow label="Outstanding (principal + interest)" value={inr(action.loan.total_outstanding)}/>
        <DataRow label="LTV" value={action.loan.ltv_percent + '%'}/></dl>}
      {action?.kind === 'repay' && <div className="mt-3"><Field label="Repayment amount (INR)" id="repay-amount" inputMode="decimal" value={repay}
        onChange={e => setRepay(e.target.value)} help="Paid from your demo wallet; applied to interest first, then principal."/></div>}
    </ReviewDialog>
  </>;
}
