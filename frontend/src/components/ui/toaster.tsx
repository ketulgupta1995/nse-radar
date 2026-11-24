import { Toaster as Sonner, toast } from "sonner";
import type { ThemeChoice } from "@/lib/theme";

export { toast };

export function Toaster({ theme = "dark" }: { theme?: ThemeChoice }) {
  return <Sonner theme={theme} position="bottom-right" richColors closeButton />;
}
