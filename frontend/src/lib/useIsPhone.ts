import { useEffect, useState } from "react";

/** Phone = viewport under 768 px (SPEC §17.9). */
export const PHONE_QUERY = "(max-width: 767px)";

function query(): MediaQueryList | null {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return null;
  return window.matchMedia(PHONE_QUERY);
}

/** True on a phone-width viewport; follows resizes live. False when matchMedia is missing. */
export function useIsPhone(): boolean {
  const [phone, setPhone] = useState<boolean>(() => query()?.matches ?? false);
  useEffect(() => {
    const mq = query();
    if (!mq) return;
    const onChange = () => setPhone(mq.matches);
    onChange();
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);
  return phone;
}
