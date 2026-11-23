import {useQuery,useMutation,useQueryClient} from '@tanstack/react-query';
import {useApp} from './context';
import {request,idempotency} from '../api/transport';
import {parseLenders,parseCash,parseEntry,createCashFlow} from '../api/demoFinance';
export function useLenders(){const {session,mode,backendConfigured}=useApp();return useQuery({queryKey:['lenders'],enabled:mode==='real'&&backendConfigured&&!!session,retry:false,queryFn:async({signal})=>parseLenders(await request('/api/v1/financing/lenders',{signal}))});}
export function useWallet(){
 const {session,role,mode,backendConfigured}=useApp(),cache=useQueryClient();
 const userId=session?.user_id||'';
 const cashFlow=createCashFlow(()=>window.sessionStorage,idempotency,userId);
 const enabled=mode==='real'&&backendConfigured&&role==='INVESTOR'&&!!userId;
 const balance=useQuery({queryKey:['wallet','balance',userId],enabled,retry:false,queryFn:async({signal})=>parseCash(await request('/api/v1/demo-wallet',{signal}),userId)});
 const activity=useQuery({queryKey:['wallet','activity',userId],enabled,retry:false,queryFn:async({signal})=>{const value=await request<unknown>('/api/v1/demo-wallet/activity',{signal});if(!Array.isArray(value))throw new Error('Invalid cash history');return value.map(parseEntry);}});
 const mutation=useMutation({retry:false,mutationFn:async({action,amount}:{action:'fund'|'withdraw';amount:string})=>
  cashFlow.run(action,amount,key=>request('/api/v1/demo-wallet/'+action,{method:'POST',body:{amount_minor:amount},idempotencyKey:key}))
  ,onSuccess:()=>{void cache.invalidateQueries({queryKey:['wallet']});void cache.invalidateQueries({queryKey:['financing']});}});
 let recovery:ReturnType<typeof cashFlow.snapshot>=null;try{if(enabled)recovery=cashFlow.snapshot();}catch{/* Mutation fails closed if storage is unavailable or corrupted. */}
 return {balance,activity,mutation,recovery};
}
