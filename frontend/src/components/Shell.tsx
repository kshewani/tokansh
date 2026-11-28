import {useEffect,useRef,useState} from 'react';
import {NavLink,Outlet,useLocation,useNavigate} from 'react-router-dom';
import {Activity,BarChart3,Building2,ChevronLeft,ChevronRight,Compass,FileClock,HandCoins,Landmark,LayoutDashboard,LogOut,Menu,UserCircle,Wallet,X} from 'lucide-react';
import type {LucideIcon} from 'lucide-react';
import type {Role} from '../demo/scenario';
import {phases} from '../demo/scenario';
import {useApp} from '../app/context';
import {ConnectedBoundary} from './ConnectedBoundary';
type MenuItem={to:string;label:string;icon:LucideIcon;roles:Role[];section:string};
const nav:MenuItem[]=[
 {to:'/overview',label:'Dashboard',icon:LayoutDashboard,roles:['INVESTOR'],section:'Invest'},
 {to:'/marketplace',label:'Explore Assets',icon:Compass,roles:['INVESTOR'],section:'Invest'},
 {to:'/registry',label:'Create Property',icon:Building2,roles:['INVESTOR'],section:'Invest'},
 {to:'/portfolio',label:'My Portfolio',icon:Wallet,roles:['INVESTOR'],section:'Invest'},
 {to:'/collateral',label:'Borrow Against ANSH',icon:Landmark,roles:['INVESTOR'],section:'Liquidity'},
 {to:'/wallet',label:'Cash Wallet',icon:HandCoins,roles:['INVESTOR'],section:'Liquidity'},
 {to:'/lending',label:'Application Review',icon:Landmark,roles:['LENDER'],section:'Institution'},
 {to:'/transactions',label:'Activity',icon:FileClock,roles:['INVESTOR','LENDER'],section:'Insights'},
 {to:'/intelligence',label:'Asset Research',icon:BarChart3,roles:['INVESTOR'],section:'Insights'},
 {to:'/system',label:'System Status',icon:Activity,roles:['INVESTOR','LENDER'],section:'Insights'}
];
export function Shell(){
 const {role,session,logout,phase,setPhase,backendReady,mode}=useApp();
 const navigate=useNavigate();
 const [open,setOpen]=useState(false),[collapsed,setCollapsed]=useState(false),[profileOpen,setProfileOpen]=useState(false);
 const menuButton=useRef<HTMLButtonElement>(null);
 const location=useLocation();
 const items=nav.filter(item=>item.roles.includes(role));
 const title=nav.find(item=>item.to===location.pathname)?.label||'TokANSH Workspace';
 function handleLogout(){void logout();setOpen(false);setProfileOpen(false);navigate('/login',{replace:true});}
 useEffect(()=>{if(!open)return;const close=(event:KeyboardEvent)=>{if(event.key==='Escape'){setOpen(false);menuButton.current?.focus();}};document.addEventListener('keydown',close);return ()=>document.removeEventListener('keydown',close);},[open]);
 useEffect(()=>{setProfileOpen(false);},[location.pathname]);
 let current='';
 return <div className="premium-app flex min-h-screen">
  {open&&<button className="fixed inset-0 z-30 bg-black/70 lg:hidden" aria-label="Close navigation" onClick={()=>setOpen(false)}/>}
  <aside id="workspace-navigation" aria-label="Workspace navigation" className={'premium-sidebar fixed inset-y-0 left-0 z-40 flex flex-col text-white transition-all duration-200 lg:sticky lg:top-0 lg:h-screen '+(open?'visible translate-x-0':'invisible -translate-x-full lg:visible lg:translate-x-0')+' '+(collapsed?'w-20':'w-64')}>
   <div className="flex h-[7.4rem] items-center justify-between border-b border-white/10 px-5">
    <NavLink to="/overview" className="flex min-w-0 items-center gap-3" onClick={()=>setOpen(false)}><img className="premium-logo" src="/images/tokansh-logo.png" alt="TokANSH" /></NavLink>
    <button className="text-[#f5d78e] lg:hidden" onClick={()=>setOpen(false)} aria-label="Close navigation"><X size={20}/></button>
   </div>
   <div className="relative z-10 overflow-y-auto px-3 py-5">
    {!collapsed&&<p className="mb-4 px-3 text-[10px] font-bold uppercase tracking-[.18em] text-[#a5afbd]">Investment workspace</p>}
    {items.map(item=>{
      const section=item.section!==current;current=item.section;const Icon=item.icon;
      return <div key={item.to}>{section&&!collapsed&&<p className="mb-2 mt-5 px-3 text-[10px] font-bold uppercase tracking-[.16em] text-[#8b96a6]">{item.section}</p>}
       <NavLink to={item.to} onClick={()=>setOpen(false)} className={({isActive})=>'premium-nav-link mb-1 flex items-center gap-3 rounded-lg px-3 py-3 text-sm font-medium '+(isActive?'text-white':'')} data-active={location.pathname===item.to?'true':'false'} title={collapsed?item.label:undefined}><Icon className="shrink-0" size={18}/>{!collapsed&&item.label}</NavLink>
      </div>;
    })}
   </div>
   <div className="relative z-10 mt-auto p-3">
    <button className="hidden w-full items-center justify-center rounded-lg py-3 text-[#a5afbd] hover:bg-white/10 lg:flex" onClick={()=>setCollapsed(x=>!x)} aria-label={collapsed?'Expand sidebar':'Collapse sidebar'} title={collapsed?'Expand sidebar':'Collapse sidebar'}>{collapsed?<ChevronRight size={17}/>:<ChevronLeft size={17}/>}</button>
   </div>
  </aside>
  <div className="min-w-0 flex-1" inert={open}>
   <header className="premium-header sticky top-0 z-20 flex min-h-[76px] flex-wrap items-center justify-between gap-3 border-b px-5 py-3 lg:px-8">
    <div className="flex min-w-0 items-center gap-3"><button className="mobile-menu-button rounded-lg p-2 lg:hidden" ref={menuButton} aria-controls="workspace-navigation" aria-expanded={open} aria-label="Open navigation" onClick={()=>setOpen(true)}><Menu size={21}/></button><div className="min-w-0"><p className="truncate text-[10px] uppercase tracking-[.14em]">TokANSH / {role==='ISSUER'?'Issuer':role==='INVESTOR'?'Investor':'Lender'}</p><strong className="block truncate text-sm">{title}</strong></div></div>
    <div className="relative flex flex-wrap items-center justify-end gap-2.5">
     <span className="hidden items-center gap-2 text-xs sm:flex"><span className="status-dot h-2 w-2 rounded-full"/>{mode==='preview'?'Illustrative workspace':backendReady?'Ledger observations available':'Service status unavailable'}</span>
     <button className="premium-profile flex items-center gap-2 rounded-full border px-2.5 py-1.5 text-left" aria-expanded={profileOpen} aria-haspopup="menu" onClick={()=>setProfileOpen(value=>!value)}><span className="gold-icon h-8 w-8 text-sm"><UserCircle size={18}/></span><span className="hidden max-w-[130px] sm:block"><strong className="block truncate text-xs">{session?.display_name||'Account'}</strong><span className="block truncate text-[10px]">{role==='LENDER'&&session?.organization_id?session.organization_id:'Investor account'}</span></span><ChevronRight className={'transition-transform '+(profileOpen?'rotate-90':'')} size={14}/></button>
     {profileOpen&&<div className="premium-profile-menu absolute right-0 top-14 z-50 min-w-[210px] rounded-xl p-2" role="menu"><div className="border-b border-[#2b3647] px-3 py-2"><p className="text-xs font-semibold text-[#f5f1e8]">{session?.display_name||'Account'}</p><p className="mt-1 break-all text-[10px] text-[#a5afbd]">{session?.user_id||'No active identity'}</p></div><button className="mt-2 flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-xs font-semibold text-[#f5f1e8] hover:bg-white/10" onClick={handleLogout} role="menuitem"><LogOut size={15}/> Logout / switch account</button></div>}
     {mode==='preview'&&<label className="flex items-center gap-1.5 text-xs text-[#a5afbd]">Scenario <select aria-label="Preview scenario stage" className="max-w-[175px] rounded-md border px-2 py-1.5 text-xs font-semibold" value={phase} onChange={e=>setPhase(e.target.value as typeof phase)}>{phases.map(x=><option key={x.id} value={x.id}>{x.label}</option>)}</select></label>}
    </div>
   </header>
   <main className="premium-main mx-auto max-w-[1550px] px-4 py-6 md:px-8"><div className="page-enter mt-2 min-w-0"><ConnectedBoundary mode={mode} path={location.pathname} title={title}><Outlet/></ConnectedBoundary></div><footer className="premium-footer mt-9 flex flex-wrap justify-between gap-2 border-t pt-5 text-[11px]"><span>TokANSH · Unlocking Real Estate, One Ansh at a Time</span><span>{mode==='preview'?'Illustrative workflow · no actual title, payment or ledger commitment':'DRUNIX ownership · indicative financing and cash workflows'}</span></footer></main>
  </div>
 </div>;
}
