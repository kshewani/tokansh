import {createContext, useContext, useEffect, useRef, useState} from 'react';
import type {ReactNode} from 'react';
import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query';
import {api, ApiError, newIdempotencyKey, setSessionEndedHandler, setSessionToken} from '../api/client';
import {route} from '../api/contracts';
import type {LedgerOperation, SystemStatus} from '../api/contracts';
import type {DemoSession, Role} from '../lib/session';
import {clearDemoSession, readDemoSession, writeDemoSession} from '../lib/session';
import {shortRef} from '../lib/format';
import {createSubmitGuard, failureMessage} from '../lib/guard';

export type Message = {kind: 'error' | 'info' | 'success' | 'pending'; text: string} | null;
type Action = {path: string; body?: unknown; label: string; method?: 'POST' | 'PUT'};
type Context = {
  session: DemoSession | null; role: Role; login: (username: string, password: string) => Promise<void>; logout: () => void;
  message: Message; notify: (m: Message) => void;
  systemStatus: SystemStatus | null; backendReady: boolean; ledgerStatus: string;
  run: <T = unknown>(action: Action) => Promise<T | null>; submitting: boolean;
};
const ctx = createContext<Context | null>(null);

/** Finds the ledger operation in any backend response, so the UI reports finality honestly. */
export function findOperation(data: unknown): LedgerOperation | null {
  if (!data || typeof data !== 'object') return null;
  const d = data as Record<string, any>;
  for (const key of ['operation', 'transfer', 'release_operation', 'pledge_operation']) {
    if (d[key]?.operation_id) return d[key];
  }
  if (d.ledger?.operation?.operation_id) return d.ledger.operation;
  if (d.operation_id && d.status) return d as LedgerOperation;
  return null;
}

function describe(label: string, status: number, data: unknown, replay: boolean): Message {
  const op = findOperation(data);
  const prefix = replay ? '(Repeated request; original result shown.) ' : '';
  if (op?.status === 'COMMITTED') return {kind: 'success', text: `${prefix}${label}: committed on DRUNIX · tx ${shortRef(op.ledger_transaction_id, 16)}`};
  if (op && op.status === 'FAILED') return {kind: 'error', text: `${prefix}${label}: application step recorded, but the ledger operation failed (${op.error_code}). ${op.error_message ?? ''}`};
  if (status === 202 || op) return {kind: 'pending', text: `${prefix}${label}: submitted, outcome not yet confirmed (${op?.status ?? 'PENDING'}). Ownership is unchanged until a confirmed commit.`};
  return {kind: 'success', text: `${prefix}${label}: done.`};
}

export function AppProvider({children}: {children: ReactNode}) {
  const [session, setSession] = useState<DemoSession | null>(() => readDemoSession());
  const [message, notify] = useState<Message>(null);
  const queryClient = useQueryClient();
  setSessionToken(session?.token ?? null);
  useEffect(() => { setSessionToken(session?.token ?? null); }, [session]);
  useEffect(() => {
    setSessionEndedHandler(() => {
      clearDemoSession(); setSessionToken(null); setSession(null);
      notify({kind: 'info', text: 'Your session ended (the API may have restarted). Sign in again.'});
    });
    return () => setSessionEndedHandler(null);
  }, []);

  const health = useQuery({queryKey: ['system-status'], queryFn: () => api<SystemStatus>(route.status).then(r => r.data),
    refetchInterval: 20000, retry: 3, retryDelay: 5000});  // free hosts can take ~1 min to wake up
  const ledgerStatus = health.data?.components.find(c => c.name === 'DRUNIX gateway adapter')?.status ?? 'UNAVAILABLE';

  const mutation = useMutation({
    mutationFn: (a: Action) => api(a.path, {method: a.method || 'POST', body: a.body ?? {}, idempotencyKey: newIdempotencyKey()}),
    retry: false,  // never retry a financial or ledger request automatically
  });
  const guard = useRef(createSubmitGuard());

  async function run<T>(a: Action): Promise<T | null> {
    if (!guard.current.tryEnter()) {
      notify({kind: 'info', text: 'A request is already being submitted. Wait for its result.'});
      return null;
    }
    try {
      const res = await mutation.mutateAsync(a);
      notify(describe(a.label, res.status, res.data, res.replay));
      return res.data as T;
    } catch (e) {
      const err = e instanceof ApiError ? e : new ApiError(0, 'UNEXPECTED', String(e));
      notify({kind: err.code === 'LEDGER_OUTCOME_UNKNOWN' ? 'pending' : 'error',
        text: failureMessage(a.label, err.status, err.code, err.message)});
      return null;
    } finally {
      guard.current.exit();
      await queryClient.invalidateQueries();
    }
  }

  async function login(username: string, password: string) {
    const res = await api<{access_token: string; user: {id: string; name: string; username: string; role: string}}>(
      route.login, {method: 'POST', body: {username, password}});
    const u = res.data.user;
    const role: Role = u.role === 'INVESTOR' ? 'INVESTOR' : u.role === 'LENDER' ? 'LENDER' : 'ISSUER';
    const s = {role, userId: u.id, name: u.name, username: u.username, token: res.data.access_token};
    writeDemoSession(s);
    setSessionToken(s.token);
    setSession(s);
    notify(null);
    queryClient.clear();
  }
  function logout() {
    void api(route.logout, {method: 'POST', body: {}}).catch(() => undefined);
    clearDemoSession();
    setSessionToken(null);
    setSession(null);
    notify(null);
    queryClient.clear();
  }

  return <ctx.Provider value={{session, role: session?.role ?? 'ISSUER', login, logout, message, notify,
    systemStatus: health.data ?? null, backendReady: health.isSuccess, ledgerStatus, run, submitting: mutation.isPending}}>
    {children}
  </ctx.Provider>;
}
export function useApp() {
  const value = useContext(ctx);
  if (!value) throw new Error('AppProvider missing');
  return value;
}

/** GET helper bound to the signed-in demo user. */
export function useApi<T>(path: string | null, key?: unknown[]) {
  const {session} = useApp();
  return useQuery({queryKey: key ?? [path, session?.userId], enabled: !!session && !!path,
    queryFn: () => api<T>(path as string).then(r => r.data)});
}
