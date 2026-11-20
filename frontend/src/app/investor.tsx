import {createContext,useContext,useEffect,useMemo,useRef,useSyncExternalStore} from 'react';
import type {ReactNode} from 'react';
import {useQuery,useQueryClient} from '@tanstack/react-query';
import {useApp} from './context';
import {request} from '../api/transport';
import {createTransferFlow,investorDemo,parseBalance} from '../api/transfers';
import type {Role} from '../demo/scenario';

function recoveryStorage():Pick<Storage,'getItem'|'setItem'|'removeItem'>{
 if(typeof window==='undefined')return {getItem:()=>null,setItem:()=>{},removeItem:()=>{}};
 try{return window.sessionStorage;}catch{return {getItem:()=>{throw new Error();},setItem:()=>{throw new Error();},removeItem:()=>{throw new Error();}};}
}
function useInvestorSession(role:Role,enabled:boolean){
 const flow=useMemo(()=>createTransferFlow(request,recoveryStorage(),role),[role]);
 const snapshot=useSyncExternalStore(flow.subscribe,flow.getSnapshot,flow.getSnapshot);
 const cache=useQueryClient(),refreshed=useRef('');
 const balances=useQuery({queryKey:['ansh-balances',role],enabled,retry:false,staleTime:0,
  queryFn:async({signal})=>{
   const holders=[investorDemo.issuer,investorDemo.investor,investorDemo.recipient];
   return Promise.all(holders.map(async holder=>parseBalance(await request<unknown>(`/api/v1/ansh/balances/${investorDemo.property}/${holder}`,{demoRole:role,signal}),holder)));
  }});
 useEffect(()=>{
  const result=snapshot.attempt?.result;
  if(enabled&&result?.state==='COMMITTED_VALID'&&refreshed.current!==result.operation_id){
   refreshed.current=result.operation_id;void cache.invalidateQueries({queryKey:['ansh-balances']});
  }
 },[enabled,snapshot.attempt?.result,cache]);
 return {flow,snapshot,balances,live:balances.isSuccess&&!balances.isFetching?balances.data:null};
}
const context=createContext<ReturnType<typeof useInvestorSession>|null>(null);
export function InvestorProvider({children}:{children:ReactNode}){
 const {role,mode,backendConfigured,demoSession}=useApp();
 const value=useInvestorSession(role,mode==='real'&&backendConfigured&&!!demoSession);
 return <context.Provider value={value}>{children}</context.Provider>;
}
export function useInvestor(){const value=useContext(context);if(!value)throw new Error('InvestorProvider missing');return value;}
