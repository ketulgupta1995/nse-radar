import { vi } from "vitest";

type Listener = (e: MediaQueryListEvent) => void;

let phone = false;
const listeners = new Map<string, Set<Listener>>();

function isPhoneQuery(q: string): boolean {
  return q.includes("max-width: 767px");
}

function matches(q: string): boolean {
  return isPhoneQuery(q) && phone;
}

function fakeMatchMedia(q: string): MediaQueryList {
  const set = listeners.get(q) ?? new Set<Listener>();
  listeners.set(q, set);
  const mql = {
    media: q,
    get matches() {
      return matches(q);
    },
    onchange: null,
    addEventListener: (_t: string, l: Listener) => set.add(l),
    removeEventListener: (_t: string, l: Listener) => set.delete(l),
    addListener: (l: Listener) => set.add(l),
    removeListener: (l: Listener) => set.delete(l),
    dispatchEvent: () => true,
  };
  return mql as unknown as MediaQueryList;
}

/**
 * Pretend the viewport is a phone (`true`) or a laptop (`false`).
 * Stubs `window.matchMedia` and fires `change` on live phone-query listeners.
 * Wrap in `act(...)` when components are mounted.
 */
export function setPhone(on: boolean): void {
  phone = on;
  vi.stubGlobal("matchMedia", fakeMatchMedia);
  for (const [q, set] of listeners) {
    if (!isPhoneQuery(q)) continue;
    const e = { matches: matches(q), media: q } as MediaQueryListEvent;
    for (const l of [...set]) l(e);
  }
}
