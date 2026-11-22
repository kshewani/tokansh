import {createContext,useContext,useMemo,useRef,useState} from 'react';
import type {ReactNode} from 'react';
import {useMutation,useQuery,useQueryClient} from '@tanstack/react-query';
import {request,realBackendConfigured,idempotency,API_MODE} from '../api/transport';
import {errorFeedback} from '../api/client';
import type {ApiMode} from '../api/client';
import {parseSystemStatus,componentStatus} from '../api/systemStatus';
import {previewData,submitAction,createSubmissionGuard,checkSubmissionResult} from './integration';
import {route} from '../api/contracts';
import type {SystemStatus} from '../api/contracts';
import type {Role,Phase} from '../demo/scenario';
import {readDemoSession,writeDemoSession,clearDemoSession} from '../demo/session';
type Message={kind:'error'|'info'|'submitted';text:string}|null;
type Context={
 role:Role;demoSession:Role|null;login:(v:Role)=>void;logout:()=>void;phase:Phase;setPhase:(v:Phase)=>void;message:Message;notify:(v:Message)=>void;
 mode:ApiMode;backendReady:boolean;systemStatus:SystemStatus|null;loadingStatus:boolean;
 statusError:unknown;retryStatus:()=>void;backendConfigured:boolean;
 preview:ReturnType<typeof previewData>;
 submit:(path:string,body:unknown)=>Promise<void>;submitting:boolean;
};
const ctx=createContext<Context|null>(null);
export function AppProvider({children}:{children:ReactNode}){
 const [demoSession,setDemoSession]=useState<Role|null>(()=>readDemoSession());
 const [role,setRoleState]=useState<Role>(()=>readDemoSession()||'INVESTOR');
 const [phase,setPhase]=useState<Phase>('ONBOARDING');
 const [message,notify]=useState<Message>(null);
 const queryClient=useQueryClient();
 const submissionGuard=useRef(createSubmissionGuard());
 const health=useQuery({queryKey:['system-status'],queryFn:async({signal})=>parseSystemStatus(await request<unknown>(route.status,{signal})),enabled:realBackendConfigured,refetchInterval:realBackendConfigured?30000:false,retry:1});
 const mutation=useMutation({
  retry:false,
  mutationFn:async({path,body}:{path:string;body:unknown})=>{
   const key=idempotency();
   const data=await request<unknown>(path,{method:'POST',body,idempotencyKey:key,correlationId:key});
   checkSubmissionResult(data,key);
   return data;
  },
  onSuccess:()=>{
   notify({kind:'info',text:'Backend response received. No ownership or ledger commitment is established by this frontend; authoritative business integration is still required.'});
   void queryClient.invalidateQueries();
  },
  onError:(error)=>notify({kind:'error',text:errorFeedback(error)})
 });
 const login=(value:Role)=>{writeDemoSession(value);setRoleState(value);setDemoSession(value);setPhase('ONBOARDING');notify(null);};
 const logout=()=>{clearDemoSession();setDemoSession(null);setRoleState('INVESTOR');setPhase('ONBOARDING');notify(null);queryClient.clear();};
 const preview=useMemo(()=>previewData(API_MODE,phase),[phase]);
 // A failed/refetching observation must not leave an old CONNECTED badge visible.
 const systemStatus=health.isSuccess&&!health.isFetching?health.data:null;
 async function submit(path:string,body:unknown){
  await submitAction(API_MODE,()=>submissionGuard.current.run(()=>mutation.mutateAsync({path,body})),()=>
   notify({kind:'info',text:'UI preview only. This operation requires the Python API and verified DRUNIX connectivity; no ledger state was changed.'}));
 }
 return <ctx.Provider value={{role,demoSession,login,logout,phase,setPhase,message,notify,mode:API_MODE,
  backendReady:componentStatus(systemStatus,'FastAPI')==='CONNECTED',systemStatus,loadingStatus:health.isFetching,
  statusError:health.error,retryStatus:()=>{void health.refetch();},backendConfigured:realBackendConfigured,
  preview,submit,submitting:mutation.isPending}}>{children}</ctx.Provider>;
}
export function useApp(){const value=useContext(ctx);if(!value)throw new Error('AppProvider missing');return value;}
export function usePreview(){
 const value=useApp();
 if(!value.preview)throw new Error('Preview business screens are unavailable in Connected Mode.');
 return {...value,...value.preview};
}
