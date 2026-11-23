import test from 'node:test';
import assert from 'node:assert/strict';
import {reitHoldings,reitTotals,yieldBps,percent,entitlement,allocation,incomeSnapshot,recordPayout,readPayouts,payoutSlot,researchScenario} from '../src/demo/investments.ts';
import {captureIncomeSnapshot} from '../src/api/income.ts';
import {investorDemo as ids} from '../src/api/transfers.ts';
const aarav='00000000-0000-4000-8000-000000000003';
const id='70000000-0000-4000-8000-000000000001',time='2026-11-20T12:00:00Z';
const storage=()=>{const rows=new Map();return {getItem:key=>rows.get(key)||null,setItem:(key,value)=>rows.set(key,value)};};

test('REIT units, NAV and income totals are internally consistent without valuing live ANSH',()=>{
 const totals=reitTotals();
 assert.equal(totals.units,205);assert.equal(totals.nav_minor,'6000000');
 assert.equal(totals.quarterly_income_minor,'104000');assert.equal(totals.annual_income_minor,'416000');
 assert.equal(totals.consolidated_live_value_minor,null);
 assert.deepEqual(reitHoldings.map(f=>percent(yieldBps(f.nav_minor,f.quarterly_distribution_minor))),['7.20%','6.40%']);
 assert.ok(reitHoldings.every(v=>v.asset_class==='REIT'&&v.representation==='SIMULATED'));
 assert.throws(()=>reitTotals([reitHoldings[0],reitHoldings[0]]),/Ambiguous/);
});
test('illustrative distributions preserve integer paise, including large quantities and pool rounding',()=>{
 assert.equal(entitlement(2,'10000'),'20000');
 assert.equal(entitlement(9007199254740991,'101'),'909727124728840091');
 assert.equal(allocation('101',1,2),'50');
 assert.throws(()=>entitlement(1.5,'100'));assert.throws(()=>entitlement(1,'1.2'));assert.throws(()=>allocation('100',3,2));
 const snapshot=incomeSnapshot(id,aarav,ids.property,2,'10000',time,'DRUNIX_CURRENT_BALANCE');
 assert.equal(snapshot.lines[0].entitlement_minor,'20000');
 assert.equal(snapshot.total_minor,'124000');
 assert.equal(snapshot.lines.filter(v=>v.asset_class==='REIT').length,2);
});
test('review captures a fresh balance via GET, preserves source and refuses unavailable or malformed reads',async()=>{
 const calls=[];
 const snapshot=await captureIncomeSnapshot(async(path,options)=>{
  calls.push({path,options});return {schema_version:1,property_id:ids.property,holder_id:aarav,quantity:1,source:'DRUNIX_EVALUATE'};
 },aarav,'10000',id,()=>time);
 assert.equal(snapshot.lines[0].units,1);assert.equal(snapshot.observed_at,time);
 assert.equal(snapshot.ownership_source,'DRUNIX_CURRENT_BALANCE');assert.equal(calls.length,1);
 assert.equal(calls[0].options.method,'GET');assert.equal(calls[0].options.demoRole,undefined);
 assert.equal(calls[0].options.body,undefined);assert.equal(calls[0].options.Authorization,undefined);
 await assert.rejects(captureIncomeSnapshot(async()=>{throw new Error('test-only unavailable');},aarav,'10000',id));
 await assert.rejects(captureIncomeSnapshot(async()=>({quantity:2,source:'UI_PREVIEW'}),aarav,'10000',id));
});
test('history is empty until explicit local completion; repeated confirmation cannot double-count',()=>{
 const store=storage(),snapshot=incomeSnapshot(id,aarav,ids.property,2,'10000',time,'DRUNIX_CURRENT_BALANCE');
 assert.deepEqual(readPayouts(store,aarav,ids.property,'DRUNIX_CURRENT_BALANCE'),[]);
 const rows=recordPayout(store,snapshot,'2026-11-20T12:01:00Z');
 assert.equal(rows.length,1);assert.equal(rows[0].status,'SIMULATED_COMPLETED');
 assert.equal(rows[0].total_minor,'124000');assert.equal('transaction_id' in rows[0],false);
 assert.equal(recordPayout(store,snapshot,'2026-11-20T12:02:00Z').length,1);
 assert.equal(readPayouts(store,aarav,ids.property,'UI_PREVIEW').length,0);
 const conflicted=incomeSnapshot(id,aarav,ids.property,3,'10000',time,'DRUNIX_CURRENT_BALANCE');
 assert.throws(()=>recordPayout(store,conflicted,'2026-11-20T12:02:00Z'),/Conflicting/);
 assert.throws(()=>recordPayout(store,snapshot,'2026-11-20T11:00:00Z'),/Invalid/);
});
test('corrupted history and storage failure never become completed payout records',()=>{
 const store=storage(),snapshot=incomeSnapshot(id,aarav,ids.property,2,'10000',time,'DRUNIX_CURRENT_BALANCE');
 const slot=payoutSlot('DRUNIX_CURRENT_BALANCE',aarav);
 store.setItem(slot,JSON.stringify([{...snapshot,status:'SIMULATED_COMPLETED',completed_at:time,total_minor:'1'}]));
 assert.throws(()=>readPayouts(store,aarav,ids.property,'DRUNIX_CURRENT_BALANCE'));
 assert.throws(()=>recordPayout({getItem:()=>null,setItem:()=>{throw new Error('unavailable');}},snapshot,time));
});
test('research insight rules and rental sensitivity are deterministic and sourced as assumptions',()=>{
 const value=researchScenario('100','94','8.2');
 assert.equal(value.valuation_minor,'100000000000');assert.equal(value.gross_rent_minor,'8200000000');
 assert.equal(value.occupancy_adjusted_rent_minor,'7708000000');
 assert.match(researchScenario('125','80','10').insights.join(' '),/vacancy sensitivity/);
 assert.equal(researchScenario('125','80','10').risks[2].level,'Higher sensitivity');
 assert.deepEqual(researchScenario('100','94','8.2'),value);
 assert.match(value.insights.join(' '),/not a declared distribution/);
 for(const args of [['0','94','8.2'],['100','101','8.2'],['100','94','NaN']])assert.throws(()=>researchScenario(...args));
});
