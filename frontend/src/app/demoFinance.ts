import {useState} from 'react';
import {useQuery,useMutation,useQueryClient} from '@tanstack/react-query';
import {useApp} from './context';
import {readInstitution} from './workspace';
import {request,idempotency} from '../api/transport';
import {parseLenders,parseCash,parseEntry,createCashFlow} from '../api/demoFinance';
import {investorDemo} from '../api/transfers';
export function useLenders(){const {role,mode,backendConfigured}=useApp();return useQuery({queryKey:['lenders',role],enabled:mode==='real'&&backendConfigured,retry:false,queryFn:async({signal})=>parseLenders(await request('/api/v1/financing/lenders',{demoRole:role,signal}))});}
export function useInstitution(){
 const [id,setId]=useState(()=>{try{return readInstitution(window.sessionStorage);}catch{return 'axim-bank';}});
 return [id,(v:string)=>{setId(v);try{window.sessionStorage.setItem('tokansh-lender',v);}catch{/* memory selection remains */}}] as const;
}
const cashFlow=createCashFlow(()=>window.sessionStorage,idempotency);
export function useWallet(){
 const {role,mode,backendConfigured}=useApp(),cache=useQueryClient();const enabled=mode==='real'&&backendConfigured&&role==='INVESTOR';
 const balance=useQuery({queryKey:['wallet','balance',role],enabled,retry:false,queryFn:async({signal})=>parseCash(await request('/api/v1/demo-wallet',{signal,demoRole:role}),investorDemo.investor)});
 const activity=useQuery({queryKey:['wallet','activity',role],enabled,retry:false,queryFn:async({signal})=>{const value=await request<unknown>('/api/v1/demo-wallet/activity',{signal,demoRole:role});if(!Array.isArray(value))throw new Error('Invalid cash history');return value.map(parseEntry);}});
 const mutation=useMutation({retry:false,mutationFn:async({action,amount}:{action:'fund'|'withdraw';amount:string})=>
 cashFlow.run(action,amount,key=>request('/api/v1/demo-wallet/'+action,{demoRole:role,method:'POST',body:{amount_minor:amount},idempotencyKey:key}))
 ,onSuccess:()=>{void cache.invalidateQueries({queryKey:['wallet']});void cache.invalidateQueries({queryKey:['financing']});}});
 let recovery:ReturnType<typeof cashFlow.snapshot>=null;try{if(enabled)recovery=cashFlow.snapshot();}catch{/* Mutation fails closed if storage is unavailable or corrupted. */}
 return {balance,activity,mutation,recovery};
}
