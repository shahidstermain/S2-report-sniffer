import { Sun, Moon } from "lucide-react";
import { useTheme } from "@/hooks/useTheme";

export default function ThemeToggle() {
  const { theme, toggle, isDark } = useTheme();
  return (
    <button
      type="button"
      onClick={toggle}
      className="icon-btn"
      aria-label={`Theme: ${theme}. Cycle theme`}
      title={`Theme: ${theme}. Click for next mode`}
      data-testid="theme-toggle"
    >
      {isDark ? <Sun size={15} /> : <Moon size={15} />}
    </button>
  );
}
