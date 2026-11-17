/** Demo-only browser session. This is not authentication; the backend still enforces roles. */
export type Role = 'ISSUER' | 'INVESTOR' | 'LENDER';
export type DemoSession = {role: Role; userId: string; name: string};
export const DEMO_SESSION_KEY = 'tokansh-demo-session-v2';
export type SessionStorageLike = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;

export function isDemoRole(value: unknown): value is Role {
  return value === 'ISSUER' || value === 'INVESTOR' || value === 'LENDER';
}
function storage(store?: SessionStorageLike | null): SessionStorageLike | null {
  return store === undefined ? (typeof window === 'undefined' ? null : window.sessionStorage) : store;
}
export function readDemoSession(store?: SessionStorageLike | null): DemoSession | null {
  try {
    const raw = storage(store)?.getItem(DEMO_SESSION_KEY);
    if (!raw) return null;
    const value = JSON.parse(raw);
    return isDemoRole(value?.role) && typeof value.userId === 'string' && value.userId && typeof value.name === 'string'
      ? {role: value.role, userId: value.userId, name: value.name} : null;
  } catch {
    return null;
  }
}
export function writeDemoSession(session: DemoSession, store?: SessionStorageLike | null): void {
  try { storage(store)?.setItem(DEMO_SESSION_KEY, JSON.stringify(session)); } catch { /* in-memory state still works */ }
}
export function clearDemoSession(store?: SessionStorageLike | null): void {
  try { storage(store)?.removeItem(DEMO_SESSION_KEY); } catch { /* cleared from React state anyway */ }
}
export const roleOptions: {role: Role; label: string; description: string}[] = [
  {role: 'ISSUER', label: 'Admin / Issuer (Meera)', description: 'Property registry, approval, issuance, listings and distributions'},
  {role: 'INVESTOR', label: 'Investor (Aarav)', description: 'Marketplace, portfolio, purchases, pledge, simulated loan and income'},
  {role: 'LENDER', label: 'Lender', description: 'Simulated credit assessment, approval, disbursement and collateral review'},
];
