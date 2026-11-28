import {Landmark,ArrowUpRight} from 'lucide-react';
import {Link} from 'react-router-dom';
import {useApp} from '../app/context';
import {Card} from './ui/card';
import {DataRow} from './ui/form';
import {reitHoldingsFor,reitTotals,yieldBps,percent,entitlement} from '../demo/investments';
import {moneyINR} from '../api/financing';

export function ReitHoldingsCard(){
 const {session}=useApp();
 const holdings=reitHoldingsFor(session?.user_id),totals=reitTotals(holdings);
 return <Card title="Tokenized REIT representations" description="Illustrative fund-unit positions · separate asset class from ANSH" action={<span className="rounded-full bg-slate-100 px-3 py-1 text-[10px] font-bold text-slate-600">ILLUSTRATIVE</span>}>
  <div className="mb-4 flex items-center gap-3 rounded-lg bg-slate-50 p-4"><Landmark size={23} className="text-[#1769AA]"/><div><p className="font-financial text-xl font-bold text-[#102B4E]">{moneyINR(totals.nav_minor)}</p><p className="mt-1 text-xs text-slate-500">Illustrative REIT subtotal · {totals.units} represented units</p></div></div>
  <div className="space-y-3">{holdings.map(fund=><details key={fund.id} className="rounded-lg border border-slate-200 p-4"><summary className="cursor-pointer text-sm font-semibold text-[#102B4E]">{fund.fund_name}<span className="mt-1 block text-xs font-normal text-slate-500">{fund.category} · {fund.units} units · illustrative yield {percent(yieldBps(fund.nav_minor,fund.quarterly_distribution_minor))}</span></summary><dl className="mt-3 text-xs"><DataRow label="Illustrative NAV / unit" value={moneyINR(fund.nav_minor)}/><DataRow label="Illustrative position value" value={moneyINR(entitlement(fund.units,fund.nav_minor))}/><DataRow label="Quarterly distribution / unit · estimate" value={moneyINR(fund.quarterly_distribution_minor)}/><DataRow label="Trading availability" value="Not integrated · representation only"/><DataRow label="ANSH financing eligibility" value="Not eligible"/></dl></details>)}</div>
  <p className="mt-4 text-xs leading-5 text-slate-500">Underlying REIT market trading follows applicable exchange hours. This representation does not enable unrestricted 24/7 trading. No live blockchain-issued REIT units, custodian or market feed is connected.</p>
  <div className="mt-4 border-t border-slate-100 pt-3 text-xs text-slate-600">Consolidated live portfolio value: unavailable without a live ANSH price. ANSH units are not added to REIT units or counted in this subtotal.</div>
  <Link to="/intelligence" className="mt-4 inline-flex items-center gap-1 text-xs font-bold text-[#1769AA]">Research assumptions <ArrowUpRight size={13}/></Link>
 </Card>;
}
export function ReitIncomeCard(){const {session}=useApp();const holdings=reitHoldingsFor(session?.user_id),totals=reitTotals(holdings);return <Card title="REIT distribution estimates" description="Illustrative quarterly income · no executed REIT payouts"><dl>{holdings.map(f=><DataRow key={f.id} label={f.fund_name} value={moneyINR(entitlement(f.units,f.quarterly_distribution_minor))}/>)}<DataRow label="Combined REIT estimate" value={moneyINR(totals.quarterly_income_minor)}/></dl><p className="mt-3 text-xs text-slate-500">Based on simulated units and fixed illustrative rates. Kept separate from ANSH rental income.</p></Card>;}
