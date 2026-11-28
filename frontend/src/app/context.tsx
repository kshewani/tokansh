import {createContext,useContext,useEffect,useMemo,useRef,useState} from 'react';
import type {ReactNode} from 'react';
import {useMutation,useQuery,useQueryClient} from '@tanstack/react-query';
import {request,realBackendConfigured,idempotency,API_MODE} from '../api/transport';
import {clearAuthSession,readAuthSession,writeAuthSession} from '../api/client';
import type {ApiMode,AuthRole,AuthSession} from '../api/client';
import {currentSession,login as loginRequest,logout as logoutRequest} from '../api/auth';
import {errorFeedback,RequestError} from '../api/client';
import {parseSystemStatus,componentStatus} from '../api/systemStatus';
import {previewData,submitAction,createSubmissionGuard,checkSubmissionResult} from './integration';
import {route} from '../api/contracts';
import type {SystemStatus} from '../api/contracts';
import type {Role,Phase} from '../demo/scenario';
type Message={kind:'error'|'info'|'submitted';text:string}|null;
type Context={
 role:Role;demoSession:AuthSession|null;session:AuthSession|null;authStatus:'loading'|'authenticated'|'unauthenticated';authError:unknown;
 login:(username:string,password:string,expectedRole:AuthRole)=>Promise<void>;logout:()=>Promise<void>;phase:Phase;setPhase:(v:Phase)=>void;message:Message;notify:(v:Message)=>void;
 mode:ApiMode;backendReady:boolean;systemStatus:SystemStatus|null;loadingStatus:boolean;
 statusError:unknown;retryStatus:()=>void;backendConfigured:boolean;
 preview:ReturnType<typeof previewData>;
 submit:(path:string,body:unknown)=>Promise<void>;submitting:boolean;
};
const ctx=createContext<Context|null>(null);
function previewSession(username:string,role:AuthRole):AuthSession {
 const lender=role==='LENDER';
 const normalized=username.trim().toLowerCase();
 const lenders:{id:string;name:string}[]=[{id:'axim-bank',name:'Axim Bank'},{id:'real-finance',name:'Real Finance'},{id:'horizon-credit',name:'Horizon Credit'}];
 const organization=lenders.find(value=>value.id===normalized);
 if(!normalized||(!lender&&!['meera','aarav'].includes(normalized))||(lender&&!organization))throw new RequestError(401,'INVALID_CREDENTIALS','The selected identity or password is invalid.');
 return {access_token:'preview-session',token_type:'bearer',username:lender?normalized:normalized[0].toUpperCase()+normalized.slice(1),display_name:lender?(organization?.name||normalized):normalized[0].toUpperCase()+normalized.slice(1),role,user_id:lender?'preview-lender':`preview-${normalized}`,organization_id:lender?normalized:null};
}
export function AppProvider({children}:{children:ReactNode}){
 const [session,setSession]=useState<AuthSession|null>(()=>readAuthSession());
 const [authStatus,setAuthStatus]=useState<'loading'|'authenticated'|'unauthenticated'>(()=>readAuthSession()?'loading':'unauthenticated');
 const [authError,setAuthError]=useState<unknown>(null);
 const [phase,setPhase]=useState<Phase>('ONBOARDING');
 const [message,notify]=useState<Message>(null);
 const queryClient=useQueryClient();
 const submissionGuard=useRef(createSubmissionGuard());
 const role=(session?.role||'INVESTOR') as Role;
 useEffect(()=>{
 const fail=()=>{clearAuthSession();setSession(null);setAuthStatus('unauthenticated');setAuthError(new RequestError(401,'AUTHENTICATION_REQUIRED','Your session is no longer valid.'));queryClient.clear();};
  window.addEventListener('tokansh-auth-failure',fail);
  if(API_MODE!=='real'){clearAuthSession();setSession(null);setAuthStatus('unauthenticated');return()=>window.removeEventListener('tokansh-auth-failure',fail);}
  const stored=readAuthSession();
  if(!stored){setAuthStatus('unauthenticated');return()=>window.removeEventListener('tokansh-auth-failure',fail);}
  let active=true;
  void currentSession(request,stored.access_token).then(value=>{if(active){writeAuthSession(value);setSession(value);setAuthStatus('authenticated');setAuthError(null);}}).catch(error=>{if(active){clearAuthSession();setSession(null);setAuthStatus('unauthenticated');setAuthError(error);}});
  return()=>{active=false;window.removeEventListener('tokansh-auth-failure',fail);};
 },[queryClient]);
 const health=useQuery({queryKey:['system-status',session?.user_id,session?.organization_id],queryFn:async({signal})=>parseSystemStatus(await request<unknown>(route.status,{signal})),enabled:realBackendConfigured&&authStatus==='authenticated',refetchInterval:realBackendConfigured?30000:false,retry:1});
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
 const login=async(username:string,password:string,expectedRole:AuthRole)=>{if(!password)throw new RequestError(422,'INVALID_CREDENTIALS','A nonempty password is required.');const value=API_MODE==='real'?await loginRequest(request,username,password,expectedRole):previewSession(username,expectedRole);if(API_MODE==='real')writeAuthSession(value);setSession(value);setAuthStatus('authenticated');setAuthError(null);setPhase('ONBOARDING');notify(null);queryClient.clear();};
 const logout=async()=>{try{if(API_MODE==='real'&&session)await logoutRequest(request);}catch{/* Local state must be cleared even when the backend is unavailable. */}finally{clearAuthSession();setSession(null);setAuthStatus('unauthenticated');setAuthError(null);setPhase('ONBOARDING');notify(null);queryClient.clear();}};
 const preview=useMemo(()=>previewData(API_MODE,phase),[phase]);
 // A failed/refetching observation must not leave an old CONNECTED badge visible.
 const systemStatus=health.isSuccess&&!health.isFetching?health.data:null;
 async function submit(path:string,body:unknown){
  await submitAction(API_MODE,()=>submissionGuard.current.run(()=>mutation.mutateAsync({path,body})),()=>
   notify({kind:'info',text:'UI preview only. This operation requires the Python API and verified DRUNIX connectivity; no ledger state was changed.'}));
 }
 return <ctx.Provider value={{role,demoSession:session,session,authStatus,authError,login,logout,phase,setPhase,message,notify,mode:API_MODE,
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
