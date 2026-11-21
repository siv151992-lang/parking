// Typed re-exports of the shared JavaScript UI components (components/ui.jsx) for TypeScript screens.
import type { ButtonHTMLAttributes, FC, ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import * as UI from "../components/ui";

type Icon = LucideIcon;
export const Button = UI.Button as unknown as FC<ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "danger" | "ghost" | "success"; size?: "sm" | "md"; icon?: Icon; loading?: boolean;
}>;
export const Modal = UI.Modal as unknown as FC<{ open: boolean; onClose: () => void; title: ReactNode; children?: ReactNode; footer?: ReactNode; wide?: boolean }>;
export const Badge = UI.Badge as unknown as FC<{ color?: string; children?: ReactNode; title?: string }>;
export const Card = UI.Card as unknown as FC<{ title?: ReactNode; action?: ReactNode; children?: ReactNode; className?: string; bodyClass?: string }>;
export const Spinner = UI.Spinner as unknown as FC;
export const Plate = UI.Plate as unknown as FC<{ value: string | null; size?: string }>;
export const PageHeader = UI.PageHeader as unknown as FC<{ title: ReactNode; subtitle?: ReactNode; children?: ReactNode }>;
import PasswordFormJs from "../components/PasswordForm";
export const PasswordForm = PasswordFormJs as unknown as FC<{ onDone?: () => void; submitLabel?: string }>;
