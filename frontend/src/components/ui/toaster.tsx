import { Toaster as Sonner, toast } from "sonner";
import type { ThemeChoice } from "@/lib/theme";
import { useIsPhone } from "@/lib/useIsPhone";

export { toast };

/** On a phone, toasts sit just above the bottom tab bar. */
const ABOVE_TABS = { bottom: "calc(4.5rem + env(safe-area-inset-bottom))" };

export function Toaster({ theme = "dark" }: { theme?: ThemeChoice }) {
  const phone = useIsPhone();
  if (phone)
    return (
      <Sonner theme={theme} position="bottom-center" offset={ABOVE_TABS} mobileOffset={ABOVE_TABS} richColors closeButton />
    );
  return <Sonner theme={theme} position="bottom-right" richColors closeButton />;
}
