import {useRef} from 'react';
import {useMutation,useQuery,useQueryClient} from '@tanstack/react-query';
import {useApp} from './context';
import {request,idempotency} from '../api/transport';
import {investorDemo} from '../api/transfers';
import {parseEligibility,parseLoan} from '../api/financing';
import type {FinanceCommand} from '../api/financing';
import {RequestError} from '../api/client';

export function useFinancing(lenderId='axim-bank'){
 const {role,mode,backendConfigured,demoSession}=useApp(),cache=useQueryClient();
 const enabled=mode==='real'&&backendConfigured&&!!demoSession&&(role==='INVESTOR'||role==='LENDER');
 const loans=useQuery({queryKey:['financing','loans',role,lenderId],enabled,retry:false,staleTime:0,
  queryFn:async({signal})=>{const value=await request<unknown>('/api/v1/financing/applications'+(role==='LENDER'?'?lender_id='+encodeURIComponent(lenderId):''),{signal,demoRole:role});if(!Array.isArray(value))throw new Error('Invalid financing list');return value.map(parseLoan);}});
 const eligibility=useQuery({queryKey:['financing','eligibility',role],enabled:enabled&&role==='INVESTOR',retry:false,staleTime:0,
  queryFn:async({signal})=>parseEligibility(await request<unknown>('/api/v1/financing/eligibility/'+investorDemo.property,{signal,demoRole:role}),investorDemo.property,investorDemo.investor)});
 const key=useRef<{body:string;key:string}|null>(null),pending=useRef(false);
 const mutation=useMutation({retry:false,mutationFn:async(args:{command:FinanceCommand}|{id:string;action:string})=>{
  if(pending.current)throw new RequestError(409,'OPERATION_PENDING','A financing operation is in progress.');
  pending.current=true;
  try{
   if('command' in args){
    const body=JSON.stringify(args.command);
    if(!key.current||key.current.body!==body)key.current={body,key:idempotency()};
    return parseLoan(await request<unknown>('/api/v1/financing/applications',{method:'POST',body:args.command,demoRole:role,idempotencyKey:key.current.key,correlationId:key.current.key}));
   }
   return parseLoan(await request<unknown>(`/api/v1/financing/applications/${args.id}/${args.action}?lender_id=${encodeURIComponent(lenderId)}`,{method:'POST',demoRole:role,body:{}}));
  }finally{pending.current=false;}
 },onSuccess:(loan)=>{
  cache.setQueryData(['financing','loans',role,lenderId],(old:ReturnType<typeof parseLoan>[]|undefined)=>[loan,...(old||[]).filter(v=>v.id!==loan.id)]);
  void cache.invalidateQueries({queryKey:['financing']});void cache.invalidateQueries({queryKey:['wallet']});
 }});
 return {role,loans,eligibility,mutation,apply:(command:FinanceCommand)=>mutation.mutateAsync({command}),action:(id:string,action:string)=>mutation.mutateAsync({id,action}),
  refresh:()=>{void cache.invalidateQueries({queryKey:['financing']});void cache.invalidateQueries({queryKey:['wallet']});},newApplication:()=>{key.current=null;mutation.reset();}};
}
