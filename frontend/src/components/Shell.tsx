import {useEffect,useRef,useState} from 'react';
import {NavLink,Outlet,useLocation,useNavigate} from 'react-router-dom';
import {Activity,BarChart3,BookOpen,Building2,ChevronDown,Compass,FileCheck2,FileClock,HandCoins,Landmark,LayoutDashboard,LogOut,Menu,Shield,ShoppingCart,Wallet,X} from 'lucide-react';
import type {LucideIcon} from 'lucide-react';
import type {Role} from '../demo/scenario';
import {phases} from '../demo/scenario';
import {useApp} from '../app/context';
import {Status,PreviewWarning} from './ui/status';
import {ConnectedBoundary} from './ConnectedBoundary';
type MenuItem={to:string;label:string;icon:LucideIcon;roles:Role[];section:string};
const nav:MenuItem[]=[
 {to:'/overview',label:'Portfolio Overview',icon:LayoutDashboard,roles:['INVESTOR'],section:'Invest'},
 {to:'/marketplace',label:'Explore Assets',icon:Compass,roles:['INVESTOR'],section:'Invest'},
 {to:'/registry',label:'Create Property',icon:Building2,roles:['INVESTOR'],section:'Invest'},
 {to:'/portfolio',label:'My Portfolio',icon:Wallet,roles:['INVESTOR'],section:'Invest'},
 {to:'/collateral',label:'Borrow Against ANSH',icon:Landmark,roles:['INVESTOR'],section:'Liquidity'},
 {to:'/wallet',label:'Cash Wallet',icon:HandCoins,roles:['INVESTOR'],section:'Liquidity'},
 {to:'/lending',label:'Application Review',icon:Landmark,roles:['LENDER'],section:'Institution'},
 {to:'/transactions',label:'Activity',icon:FileClock,roles:['INVESTOR','LENDER'],section:'Insights'},
 {to:'/intelligence',label:'Asset Research',icon:BarChart3,roles:['INVESTOR'],section:'Insights'},
 {to:'/distributions',label:'Income',icon:HandCoins,roles:['INVESTOR'],section:'Insights'},
 {to:'/system',label:'System Status',icon:Activity,roles:['INVESTOR','LENDER'],section:'Insights'}
];
export function Shell(){
 const {role,session,logout,phase,setPhase,message,notify,backendReady,mode}=useApp();
 const navigate=useNavigate();
 function handleLogout(){logout();setOpen(false);navigate('/login',{replace:true});}
 const [open,setOpen]=useState(false);
 const [collapsed,setCollapsed]=useState(false);
 const menuButton=useRef<HTMLButtonElement>(null);
 useEffect(()=>{if(!open)return;const close=(event:KeyboardEvent)=>{if(event.key==='Escape'){setOpen(false);menuButton.current?.focus();}};document.addEventListener('keydown',close);return ()=>document.removeEventListener('keydown',close);},[open]);
 const location=useLocation();
 const items=nav.filter(item=>item.roles.includes(role));
 const title=nav.find(item=>item.to===location.pathname)?.label||'TokANSH Workspace';
 let current='';
 return <div className="flex min-h-screen bg-[#F7F9FC]">
  {open&&<button className="fixed inset-0 z-30 bg-slate-950/50 lg:hidden" aria-label="Close navigation" onClick={()=>setOpen(false)}/>}
  <aside id="workspace-navigation" aria-label="Workspace navigation" className={'fixed inset-y-0 left-0 z-40 flex flex-col bg-[#10233F] text-white transition-all lg:sticky lg:top-0 lg:h-screen '+(open?'visible translate-x-0':'invisible -translate-x-full lg:visible lg:translate-x-0')+' '+(collapsed?'w-20':'w-64')}>
   <div className="flex h-20 items-center justify-between border-b border-white/10 px-5">
    <NavLink to="/overview" className="flex items-center gap-2 text-lg font-extrabold tracking-tight" onClick={()=>setOpen(false)}><span className="rounded-lg border border-blue-300/40 bg-blue-400/15 p-1.5 text-blue-200">◈</span>{!collapsed&&<span>Tok<span className="text-blue-200">ANSH</span></span>}</NavLink>
    <button className="text-blue-200 lg:hidden" onClick={()=>setOpen(false)} aria-label="Close navigation"><X size={20}/></button>
   </div>
   <div className="overflow-y-auto px-3 py-5">
    {!collapsed&&<p className="mb-4 px-3 text-[10px] font-bold uppercase tracking-widest text-blue-200/70">Institutional Workspace</p>}
    {items.map(item=>{
      const section=item.section!==current;current=item.section;const Icon=item.icon;
      return <div key={item.to}>{section&&!collapsed&&<p className="mb-2 mt-5 px-3 text-[10px] font-bold uppercase tracking-wider text-blue-200/60">{item.section}</p>}
      <NavLink to={item.to} onClick={()=>setOpen(false)} className={({isActive})=>'mb-1 flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium '+(isActive?'bg-[#3478F6] text-white':'text-blue-100/80 hover:bg-white/10 hover:text-white')} title={collapsed?item.label:undefined}><Icon className="shrink-0" size={18}/>{!collapsed&&item.label}</NavLink></div>;
    })}
   </div>
   <div className="mt-auto p-3">
    <button className="hidden w-full items-center justify-center rounded-lg py-2 text-blue-100 hover:bg-white/10 lg:flex" onClick={()=>setCollapsed(x=>!x)} aria-label={collapsed?'Expand sidebar':'Collapse sidebar'}><ChevronDown className={collapsed?'rotate-90':'-rotate-90'} size={16}/></button>
   </div>
  </aside>
  <div className="min-w-0 flex-1" inert={open}>
   <header className="sticky top-0 z-20 flex min-h-[72px] flex-wrap items-center justify-between gap-3 border-b border-slate-200 bg-white px-5 py-3 lg:px-8">
    <div className="flex items-center gap-3"><button className="rounded-lg p-2 text-[#102B4E] lg:hidden" ref={menuButton} aria-controls="workspace-navigation" aria-expanded={open} aria-label="Open navigation" onClick={()=>setOpen(true)}><Menu size={22}/></button><div><p className="text-[10px] uppercase tracking-[.1em] text-slate-400">TokANSH / {role==='ISSUER'?'Issuer':role==='INVESTOR'?'Investor':'Lender'}</p><strong className="text-sm text-[#102B4E]">{title}</strong></div></div>
    <div className="flex flex-wrap items-center gap-2.5">
     {mode==='preview'?<Status value={backendReady?'PENDING':'UNAVAILABLE'}/>:<span className="text-xs text-slate-500">Commit evidence is shown per operation</span>}
     <div className="flex items-center gap-2 rounded-md border border-slate-200 bg-slate-50 px-2.5 py-1.5 text-xs text-slate-700"><span className="hidden font-medium text-slate-500 sm:inline">Signed in as</span><strong>{session?.display_name||'Account'}</strong>{role==='LENDER'&&session?.organization_id&&<span className="hidden text-slate-500 md:inline">· {session.organization_id}</span>}</div>
     <button className="flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-[#102B4E] hover:bg-slate-50" onClick={handleLogout} title="Sign out and choose another account"><LogOut size={15}/> <span className="hidden sm:inline">Logout</span></button>
     {mode==='preview'&&<label className="flex items-center gap-1.5 text-xs text-slate-500">Scenario <select aria-label="Preview scenario stage" className="max-w-[175px] rounded-md border border-slate-200 bg-white px-2 py-1.5 text-xs font-semibold text-[#102B4E]" value={phase} onChange={e=>setPhase(e.target.value as typeof phase)}>{phases.map(x=><option key={x.id} value={x.id}>{x.label}</option>)}</select></label>}
    </div>
   </header>
   <main className="mx-auto max-w-[1550px] px-4 py-6 md:px-8">
    <PreviewWarning compact connected={mode==='real'}/>
    {message&&<div role="status" className={'mt-4 flex justify-between gap-3 rounded-lg border p-3 text-sm '+(message.kind==='error'?'border-red-200 bg-red-50 text-red-800':'border-blue-200 bg-blue-50 text-blue-900')}><span>{message.text}</span><button onClick={()=>notify(null)} aria-label="Dismiss notification"><X size={16}/></button></div>}
    <div className="page-enter mt-6 min-w-0"><ConnectedBoundary mode={mode} path={location.pathname} title={title}><Outlet/></ConnectedBoundary></div>
    <footer className="mt-9 flex flex-wrap justify-between gap-2 border-t border-slate-200 pt-5 text-[11px] text-slate-400"><span>TokANSH · DRUNIX Hackathon 2026</span><span>{mode==='preview'?'Illustrative workspace · No actual property title, payment or DRUNIX commitment':'DRUNIX ownership · indicative financing and cash workflows'}</span></footer>
   </main>
  </div>
 </div>;
}
