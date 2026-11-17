/** Display formatting only. Amounts arrive from the API as decimal strings; the backend is the authority. */
export function inr(value: string | number | null | undefined, short = false): string {
  if (value === null || value === undefined || value === '') return '—';
  const amount = typeof value === 'string' ? Number(value) : value;
  if (!Number.isFinite(amount)) return '—';
  if (short && Math.abs(amount) >= 10000000) return '₹' + (amount / 10000000).toFixed(2) + ' Cr';
  if (short && Math.abs(amount) >= 100000) return '₹' + (amount / 100000).toFixed(2) + ' L';
  return '₹' + amount.toLocaleString('en-IN', {maximumFractionDigits: 2});
}
export function integer(value: number | null | undefined): string {
  return value === null || value === undefined ? '—' : value.toLocaleString('en-IN');
}
export function shortRef(ref: string | null | undefined, keep = 10): string {
  if (!ref) return '—';
  return ref.length > keep + 4 ? ref.slice(0, keep) + '…' + ref.slice(-4) : ref;
}
export function when(iso: string | null | undefined): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString('en-IN', {dateStyle: 'medium', timeStyle: 'short'});
}
/** Decimal-string multiply for display previews (quantity × price) without binary floating point. */
export function multiplyAmount(quantity: number, price: string): string {
  if (!Number.isSafeInteger(quantity) || !/^\d+(\.\d{1,2})?$/.test(price)) return '';
  const [whole, frac = ''] = price.split('.');
  const paise = BigInt(whole) * 100n + BigInt((frac + '00').slice(0, 2));
  const total = paise * BigInt(quantity);
  return (total / 100n).toString() + '.' + (total % 100n).toString().padStart(2, '0');
}
export function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}
