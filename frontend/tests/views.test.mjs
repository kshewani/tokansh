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

test('connected property registry renders its authenticated workflow; preview renders fixtures unchanged',()=>{
 function Fixture(){return h('div',null,'500 ANSH PREVIEW-001');}
 for(const mode of ['real','preview']){
  const html=renderToStaticMarkup(h(MemoryRouter,null,h(ConnectedBoundary,{mode,path:'/registry',title:'Registry'},h(Fixture))));
  if(mode==='real'){
   assert.match(html,/500 ANSH PREVIEW-001/);
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
 assert.match(renderStatus({mode:'preview'}),/Service status is not requested for this workspace/);
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
test('connected marketplace shows loading offerings without scenario holdings or invented evidence',()=>{
 const cache=new QueryClient({defaultOptions:{queries:{retry:false}}});
 const html=renderToStaticMarkup(h(QueryClientProvider,{client:cache},h(MemoryRouter,null,h(AppProvider,null,h(InvestorProvider,null,h(ConnectedMarketplace))))));
 assert.match(html,/ANSH Marketplace/);assert.match(html,/Loading active offerings…/);
 assert.doesNotMatch(html,/Authoritative balance unavailable|Simulated payment outcome|Review acquisition|Purchase existing ANSH/);
 assert.doesNotMatch(html,/500 ANSH|100,000 ANSH|COMMITTED_VALID|Bearer|TOKANSH_TRANSFER_SECRET/);
 cache.clear();
});

test('connected marketplace shows an empty offering state without invented inventory or purchase controls',()=>{
 const cache=new QueryClient({defaultOptions:{queries:{retry:false}}});
 cache.setQueryData(['marketplace-offerings'],[]);
 cache.setQueryData(['marketplace-properties'],[]);
 const html=renderToStaticMarkup(h(QueryClientProvider,{client:cache},h(MemoryRouter,null,h(AppProvider,null,h(InvestorProvider,null,h(ConnectedMarketplace))))));
 assert.match(html,/No active offerings are currently available/);
 assert.doesNotMatch(html,/Purchase existing ANSH|500 ANSH|100,000 ANSH|COMMITTED_VALID/);
 cache.clear();
});

test('connected marketplace keeps offering errors separate from empty and purchase states',()=>{
 const cache=new QueryClient({defaultOptions:{queries:{retry:false,retryOnMount:false,staleTime:Infinity}}});
 const query=cache.getQueryCache().build(cache,{queryKey:['marketplace-offerings'],queryFn:async()=>[],staleTime:Infinity,retryOnMount:false});
 query.setState({...query.state,error:new RequestError(503,'HTTP_ERROR','Offering service unavailable'),
  errorUpdateCount:1,errorUpdatedAt:Date.now(),status:'error',fetchStatus:'idle'});
 cache.setQueryData(['marketplace-properties'],[]);
 const html=renderToStaticMarkup(h(QueryClientProvider,{client:cache},h(MemoryRouter,null,h(AppProvider,null,h(InvestorProvider,null,h(ConnectedMarketplace))))));
 assert.match(html,/role="alert"/);assert.match(html,/Offering service unavailable/);
 assert.doesNotMatch(html,/No active offerings are currently available|Purchase existing ANSH/);
 cache.clear();
});

test('connected marketplace disables purchase when authoritative wallet data is unavailable',()=>{
 const cache=new QueryClient({defaultOptions:{queries:{retry:false,staleTime:Infinity}}});
 cache.setQueryData(['marketplace-offerings'],[{
  id:'70000000-0000-4000-8000-000000000001',property_id:'f6169750-4676-4e99-887f-2bc5471bd518',
  issuer_id:'00000000-0000-4000-8000-000000000003',offered_quantity:5,sold_quantity:0,reserved_quantity:0,
  available_quantity:5,price_minor:'100000',currency:'INR',status:'ACTIVE',created_at:'2026-11-20T00:00:00Z',updated_at:'2026-11-20T00:00:00Z'
 }]);
 cache.setQueryData(['marketplace-properties'],[]);
 const html=renderToStaticMarkup(h(QueryClientProvider,{client:cache},h(MemoryRouter,null,h(AppProvider,null,h(InvestorProvider,null,h(ConnectedMarketplace))))));
 assert.match(html,/Available simulated cash/);assert.match(html,/Unavailable/);
 assert.match(html,/disabled=""[^>]*>Purchase existing ANSH/s);
 assert.doesNotMatch(html,/500 ANSH|100,000 ANSH|COMMITTED_VALID|Simulated payment outcome/);
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

const {ReitHoldingsCard}=await import('../src/components/ReitHoldings.tsx');
const {CurrentDistributions}=await import('../src/components/IncomeDistributions.tsx');
const {AssetResearch}=await import('../src/components/AssetResearch.tsx');
function renderInvestment(Component){const cache=new QueryClient({defaultOptions:{queries:{retry:false}}});try{return renderToStaticMarkup(h(QueryClientProvider,{client:cache},h(MemoryRouter,null,h(AppProvider,null,h(InvestorProvider,null,h(Component))))));}finally{cache.clear();}}
test('REIT representation displays separate subtotal, exact yield, trading boundary and collateral exclusion',()=>{
 const html=renderToStaticMarkup(h(MemoryRouter,null,h(ReitHoldingsCard)));
 assert.match(html,/ILLUSTRATIVE/);assert.match(html,/₹60,000.00/);assert.match(html,/7.20%/);assert.match(html,/6.40%/);
 assert.match(html,/applicable exchange hours/);assert.match(html,/does not enable unrestricted 24\/7 trading/);
 assert.match(html,/Not eligible/);assert.match(html,/Consolidated live portfolio value: unavailable/);
});
test('income view separates projections and empty local payout history without invented settlement evidence',()=>{
 const html=renderInvestment(CurrentDistributions);
 assert.match(html,/Projected ANSH income/);assert.match(html,/Projected REIT income/);
 assert.match(html,/No illustrative distributions yet/);assert.match(html,/not audited historical or record-date ownership/);
 assert.doesNotMatch(html,/· SIMULATED COMPLETED|COMMITTED_VALID|ledger transaction ID/);
});
test('research distinguishes illustrative assumptions from sourced ledger observations',()=>{
 const html=renderInvestment(AssetResearch);
 assert.match(html,/curated scenario/);assert.match(html,/No guaranteed buyer|no guaranteed buyer/);
 assert.match(html,/Configured property reference/);assert.match(html,/Curated demonstration labels/);
 assert.match(html,/no independent appraisal|independent appraisal/);assert.match(html,/Explainable investment insights/);
});

test('investor loan details never render lender decisions; lender receives state-appropriate controls',()=>{
 const base={id:'loan',quantity:1,state:'ASSESSED',ltv_percent:60,reservation_active:false,collateral_value_minor:'1000000',principal_minor:'600000',interest_minor:'60000',repayment_minor:'660000',outstanding_principal_minor:'0',amount_due_minor:'0',assessment:null,timeline:[]};
 const investor=renderToStaticMarkup(h(LoanDetails,{loan:base,onAction:()=>{},role:'INVESTOR'}));
 assert.doesNotMatch(investor,/Simulate approval|Reject application|Simulate disbursement/);
 const lender=renderToStaticMarkup(h(LoanDetails,{loan:base,onAction:()=>{},role:'LENDER',canRepay:false}));
 assert.match(lender,/Simulate approval/);assert.match(lender,/Reject application/);assert.doesNotMatch(lender,/Simulate full repayment/);
});

const {default:App}=await import('../src/App.tsx');
test('login renders exactly Investor and Lender role cards without a separate issuer account',()=>{
 const cache=new QueryClient({defaultOptions:{queries:{retry:false}}});
 const html=renderToStaticMarkup(h(QueryClientProvider,{client:cache},h(MemoryRouter,{initialEntries:['/login']},h(AppProvider,null,h(App)))));
 assert.equal((html.match(/name="demo-role"/g)||[]).length,2);
 assert.match(html,/value="INVESTOR"/);assert.match(html,/value="LENDER"/);assert.doesNotMatch(html,/value="ISSUER"/);cache.clear();
});
