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
  const html=renderToStaticMarkup(h(MemoryRouter,null,h(ConnectedBoundary,{mode,path:'/portfolio',title:'Portfolio'},h(Fixture))));
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
