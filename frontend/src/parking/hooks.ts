// Typed wrappers of the JavaScript helpers in components/ui.jsx.
import type { DependencyList } from "react";
import { useFetch as useFetchJs, useToast as useToastJs } from "../components/ui";

export interface Fetched<T> {
  data: T | null;
  error: Error | null;
  loading: boolean;
  reload: () => Promise<void>;
  setData: (v: T | null | ((prev: T | null) => T | null)) => void;
}
export function useFetchT<T>(fn: () => Promise<T>, deps: DependencyList = []): Fetched<T> {
  return useFetchJs(fn, deps as unknown[]) as unknown as Fetched<T>;
}
export const useToastT = () => useToastJs() as unknown as (msg: string, kind?: "success" | "error" | "warning" | "info") => void;
