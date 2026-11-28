import test from 'node:test';
import assert from 'node:assert/strict';
import {filterActivity,lenderSummary,rangeCutoff,eventCount} from '../src/api/lenderActivity.ts';

const loan=(id,state='DISBURSED',property_id='f6169750-4676-4e99-887f-2bc5471bd518')=>({
 id,borrower_id:'00000000-0000-4000-8000-000000000003',property_id,asset_class:'ANSH',quantity:10,
 unit_value_minor:'100000',ltv_percent:60,annual_rate_bps:1200,term_months:12,lender_id:'axim-bank',
 type:'SIMULATED_FINANCING',simulated:true,on_chain_lock:false,reservation_active:state==='DISBURSED',
 collateral_value_minor:'1000000',principal_minor:'600000',interest_minor:'72000',repayment_minor:'672000',
 outstanding_principal_minor:state==='DISBURSED'?'600000':'0',amount_due_minor:state==='DISBURSED'?'672000':'0',
 created_at:'2026-11-20T10:00:00Z',updated_at:'2026-11-22T10:00:00Z',assessment:null,
 timeline:[
  {state:'APPLIED',timestamp:'2026-11-20T10:00:00Z',actor_role:'INVESTOR',simulated:true},
  {state:'APPROVED',timestamp:'2026-11-21T10:00:00Z',actor_role:'LENDER',simulated:true},
  ...(state==='DISBURSED'?[{state:'DISBURSED',timestamp:'2026-11-22T10:00:00Z',actor_role:'LENDER',simulated:true}]:[])
 ]
});

test('lender activity summarizes distinct applications and lifecycle money without double counting',()=>{
 const result=lenderSummary([loan('70000000-0000-4000-8000-000000000001')],rangeCutoff('ALL',Date.parse('2026-11-30T00:00:00Z')));
 assert.deepEqual(result,{applications:1,approved:1,disbursed:1,disbursedMinor:'600000',repaid:0,repaidMinor:'0'});
 assert.equal(eventCount([loan('70000000-0000-4000-8000-000000000001')],'ALL',null),1);
 assert.equal(eventCount([loan('70000000-0000-4000-8000-000000000001')],'DISBURSED',null),1);
});

test('current status categories are mutually exclusive and keep closed repayment distinct in history',()=>{
 const approved=loan('70000000-0000-4000-8000-000000000004','APPROVED');
 const closed=loan('70000000-0000-4000-8000-000000000005','REPAID');
 closed.timeline=[...closed.timeline,{state:'REPAID',timestamp:'2026-11-23T10:00:00Z',actor_role:'INVESTOR',simulated:true}];
 const records=[approved,closed];
 assert.equal(eventCount(records,'APPROVED',null),1);
 assert.equal(eventCount(records,'CLOSED',null),1);
 assert.equal(eventCount(records,'DISBURSED',null),0);
 assert.equal(eventCount(records,'ALL',null),2);
 assert.equal(closed.timeline.at(-1).state,'REPAID');
});

test('lender activity filters by event and searchable property metadata',()=>{
 const first=loan('70000000-0000-4000-8000-000000000001');
 const second=loan('70000000-0000-4000-8000-000000000002','APPROVED','f6169750-4676-4e99-887f-2bc5471bd519');
 second.timeline=second.timeline.filter(event=>event.state!=='DISBURSED');
 const rows=filterActivity([first,second],'green','ALL',null,{'f6169750-4676-4e99-887f-2bc5471bd519':{name:'Green Acres Farmland',location:'Nashik',ansh_symbol:'ANSH-GREEN'}});
 assert.deepEqual(rows.map(value=>value.id),[second.id]);
});

test('date scope excludes lifecycle events outside the selected reporting period',()=>{
 const value=loan('70000000-0000-4000-8000-000000000003');
 assert.equal(lenderSummary([value],rangeCutoff('7',Date.parse('2026-12-01T00:00:00Z'))).applications,0);
 assert.equal(lenderSummary([value],rangeCutoff('ALL',Date.parse('2026-12-01T00:00:00Z'))).applications,1);
 assert.equal(eventCount([value],'ALL',rangeCutoff('7',Date.parse('2026-12-01T00:00:00Z'))),0);
});
