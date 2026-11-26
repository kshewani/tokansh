import {createContext,useContext,useEffect,useMemo,useRef,useSyncExternalStore} from 'react';
import type {ReactNode} from 'react';
import {useQuery,useQueryClient} from '@tanstack/react-query';
import {useApp} from './context';
import {request} from '../api/transport';
import {route} from '../api/contracts';
import {createTransferFlow,parseBalance} from '../api/transfers';
import {parsePortfolio} from '../api/properties';
function recoveryStorage():Pick<Storage,'getItem'|'setItem'|'removeItem'>{
 if(typeof window==='undefined')return {getItem:()=>null,setItem:()=>{},removeItem:()=>{}};
 try{return window.sessionStorage;}catch{return {getItem:()=>{throw new Error();},setItem:()=>{throw new Error();},removeItem:()=>{throw new Error();}};}
}
function useInvestorSession(userId:string|undefined,enabled:boolean){
 const flow=useMemo(()=>createTransferFlow(request,recoveryStorage(),userId||'anonymous'),[userId]);
 const snapshot=useSyncExternalStore(flow.subscribe,flow.getSnapshot,flow.getSnapshot);
 const cache=useQueryClient(),refreshed=useRef('');
 const portfolio=useQuery({queryKey:['portfolio',userId],enabled,retry:false,staleTime:0,
  queryFn:async({signal})=>{if(!userId)throw new Error('No authenticated investor identity.');return parsePortfolio(await request<unknown>(route.portfolio,{signal}),userId);}});
 const observedProperty=portfolio.data?.items.find(item=>item.observation_status==='AVAILABLE')?.property_id;
 const balances=useQuery({queryKey:['ansh-balances',userId,observedProperty],enabled:enabled&&!!observedProperty,retry:false,staleTime:0,
  queryFn:async({signal})=>{
   if(!userId)throw new Error('No authenticated investor identity.');
   if(!observedProperty)throw new Error('No authoritative property balance is available.');
   return parseBalance(await request<unknown>(`/api/v1/ansh/balances/${observedProperty}/${userId}`,{signal}),observedProperty,userId);
  }});
 useEffect(()=>{
  const result=snapshot.attempt?.result;
  if(enabled&&result?.state==='COMMITTED_VALID'&&refreshed.current!==result.operation_id){
   refreshed.current=result.operation_id;void cache.invalidateQueries({queryKey:['ansh-balances']});
   void cache.invalidateQueries({queryKey:['financing']});
  }
 },[enabled,snapshot.attempt?.result,cache]);
 return {flow,snapshot,balances,portfolio,live:balances.isSuccess&&!balances.isFetching?balances.data:null};
}
const context=createContext<ReturnType<typeof useInvestorSession>|null>(null);
export function InvestorProvider({children}:{children:ReactNode}){
 const {session,mode,backendConfigured,demoSession}=useApp();
 const value=useInvestorSession(session?.user_id,mode==='real'&&backendConfigured&&!!demoSession&&session?.role==='INVESTOR');
 return <context.Provider value={value}>{children}</context.Provider>;
}
export function useInvestor(){const value=useContext(context);if(!value)throw new Error('InvestorProvider missing');return value;}
