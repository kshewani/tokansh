import {useState} from 'react';
import {ArrowRight} from 'lucide-react';
import {useApi, useApp} from '../app/context';
import {route} from '../api/contracts';
import type {Issuance, Listing, Order, Page, Property} from '../api/contracts';
import {inr, integer, multiplyAmount, shortRef, when} from '../lib/format';
import {Button} from '../components/ui/button';
import {Card, EmptyState, Metric, SectionHeading} from '../components/ui/card';
import {ReviewDialog} from '../components/ui/dialog';
import {DataRow, Field, SelectField} from '../components/ui/form';
import {LedgerRef, Loading, QueryError, Status} from '../components/ui/status';

const blank = {name: 'TechPark One', property_type: 'COMMERCIAL_OFFICE', address: 'Demo Address, Whitefield', city: 'Bengaluru',
  country: 'India', valuation: '1000000000', proposed_supply: 100000, issue_price: '10000', description: 'Synthetic Grade-A office campus.'};
const money = /^\d{1,15}(\.\d{1,2})?$/;

export function useProperties() {
  return useApi<Page<Property>>(route.properties + '?page_size=100');
}

type PropAction = {kind: 'create' | 'submit' | 'approve' | 'reject' | 'register'; property?: Property} | null;

export function Registry() {
  const {run, submitting} = useApp();
  const props = useProperties();
  const [form, setForm] = useState(blank);
  const [action, setAction] = useState<PropAction>(null);
  const [approvedSupply, setApprovedSupply] = useState<number | ''>('');
  const [reason, setReason] = useState('Supporting evidence incomplete');
  const valid = form.name.trim().length > 2 && form.address.trim().length > 1 && form.city.trim().length > 1 &&
    money.test(form.valuation) && Number(form.valuation) > 0 && Number.isSafeInteger(form.proposed_supply) &&
    form.proposed_supply > 0 && money.test(form.issue_price) && Number(form.issue_price) > 0;
  const items = props.data?.items ?? [];
  const set = (k: keyof typeof blank) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setForm(f => ({...f, [k]: k === 'proposed_supply' ? Number(e.target.value) : e.target.value}));

  async function confirm() {
    if (!action) return;
    const p = action.property;
    if (action.kind === 'create') await run({path: route.properties, label: 'Property onboarding', body: {...form, currency: 'INR'}});
    if (action.kind === 'submit' && p) await run({path: `${route.properties}/${p.id}/submit`, label: 'Submit for approval'});
    if (action.kind === 'approve' && p) await run({path: `${route.properties}/${p.id}/approve`, label: 'Approval and DRUNIX registration',
      body: {approved_supply: approvedSupply || undefined, notes: 'Synthetic evidence reviewed'}});
    if (action.kind === 'reject' && p) await run({path: `${route.properties}/${p.id}/reject`, label: 'Rejection', body: {reason}});
    if (action.kind === 'register' && p) await run({path: `${route.properties}/${p.id}/register`, label: 'DRUNIX registration retry'});
    setAction(null);
  }

  return <>
    <SectionHeading title="Property Registry" description="Onboarding and approval are application decisions; only the approved reference and supply constraint are registered on DRUNIX."/>
    <div className="grid gap-4 lg:grid-cols-3">
      <Metric label="Properties" value={integer(items.length)} description="Synthetic demonstration records"/>
      <Metric label="Approved" value={integer(items.filter(p => p.approval_status === 'APPROVED').length)} description="Application approval"/>
      <Metric label="Registered on DRUNIX" value={integer(items.filter(p => p.ledger.registered).length)} description="Committed RegisterApprovedProperty"/>
    </div>
    <div className="mt-5 grid gap-5 xl:grid-cols-[1fr_1.4fr]">
      <Card title="Onboard a property" description="Creates a DRAFT record. Values are synthetic and illustrative.">
        <form onSubmit={e => { e.preventDefault(); if (valid) setAction({kind: 'create'}); }} className="grid gap-4 sm:grid-cols-2">
          <Field label="Property name" id="reg-name" value={form.name} onChange={set('name')} required minLength={3}/>
          <SelectField label="Property type" id="reg-type" value={form.property_type} onChange={set('property_type')}>
            <option value="COMMERCIAL_OFFICE">Commercial office</option><option value="RESIDENTIAL">Residential</option>
            <option value="INDUSTRIAL">Industrial</option><option value="RETAIL">Retail</option></SelectField>
          <Field label="Address" id="reg-address" value={form.address} onChange={set('address')} required/>
          <Field label="City" id="reg-city" value={form.city} onChange={set('city')} required/>
          <Field label="Illustrative valuation (INR)" id="reg-value" inputMode="decimal" value={form.valuation} onChange={set('valuation')}
            error={money.test(form.valuation) ? undefined : 'Up to two decimal places'}/>
          <Field label="Proposed ANSH supply" id="reg-supply" type="number" min={1} step={1} value={form.proposed_supply} onChange={set('proposed_supply')}/>
          <Field label="Issue price / ANSH (INR)" id="reg-price" inputMode="decimal" value={form.issue_price} onChange={set('issue_price')}
            error={money.test(form.issue_price) ? undefined : 'Up to two decimal places'}/>
          <Field label="Country" id="reg-country" value={form.country} onChange={set('country')}/>
          <div className="sm:col-span-2"><Button type="submit" disabled={!valid || submitting}>Review onboarding <ArrowRight size={15}/></Button></div>
        </form>
      </Card>
      <Card title="Registry" description="Application status and DRUNIX registration evidence, side by side">
        {props.isLoading ? <Loading/> : props.error ? <QueryError error={props.error}/> : !items.length
          ? <EmptyState title="No properties yet" description="Onboard TechPark One to start the demonstration."/>
          : <div className="data-table-wrap"><table className="data-table w-full">
            <thead><tr><th>Property</th><th className="money">Supply</th><th>Approval</th><th>DRUNIX registration</th><th>Actions</th></tr></thead>
            <tbody>{items.map(p => <tr key={p.id}>
              <td><p className="font-semibold">{p.name}</p><p className="text-[11px] text-slate-500">{p.city} · {inr(p.valuation, true)} · {inr(p.issue_price)}/ANSH</p>
                {p.ledger.approved_property_ref && <code className="text-[10px] text-slate-500">{p.ledger.approved_property_ref}</code>}</td>
              <td className="money">{integer(p.approved_supply ?? p.proposed_supply)}<p className="text-[10px] text-slate-400">{p.approved_supply ? 'approved' : 'proposed'}</p></td>
              <td><Status value={p.approval_status}/></td>
              <td className="text-right"><LedgerRef op={p.ledger.operation} empty="After approval"/></td>
              <td><div className="flex flex-wrap gap-1.5">
                {p.approval_status === 'DRAFT' && <Button size="sm" onClick={() => setAction({kind: 'submit', property: p})}>Submit</Button>}
                {['SUBMITTED', 'UNDER_REVIEW'].includes(p.approval_status) && <>
                  <Button size="sm" onClick={() => { setApprovedSupply(p.proposed_supply); setAction({kind: 'approve', property: p}); }}>Approve</Button>
                  <Button size="sm" variant="secondary" onClick={() => setAction({kind: 'reject', property: p})}>Reject</Button></>}
                {p.approval_status === 'APPROVED' && !p.ledger.registered && p.ledger.operation?.status === 'FAILED' &&
                  <Button size="sm" variant="secondary" onClick={() => setAction({kind: 'register', property: p})}>Retry registration</Button>}
              </div></td>
            </tr>)}</tbody></table></div>}
      </Card>
    </div>
    <ReviewDialog open={!!action} onOpenChange={v => !v && setAction(null)} onConfirm={confirm} busy={submitting} confirmLabel="Confirm"
      title={action?.kind === 'approve' ? 'Approve and register on DRUNIX' : action?.kind === 'reject' ? 'Reject property' : action?.kind === 'register' ? 'Retry DRUNIX registration' : action?.kind === 'submit' ? 'Submit for approval' : 'Onboard property'}
      description={action?.kind === 'approve' ? 'Approval is recorded in the application. The approved reference and supply are then submitted to DRUNIX (RegisterApprovedProperty); issuance needs that commit.' : 'Please confirm this action.'}>
      <dl>
        <DataRow label="Property" value={action?.property?.name ?? form.name}/>
        {action?.kind === 'create' && <><DataRow label="Illustrative valuation" value={inr(form.valuation)}/><DataRow label="Proposed supply" value={integer(form.proposed_supply)}/><DataRow label="Issue price" value={inr(form.issue_price)}/></>}
      </dl>
      {action?.kind === 'approve' && <div className="mt-3"><Field label="Approved supply (ANSH)" id="approve-supply" type="number" min={1} step={1}
        value={approvedSupply} onChange={e => setApprovedSupply(e.target.value ? Number(e.target.value) : '')}/></div>}
      {action?.kind === 'reject' && <div className="mt-3"><Field label="Reason" id="reject-reason" value={reason} onChange={e => setReason(e.target.value)}/></div>}
    </ReviewDialog>
  </>;
}

export function Issuance() {
  const {run, submitting, session} = useApp();
  const props = useProperties();
  const issuances = useApi<Page<Issuance>>(route.issuances + '?page_size=100');
  const listings = useApi<Page<Listing>>(route.listings + '?page_size=100');
  const eligible = (props.data?.items ?? []).filter(p => p.approval_status === 'APPROVED' && p.ledger.registered && p.issuance?.status !== 'CONFIRMED');
  const [propertyId, setPropertyId] = useState('');
  const selected = eligible.find(p => p.id === propertyId) ?? eligible[0];
  const [quantity, setQuantity] = useState<number | ''>('');
  const qty = quantity === '' ? selected?.approved_supply ?? 0 : quantity;
  const [open, setOpen] = useState<null | 'issue' | Issuance>(null);
  const [listQty, setListQty] = useState(100000);
  const valid = !!selected && Number.isSafeInteger(qty) && qty > 0 && qty <= (selected.approved_supply ?? 0);
  const myListed = (id: string) => (listings.data?.items ?? []).filter(l => l.issuance_id === id && l.seller.id === session?.userId)
    .reduce((s, l) => s + l.remaining_quantity, 0);

  async function confirm() {
    if (open === 'issue' && selected) await run({path: route.issuances, label: 'ANSH issuance', body: {property_id: selected.id, quantity: qty, currency: 'INR'}});
    else if (open && open !== 'issue') await run({path: route.listings, label: 'Primary listing', body: {issuance_id: open.id, quantity: listQty, currency: 'INR'}});
    setOpen(null);
  }

  return <>
    <SectionHeading title="ANSH Issuance" description="Issue only against an approved property whose DRUNIX registration has committed. Issued supply counts only after the IssueANSH commit."/>
    <div className="grid gap-5 xl:grid-cols-[1fr_1.4fr]">
      <Card title="Initiate issuance" description="Quantity cannot exceed the approved supply (also enforced by the backend and chaincode)">
        {!eligible.length ? <EmptyState title="No property ready for issuance" description="A property must be approved and its DRUNIX registration committed."/> :
          <form className="space-y-4" onSubmit={e => { e.preventDefault(); if (valid) setOpen('issue'); }}>
            <SelectField label="Property" id="issue-prop" value={selected?.id} onChange={e => { setPropertyId(e.target.value); setQuantity(''); }}>
              {eligible.map(p => <option key={p.id} value={p.id}>{p.name} · {p.ledger.approved_property_ref}</option>)}</SelectField>
            <Field id="issue-quantity" label="Quantity (ANSH)" type="number" min={1} max={selected?.approved_supply ?? undefined} step={1}
              value={qty} onChange={e => setQuantity(e.target.value ? Number(e.target.value) : '')}
              error={selected && qty > (selected.approved_supply ?? 0) ? 'Exceeds the approved supply' : undefined}/>
            <dl><DataRow label="Approved supply" value={integer(selected?.approved_supply)}/><DataRow label="Issue price" value={inr(selected?.issue_price)}/>
              <DataRow label="Issuance value" value={inr(multiplyAmount(qty, selected?.issue_price ?? ''))}/>
              <DataRow label="Registration tx" value={<code title={selected?.ledger.registration_transaction_id ?? ''}>{shortRef(selected?.ledger.registration_transaction_id, 14)}</code>}/></dl>
            <Button type="submit" disabled={!valid || submitting}>Review issuance <ArrowRight size={15}/></Button>
          </form>}
      </Card>
      <Card title="Issuances" description="Business status beside DRUNIX finality">
        {issuances.isLoading ? <Loading/> : issuances.error ? <QueryError error={issuances.error}/> : !issuances.data?.items.length
          ? <EmptyState title="No issuances" description="Issue ANSH for a registered property."/>
          : <div className="data-table-wrap"><table className="data-table w-full">
            <thead><tr><th>Asset</th><th className="money">Issued / approved</th><th>Status</th><th>DRUNIX</th><th>Market</th></tr></thead>
            <tbody>{issuances.data.items.map(i => <tr key={i.id}>
              <td><p className="font-semibold">{i.property_name}</p><code className="text-[10px] text-slate-500">{i.ansh_asset_id}</code></td>
              <td className="money">{integer(i.issued_quantity)} / {integer(i.approved_supply)}</td>
              <td><Status value={i.status}/></td><td className="text-right"><LedgerRef op={i.operation}/></td>
              <td>{i.status === 'CONFIRMED' && i.issuer.id === session?.userId
                ? <Button size="sm" variant="secondary" onClick={() => { setListQty(Math.max(1, i.issued_quantity - myListed(i.id))); setOpen(i); }}>List for sale</Button>
                : <span className="text-xs text-slate-400">—</span>}
                {myListed(i.id) > 0 && <p className="mt-1 text-[10px] text-slate-500">{integer(myListed(i.id))} listed</p>}</td>
            </tr>)}</tbody></table></div>}
      </Card>
    </div>
    <ReviewDialog open={!!open} onOpenChange={v => !v && setOpen(null)} onConfirm={confirm} busy={submitting}
      title={open === 'issue' ? 'Review ANSH issuance' : 'Create primary listing'} confirmLabel={open === 'issue' ? 'Submit IssueANSH' : 'Create listing'}
      description={open === 'issue' ? 'Submitted to DRUNIX. Success is shown only after a confirmed commit with its transaction id.' : 'The backend checks your available balance on DRUNIX before listing.'}>
      {open === 'issue' ? <dl><DataRow label="Property" value={selected?.name}/><DataRow label="Quantity" value={integer(qty) + ' ANSH'}/>
        <DataRow label="Issue price" value={inr(selected?.issue_price)}/></dl>
        : open && <><dl><DataRow label="Asset" value={open.ansh_asset_id}/><DataRow label="Price / ANSH" value={inr(open.issue_price)}/></dl>
          <div className="mt-3"><Field label="Quantity to list" id="list-qty" type="number" min={1} step={1} value={listQty} onChange={e => setListQty(Number(e.target.value))}/></div></>}
    </ReviewDialog>
  </>;
}

export function Marketplace() {
  const {role, run, submitting} = useApp();
  const listings = useApi<Page<Listing>>(route.listings + '?page_size=100');
  const orders = useApi<Page<Order>>(route.orders + '?page_size=50');
  const [listingId, setListingId] = useState('');
  const items = listings.data?.items ?? [];
  const listing = items.find(l => l.id === listingId) ?? items[0];
  const [quantity, setQuantity] = useState(500);
  const [stage, setStage] = useState<null | 'order' | Order>(null);
  const [outcome, setOutcome] = useState<'SUCCESS' | 'FAILED'>('SUCCESS');
  const isInvestor = role === 'INVESTOR';
  const valid = !!listing && Number.isSafeInteger(quantity) && quantity > 0 && quantity <= listing.remaining_quantity;

  async function confirm() {
    if (stage === 'order' && listing) {
      const order = await run<Order>({path: route.orders, label: 'Purchase order', body: {listing_id: listing.id, quantity, currency: 'INR'}});
      setOutcome('SUCCESS');  // each new payment starts from "succeeds"; failure must be chosen deliberately
      setStage(order && order.status === 'PAYMENT_PENDING' ? order : null);
      return;
    }
    if (stage && stage !== 'order') await run({path: route.payments, label: 'Simulated payment and ANSH transfer',
      body: {order_id: stage.id, simulated_outcome: outcome}});
    setStage(null);
  }

  return <>
    <SectionHeading title="Marketplace" description="Payment is simulated and separate from the DRUNIX transfer; ownership changes only after a confirmed commit. No atomic delivery-versus-payment is claimed."/>
    <div className="grid gap-5 xl:grid-cols-[1.3fr_1fr]">
      <Card title="Open listings" description="Synthetic properties · prices in INR">
        {listings.isLoading ? <Loading/> : listings.error ? <QueryError error={listings.error}/> : !items.length
          ? <EmptyState title="No open listings" description="The issuer lists ANSH after a confirmed issuance."/>
          : <div className="data-table-wrap"><table className="data-table w-full">
            <thead><tr><th>Asset</th><th>Seller</th><th className="money">Remaining</th><th className="money">Price</th><th>Status</th></tr></thead>
            <tbody>{items.map(l => <tr key={l.id} className={l.id === listing?.id ? 'bg-blue-50/50' : ''}>
              <td><button className="text-left font-semibold text-[#1769AA] hover:underline" onClick={() => setListingId(l.id)}>{l.property.name}</button>
                <p className="text-[11px] text-slate-500">{l.property.city} · {l.property.property_type.replaceAll('_', ' ').toLowerCase()}</p></td>
              <td>{l.seller.name}</td><td className="money">{integer(l.remaining_quantity)}</td><td className="money">{inr(l.unit_price)}</td>
              <td><Status value={l.status}/></td></tr>)}</tbody></table></div>}
      </Card>
      {isInvestor && <Card title="Buy ANSH" description="Step 1: order · Step 2: simulated payment · Step 3: DRUNIX transfer">
        {!listing ? <EmptyState title="Nothing to buy" description="No open listing."/> :
          <form className="space-y-4" onSubmit={e => { e.preventDefault(); if (valid) setStage('order'); }}>
            <Field id="order-asset" label="Asset" value={listing.property.name} readOnly/>
            <Field id="order-quantity" label="Quantity (ANSH)" type="number" min={1} max={listing.remaining_quantity} step={1} value={quantity}
              onChange={e => setQuantity(Number(e.target.value))} error={quantity > listing.remaining_quantity ? 'Exceeds remaining listing quantity' : undefined}/>
            <dl><DataRow label="Price / ANSH" value={inr(listing.unit_price)}/><DataRow label="Estimated amount" value={inr(multiplyAmount(quantity, listing.unit_price))}/>
              <DataRow label="Authoritative amount" value="Calculated by the backend"/></dl>
            <Button type="submit" disabled={!valid || submitting}>Review order <ArrowRight size={15}/></Button>
          </form>}
      </Card>}
    </div>
    <Card className="mt-5" title={isInvestor ? 'My orders' : 'Orders'} description="Order, simulated payment and DRUNIX transfer states are tracked separately">
      {orders.isLoading ? <Loading/> : !orders.data?.items.length ? <EmptyState title="No orders" description="Orders appear here once placed."/> :
        <div className="data-table-wrap"><table className="data-table w-full">
          <thead><tr><th>Order</th><th className="money">Qty</th><th className="money">Amount</th><th>Order status</th><th>Payment (simulated)</th><th>DRUNIX transfer</th><th/></tr></thead>
          <tbody>{orders.data.items.map(o => <tr key={o.id}>
            <td><p className="font-semibold">{o.property_name}</p><p className="text-[11px] text-slate-500">{o.buyer.name} ← {o.seller.name} · {when(o.created_at)}</p>
              {o.failure_reason && <p className="text-[11px] text-red-700">{o.failure_reason}</p>}</td>
            <td className="money">{integer(o.quantity)}</td><td className="money">{inr(o.total_amount)}</td><td><Status value={o.status}/></td>
            <td>{o.payments.length ? o.payments.map(p => <div key={p.id} className="mb-1 flex items-center gap-1.5"><Status value={p.status}/>
              <span className="text-[10px] text-slate-500">{p.kind} · {p.reference}</span></div>) : <span className="text-xs text-slate-400">Not paid</span>}</td>
            <td className="text-right"><LedgerRef op={o.transfer}/></td>
            <td>{isInvestor && o.status === 'PAYMENT_PENDING' && <Button size="sm" onClick={() => { setOutcome('SUCCESS'); setStage(o); }}>Pay</Button>}</td>
          </tr>)}</tbody></table></div>}
    </Card>
    <ReviewDialog open={!!stage} onOpenChange={v => !v && setStage(null)} onConfirm={confirm} busy={submitting}
      title={stage === 'order' ? 'Review purchase order' : 'Simulated payment'} confirmLabel={stage === 'order' ? 'Place order' : 'Run simulated payment'}
      description={stage === 'order' ? 'Placing an order does not take payment or move ownership.' : 'SIMULATED payment. On success the backend submits TransferANSH to DRUNIX; on failure no transfer is submitted.'}>
      {stage === 'order' && listing && <dl><DataRow label="Asset" value={listing.property.name}/><DataRow label="Quantity" value={integer(quantity) + ' ANSH'}/>
        <DataRow label="Estimated amount" value={inr(multiplyAmount(quantity, listing.unit_price))}/></dl>}
      {stage && stage !== 'order' && <><dl><DataRow label="Order" value={stage.property_name + ' · ' + integer(stage.quantity) + ' ANSH'}/>
        <DataRow label="Amount (backend)" value={inr(stage.total_amount)}/></dl>
        <fieldset className="mt-3 space-y-2"><legend className="mb-1 text-xs font-semibold text-[#102B4E]">Payment simulator outcome</legend>
          {(['SUCCESS', 'FAILED'] as const).map(o => <label key={o} className="flex items-center gap-2 text-sm">
            <input type="radio" name="pay-outcome" checked={outcome === o} onChange={() => setOutcome(o)}/>{o === 'SUCCESS' ? 'Payment succeeds' : 'Payment fails (no transfer)'}</label>)}
        </fieldset></>}
    </ReviewDialog>
  </>;
}
