// Typed view of the (JavaScript) auth context for the TypeScript screens.
import { useAuth as useAuthJs } from "../lib/auth";

export interface AuthUser {
  id: number; username: string; email: string; full_name: string; phone: string; department: string;
  role: string; is_active: boolean; permissions: string[]; is_owner?: boolean; must_change_password?: boolean;
}
export interface AuthApi {
  user: AuthUser;
  can: (permission: string) => boolean;
  logout: () => Promise<void>;
  login: (username: string, password: string) => Promise<AuthUser>;
  register: (body: { full_name: string; email: string; password: string; phone: string; department: string }) => Promise<AuthUser>;
  setUser: (u: AuthUser) => void;
}

export const useAuthT = () => useAuthJs() as unknown as AuthApi;
export const isStaff = (u: AuthUser) => u.role !== "EMPLOYEE";
