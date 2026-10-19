export function backendIsOlder(running: string, bundled: string): boolean {
  const parse = (value: string) => /^\d+\.\d+\.\d+$/.test(value) ? value.split('.').map(Number) : null;
  const a = parse(running), b = parse(bundled);
  if (!a || !b) throw new Error('Unrecognized backend version. Check the configured address.');
  for (let i = 0; i < 3; i++) { if (a[i] !== b[i]) return a[i] < b[i]; }
  return false;
}
