import test from 'node:test';
import assert from 'node:assert/strict';
import {registerHooks} from 'node:module';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
import {createElement as h} from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {MemoryRouter} from 'react-router-dom';
import {RequestError} from '../src/api/client.ts';

// Use the existing TypeScript compiler for JSX; no new test dependencies.
registerHooks({
 resolve(specifier,context,next){
  try{return next(specifier,context);}catch(error){
   if(specifier.startsWith('.')&&!/\.[a-z]+$/i.test(specifier)){
    for(const extension of ['.ts','.tsx']){
     try{return next(specifier+extension,context);}catch{}
    }
   }
   throw error;
  }
 },
 load(url,context,next){
  if(url.endsWith('.tsx'))return {format:'module',shortCircuit:true,source:ts.transpileModule(readFileSync(new URL(url),'utf8'),{
   compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}
  }).outputText};
  return next(url,context);
 }
});
const {ConnectedBoundary}=await import('../src/components/ConnectedBoundary.tsx');
const {SystemStatusView}=await import('../src/components/SystemStatus.tsx');
const props={mode:'real',configured:true,data:null,loading:false,error:null,retry:()=>{}};
const renderStatus=(overrides={})=>renderToStaticMarkup(h(SystemStatusView,{...props,...overrides}));

test('connected business boundary does not render fixture children; preview renders them unchanged',()=>{
 function Fixture(){return h('div',null,'500 ANSH PREVIEW-001');}
 for(const mode of ['real','preview']){
  const html=renderToStaticMarkup(h(MemoryRouter,null,h(ConnectedBoundary,{mode,path:'/registry',title:'Registry'},h(Fixture))));
  if(mode==='real'){
   assert.match(html,/not integrated yet/);assert.doesNotMatch(html,/500 ANSH|PREVIEW-001/);
  }else assert.match(html,/500 ANSH PREVIEW-001/);
 }
});
test('System Status remains accessible through the connected boundary',()=>{
 const html=renderToStaticMarkup(h(MemoryRouter,null,h(ConnectedBoundary,{mode:'real',path:'/system',title:'System Status'},h(SystemStatusView,props))));
 assert.match(html,/Infrastructure components/);assert.doesNotMatch(html,/not integrated yet/);
});
test('status view renders loading, configuration failure, malformed-response feedback and retry',()=>{
 assert.match(renderStatus({loading:true}),/Checking API status/);
 assert.match(renderStatus({configured:false}),/API URL is missing/);
 const html=renderStatus({error:new RequestError(200,'MALFORMED_RESPONSE','Invalid status data.')});
 assert.match(html,/role="alert"/);assert.match(html,/MALFORMED_RESPONSE/);assert.match(html,/Retry status check/);
 assert.match(renderStatus({mode:'preview'}),/no backend status request is made/);
});
test('status view uses returned component fields and does not invent a successful operation',()=>{
 const data={components:[{name:'FastAPI',status:'UNAVAILABLE'},{name:'Go gateway',status:'DEGRADED'}]};
 const html=renderStatus({data});
 assert.match(html,/UNAVAILABLE/);assert.match(html,/DEGRADED/);assert.match(html,/Not available/);
 assert.doesNotMatch(html,/Responding|COMMITTED/);
 assert.match(renderStatus({data:{...data,last_ledger_operation:'backend-reference'}}),/backend-reference/);
});
test('old successful observations are hidden while refreshing or after an error',()=>{
 const data={components:[{name:'FastAPI',status:'CONNECTED'}],last_ledger_operation:'old-reference'};
 for(const overrides of [{loading:true},{error:new RequestError(503,'HTTP_ERROR','Unavailable')}]){
  const html=renderStatus({data,...overrides});
  assert.doesNotMatch(html,/old-reference|>CONNECTED</);assert.match(html,/UNKNOWN/);
 }
});
test('preview component states never claim a report from a live API',()=>{
 const html=renderStatus({mode:'preview'});
 assert.doesNotMatch(html,/Reported by Python system API/);
 assert.match(html,/No verified integration status returned/);
});

const {QueryClient,QueryClientProvider}=await import('@tanstack/react-query');
const {AppProvider}=await import('../src/app/context.tsx');
const {InvestorProvider}=await import('../src/app/investor.tsx');
const {ConnectedMarketplace}=await import('../src/pages/Investor.tsx');
test('connected marketplace renders missing balances without scenario holdings or invented evidence',()=>{
 const cache=new QueryClient({defaultOptions:{queries:{retry:false}}});
 const html=renderToStaticMarkup(h(QueryClientProvider,{client:cache},h(MemoryRouter,null,h(AppProvider,null,h(InvestorProvider,null,h(ConnectedMarketplace))))));
 assert.match(html,/ANSH Marketplace/);assert.match(html,/Authoritative balance unavailable/);
 assert.match(html,/Simulated payment outcome/);assert.match(html,/Review acquisition/);
 assert.doesNotMatch(html,/500 ANSH|100,000 ANSH|COMMITTED_VALID|Bearer|TOKANSH_TRANSFER_SECRET/);
 cache.clear();
});

const {ReservationNotice,LoanDetails}=await import('../src/pages/Financing.tsx');
test('financing notice explicitly separates reservation and transferable ownership',()=>{
 const html=renderToStaticMarkup(h(ReservationNotice));
 assert.match(html,/no blockchain lock or legal pledge/);assert.match(html,/remain transferable on DRUNIX/);
 assert.match(html,/never your displayed transferable balance/);
});
test('financing detail shows simulated loan amounts, dated lifecycle and the correct repayment/release action',()=>{
 const base={id:'70000000-0000-4000-8000-000000000001',quantity:1,state:'DISBURSED',ltv_percent:60,
  reservation_active:true,collateral_value_minor:'1000000',principal_minor:'600000',interest_minor:'60000',
  repayment_minor:'660000',outstanding_principal_minor:'600000',amount_due_minor:'660000',assessment:null,
  timeline:[{state:'DISBURSED',timestamp:'2026-11-20T10:00:00Z',actor_role:'INVESTOR',simulated:true}]};
 const html=renderToStaticMarkup(h(LoanDetails,{loan:base,onAction:()=>{}}));
 assert.match(html,/SIMULATED/);assert.match(html,/₹6,600.00/);assert.match(html,/Simulate full repayment/);assert.match(html,/dateTime="2026-11-20T10:00:00Z"/i);
 assert.doesNotMatch(html,/Release simulation reservation/);
 const repaid=renderToStaticMarkup(h(LoanDetails,{loan:{...base,state:'REPAID',outstanding_principal_minor:'0',amount_due_minor:'0'},onAction:()=>{}}));
 assert.match(repaid,/Release simulation reservation/);assert.doesNotMatch(repaid,/Simulate full repayment/);
});
