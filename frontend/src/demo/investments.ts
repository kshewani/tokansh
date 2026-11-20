/** Curated M6 illustrations, never an external feed or ledger implementation. */
import {isRecord} from '../api/client.ts';
export type ReitHolding={id:string;asset_class:'REIT';fund_name:string;units:number;nav_minor:string;quarterly_distribution_minor:string;category:string;representation:'SIMULATED'};
export const reitHoldings:readonly ReitHolding[]=[
 {id:'SIM-REIT-OFFICE',asset_class:'REIT',fund_name:'Illustrative Indian REIT · Offices',units:125,nav_minor:'32000',quarterly_distribution_minor:'576',category:'Commercial offices',representation:'SIMULATED'},
 {id:'SIM-REIT-LOGISTICS',asset_class:'REIT',fund_name:'Illustrative Logistics REIT',units:80,nav_minor:'25000',quarterly_distribution_minor:'400',category:'Logistics & industrial',representation:'SIMULATED'}
];
const minor=(v:unknown):v is string=>typeof v==='string'&&/^(0|[1-9][0-9]*)$/.test(v);
const units=(v:unknown):v is number=>typeof v==='number'&&Number.isSafeInteger(v)&&v>=0;
const instant=(v:unknown):v is string=>typeof v==='string'&&Number.isFinite(Date.parse(v));
export function entitlement(quantity:number,rateMinor:string){
 if(!units(quantity)||!minor(rateMinor))throw new Error('Invalid illustrative income inputs.');
 return String(BigInt(quantity)*BigInt(rateMinor));
}
export function allocation(totalMinor:string,owned:number,supply:number){
 if(!minor(totalMinor)||!units(owned)||!units(supply)||supply<1||owned>supply)throw new Error('Invalid scenario allocation.');
 return String(BigInt(totalMinor)*BigInt(owned)/BigInt(supply));
}
export function yieldBps(navMinor:string,quarterlyRateMinor:string){
 if(!minor(navMinor)||BigInt(navMinor)<1n||!minor(quarterlyRateMinor))throw new Error('Invalid illustrative NAV.');
 return Number((BigInt(quarterlyRateMinor)*4n*10000n+BigInt(navMinor)/2n)/BigInt(navMinor));
}
export function percent(bps:number){if(!Number.isSafeInteger(bps)||bps<0)throw new Error('Invalid rate.');return Math.floor(bps/100)+'.'+String(bps%100).padStart(2,'0')+'%';}
export function reitTotals(holdings:readonly ReitHolding[]=reitHoldings){
 const seen=new Set<string>();let count=0,nav=0n,quarterly=0n;
 for(const fund of holdings){
  if(fund.asset_class!=='REIT'||fund.representation!=='SIMULATED'||seen.has(fund.id)||!units(fund.units)||!minor(fund.nav_minor)||!minor(fund.quarterly_distribution_minor))throw new Error('Ambiguous REIT illustration.');
  seen.add(fund.id);count+=fund.units;if(!Number.isSafeInteger(count))throw new Error('Invalid unit total.');
  nav+=BigInt(entitlement(fund.units,fund.nav_minor));quarterly+=BigInt(entitlement(fund.units,fund.quarterly_distribution_minor));
 }
 return {units:count,nav_minor:String(nav),quarterly_income_minor:String(quarterly),annual_income_minor:String(quarterly*4n),consolidated_live_value_minor:null};
}
export type IncomeLine={asset_id:string;asset_class:'ANSH'|'REIT';label:string;units:number;rate_minor:string;entitlement_minor:string};
export type IncomeSnapshot={id:string;holder_id:string;observed_at:string;ownership_source:'DRUNIX_CURRENT_BALANCE'|'UI_PREVIEW';lines:IncomeLine[];total_minor:string};
export type SimulatedPayout=IncomeSnapshot&{status:'SIMULATED_COMPLETED';completed_at:string};
export function incomeSnapshot(id:string,holder:string,property:string,quantity:number,rate:string,observedAt:string,source:IncomeSnapshot['ownership_source']):IncomeSnapshot{
 if(!instant(observedAt))throw new Error('Snapshot time is unavailable.');
 const lines:IncomeLine[]=[{asset_id:property,asset_class:'ANSH',label:'TechPark One · ANSH',units:quantity,rate_minor:rate,entitlement_minor:entitlement(quantity,rate)},
  ...reitHoldings.map(f=>({asset_id:f.id,asset_class:'REIT' as const,label:f.fund_name,units:f.units,rate_minor:f.quarterly_distribution_minor,entitlement_minor:entitlement(f.units,f.quarterly_distribution_minor)}))];
 return {id,holder_id:holder,observed_at:observedAt,ownership_source:source,lines,total_minor:String(lines.reduce((sum,line)=>sum+BigInt(line.entitlement_minor),0n))};
}
function validatePayout(value:unknown,holder:string,property:string,source:IncomeSnapshot['ownership_source']):SimulatedPayout{
 if(!isRecord(value)||typeof value.id!=='string'||!/^[0-9a-f-]{36}$/.test(value.id)||value.holder_id!==holder||value.ownership_source!==source||value.status!=='SIMULATED_COMPLETED'||!instant(value.observed_at)||!instant(value.completed_at)||Date.parse(value.completed_at)<Date.parse(value.observed_at)||!Array.isArray(value.lines)||value.lines.length!==3)throw new Error('Invalid browser simulation history.');
 const line=value.lines[0];
 if(!isRecord(line)||!units(line.units)||!minor(line.rate_minor))throw new Error('Invalid browser simulation history.');
 const expected=incomeSnapshot(value.id,holder,property,line.units,line.rate_minor,value.observed_at,source);
 if(value.total_minor!==expected.total_minor||!value.lines.every((line,i)=>isRecord(line)&&Object.entries(expected.lines[i]).every(([k,v])=>line[k]===v)))throw new Error('Inconsistent browser simulation history.');
 return value as SimulatedPayout;
}
type Store=Pick<Storage,'getItem'|'setItem'>;
export function payoutSlot(source:IncomeSnapshot['ownership_source'],holder:string){return 'tokansh-income-v1:'+source+':'+holder;}
export function readPayouts(store:Store,holder:string,property:string,source:IncomeSnapshot['ownership_source']):SimulatedPayout[]{
 const raw=store.getItem(payoutSlot(source,holder));if(!raw)return [];
 const values:unknown=JSON.parse(raw);if(!Array.isArray(values)||values.length>20)throw new Error('Invalid browser simulation history.');
 const rows=values.map(v=>validatePayout(v,holder,property,source));
 if(new Set(rows.map(v=>v.id)).size!==rows.length)throw new Error('Duplicate browser simulation receipt.');
 return rows;
}
export function recordPayout(store:Store,snapshot:IncomeSnapshot,completedAt:string){
 const row=validatePayout({...snapshot,status:'SIMULATED_COMPLETED',completed_at:completedAt},snapshot.holder_id,snapshot.lines[0].asset_id,snapshot.ownership_source);
 const rows=readPayouts(store,row.holder_id,row.lines[0].asset_id,row.ownership_source),existing=rows.find(v=>v.id===row.id);
 if(existing){
  if(JSON.stringify({...existing,completed_at:''})!==JSON.stringify({...row,completed_at:''}))throw new Error('Conflicting simulation reference.');
  return rows;
 }
 const next=[row,...rows].slice(0,20);store.setItem(payoutSlot(row.ownership_source,row.holder_id),JSON.stringify(next));return next;
}
export function researchScenario(valueCrore:string,occupancy:string,yieldPercent:string){
 if(!/^[1-9][0-9]{0,2}$/.test(valueCrore)||!/^([0-9]|[1-9][0-9]|100)$/.test(occupancy)||!/^([0-9]|[12][0-9])(\.[0-9]{1,2})?$/.test(yieldPercent))throw new Error('Enter valid illustrative research assumptions.');
 const value=BigInt(valueCrore)*1000000000n; // One crore INR in paise.
 const [whole,fraction='']=yieldPercent.split('.'),bps=Number(whole)*100+Number(fraction.padEnd(2,'0'));
 const gross=value*BigInt(bps)/10000n,adjusted=gross*BigInt(occupancy)/100n;
 return {valuation_minor:String(value),gross_rent_minor:String(gross),occupancy_adjusted_rent_minor:String(adjusted),yield_bps:bps,
  risks:[{title:'Liquidity',level:'Elevated',reason:'Transfers are supported, but no guaranteed buyer, matching engine or exit liquidity is assumed.'},
   {title:'Concentration',level:'Focused',reason:'The displayed ANSH position references one property. Simulated REIT holdings are a separate analytical illustration.'},
   {title:'Valuation',level:Number(valueCrore)>120?'Higher sensitivity':'Unverified',reason:'The valuation is an editable scenario assumption, not an independent appraisal.'}],
  insights:[Number(occupancy)<85?'Lower assumed occupancy increases vacancy sensitivity.':'The occupancy assumption supports the rent model; no lease roll has been verified.',
   bps>900?'Higher assumed yield increases the need to test costs and collection risk.':'Gross yield excludes fees, taxes and collection losses.',
   'Modelled rent is not a declared distribution, investor entitlement or forecast of actual performance.']};
}
