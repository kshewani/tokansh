import {useState} from 'react';
import {Navigate,Outlet,Route,Routes,useNavigate} from 'react-router-dom';
import type {ReactNode} from 'react';
import {ArrowRight,Building2,LockKeyhole,ShieldCheck} from 'lucide-react';
import {useApp} from './app/context';
import type {Role} from './lib/session';
import {roleOptions} from './lib/session';
import {Shell} from './components/Shell';
import {Button} from './components/ui/button';
import {Card} from './components/ui/card';
import {InlineError,TrustNotice} from './components/ui/status';
import {Overview,Portfolio} from './pages/Overview';
import {Registry,Issuance,Marketplace} from './pages/RealEstate';
import {Collateral,Lending} from './pages/Finance';
import {Distributions,Audit,Intelligence,System} from './pages/Supporting';

/** UI navigation only. Production identity and authorization belong to Python APIs. */
function RequireDemoSession(){
 const {session}=useApp();
 return session?<Outlet/>:<Navigate to="/login" replace/>;
}
function Guard({roles,children}:{roles:Role[];children:ReactNode}){
 const {role}=useApp();
 return roles.includes(role)?<>{children}</>:<Navigate to="/overview" replace/>;
}
function Login(){
 const {session,role,login,backendReady}=useApp();
 const [selectedRole,setSelectedRole]=useState<Role>(role);
 const [username,setUsername]=useState(roleOptions.find(o=>o.role===role)?.usernames[0].value??'meera');
 const [password,setPassword]=useState('');
 const [error,setError]=useState<string|null>(null);
 const [busy,setBusy]=useState(false);
 const navigate=useNavigate();
 if(session)return <Navigate to="/overview" replace/>;
 const selected=roleOptions.find(item=>item.role===selectedRole);
 async function enter(event:React.FormEvent<HTMLFormElement>){
  event.preventDefault();
  setBusy(true);setError(null);
  try{await login(username,password);navigate('/overview',{replace:true});}
  catch(e){setError(e instanceof Error?e.message:'Sign-in failed.');}
  finally{setBusy(false);}
 }
 return <main className="grid min-h-screen grid-cols-1 bg-[#F4F6F9] lg:grid-cols-[.9fr_1.1fr]">
  <section className="flex min-h-[290px] flex-col justify-between bg-[#102B4E] px-7 py-8 text-white sm:px-10 lg:min-h-screen lg:px-14 lg:py-12">
   <div className="flex items-center gap-3 text-xl font-extrabold tracking-tight"><span className="flex h-10 w-10 items-center justify-center rounded-xl border border-blue-300/40 bg-blue-400/10 text-3xl text-blue-200">◈</span><span>Tok<span className="text-blue-200">ANSH</span></span></div>
   <div className="max-w-lg py-8 lg:py-20"><p className="text-xs font-bold uppercase tracking-[.18em] text-blue-200">DRUNIX Hackathon 2026</p>
    <h1 className="mt-5 text-3xl font-extrabold leading-tight text-white sm:text-4xl lg:text-5xl">Unlocking Real Estate,<br/><span className="text-blue-200">One Ansh at a Time.</span></h1>
    <p className="mt-5 max-w-md text-sm leading-7 text-blue-100/80">A professional workspace for fractional real estate interests, portfolio visibility, issuance, collateral and lifecycle tracking.</p>
    <div className="mt-9 grid gap-4 text-sm text-blue-100/90"><div className="flex items-center gap-3"><Building2 size={18} className="text-blue-200"/> Property and ANSH lifecycle</div><div className="flex items-center gap-3"><ShieldCheck size={18} className="text-blue-200"/> Distinct transaction and ledger states</div><div className="flex items-center gap-3"><LockKeyhole size={18} className="text-blue-200"/> Institution-ready role experiences</div></div>
   </div>
   <p className="text-xs text-blue-100/60">Synthetic demonstration · Simulated payments and lending · ANSH ledger on DRUNIX</p>
  </section>
  <section className="flex items-center justify-center px-5 py-9 sm:px-8 lg:p-12">
   <div className="w-full max-w-[470px]">
    <p className="mb-2 text-xs font-bold uppercase tracking-[.14em] text-[#607D9B]">TokANSH / Demo Access</p>
    <h2 className="text-2xl font-extrabold text-[#102B4E]">Sign in to your workspace</h2>
    <p className="mb-7 mt-2 text-sm leading-6 text-slate-500">Select a demonstration account to explore the approved MVP workflows.</p>
    <Card>
     <form onSubmit={enter}>
      <fieldset className="space-y-3"><legend className="mb-3 text-sm font-bold text-[#102B4E]">Choose an account</legend>
       {roleOptions.map(item=><label key={item.role} className={'flex cursor-pointer items-start gap-3 rounded-lg border p-4 transition-colors '+(selectedRole===item.role?'border-[#1769AA] bg-blue-50':'border-slate-200 bg-white hover:border-blue-300')}>
        <input className="mt-1 accent-[#1769AA]" type="radio" name="demo-role" value={item.role} checked={selectedRole===item.role} onChange={()=>{setSelectedRole(item.role);setUsername(item.usernames[0].value);}}/>
        <span><strong className="text-sm text-[#102B4E]">{item.label}</strong><span className="mt-1 block text-xs leading-5 text-slate-500">{item.description}</span></span>
       </label>)}
      </fieldset>
      <div className="mt-5 grid gap-3">
       {selected&&selected.usernames.length>1&&<label className="grid gap-1.5 text-xs font-semibold text-[#102B4E]" htmlFor="login-institution">Institution
        <select id="login-institution" className="rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-sm font-normal text-slate-700" value={username} onChange={e=>setUsername(e.target.value)}>
         {selected.usernames.map(u=><option key={u.value} value={u.value}>{u.label}</option>)}</select></label>}
       <label className="grid gap-1.5 text-xs font-semibold text-[#102B4E]" htmlFor="login-password">Password
        <input id="login-password" type="password" autoComplete="current-password" required className="rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-sm font-normal text-slate-700" value={password} onChange={e=>setPassword(e.target.value)} placeholder="Any password for this demo"/></label>
       <p className="text-xs text-slate-500">Signing in as <strong className="text-[#102B4E]">{selected?.usernames.find(u=>u.value===username)?.label??username}</strong>. Demo sign-in: any non-empty password is accepted.</p>
      </div>
      <Button type="submit" className="mt-5 w-full" disabled={busy||!password}>{busy?'Signing in…':'Enter demo workspace'} <ArrowRight size={17}/></Button>
      {error&&<InlineError message={error}/>}
      {!backendReady&&!error&&<p className="mt-3 text-xs text-amber-800">Connecting to the TokANSH API… a sleeping free server can take up to a minute to wake up.</p>}
     </form>
    </Card>
    <div className="mt-5"><TrustNotice compact/></div>
    <p className="mt-4 text-center text-xs leading-5 text-slate-500">Demonstration sign-in, not real authentication: the API issues a session token and enforces each role's permissions. Sessions end when the API restarts.</p>
   </div>
  </section>
 </main>;
}
export default function App(){
 return <Routes>
  <Route path="/login" element={<Login/>}/>
  <Route element={<RequireDemoSession/>}>
   <Route element={<Shell/>}>
    <Route path="/overview" element={<Overview/>}/>
    <Route path="/registry" element={<Guard roles={['ISSUER']}><Registry/></Guard>}/>
    <Route path="/issuance" element={<Guard roles={['ISSUER']}><Issuance/></Guard>}/>
    <Route path="/marketplace" element={<Guard roles={['ISSUER','INVESTOR']}><Marketplace/></Guard>}/>
    <Route path="/portfolio" element={<Guard roles={['INVESTOR']}><Portfolio/></Guard>}/>
    <Route path="/transactions" element={<Audit mode="transactions"/>}/>
    <Route path="/intelligence" element={<Guard roles={['ISSUER','INVESTOR']}><Intelligence/></Guard>}/>
    <Route path="/collateral" element={<Guard roles={['INVESTOR','LENDER']}><Collateral/></Guard>}/>
    <Route path="/lending" element={<Guard roles={['INVESTOR','LENDER']}><Lending/></Guard>}/>
    <Route path="/distributions" element={<Guard roles={['ISSUER','INVESTOR']}><Distributions/></Guard>}/>
    <Route path="/audit" element={<Guard roles={['ISSUER','LENDER']}><Audit/></Guard>}/>
    <Route path="/system" element={<System/>}/>
   </Route>
  </Route>
  <Route path="*" element={<Navigate to="/login" replace/>}/>
 </Routes>;
}
