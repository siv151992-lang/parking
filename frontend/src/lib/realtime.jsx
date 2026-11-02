import { createContext, useContext, useEffect, useRef, useState } from "react";
import { getToken } from "./api";

// One WebSocket per browser tab; components subscribe to event types.
const RtCtx = createContext(null);

export function RealtimeProvider({ children, enabled }) {
  const [connected, setConnected] = useState(false);
  const listeners = useRef(new Map());
  const wsRef = useRef(null);

  useEffect(() => {
    if (!enabled) return undefined;
    let stopped = false;
    let retry = 1000;
    let pingTimer;
    let reconnectTimer;

    const connect = () => {
      const proto = window.location.protocol === "https:" ? "wss" : "ws";
      const ws = new WebSocket(`${proto}://${window.location.host}/ws?token=${encodeURIComponent(getToken() || "")}`);
      wsRef.current = ws;
      ws.onopen = () => {
        setConnected(true);
        retry = 1000;
        pingTimer = setInterval(() => ws.readyState === 1 && ws.send("ping"), 25000);
      };
      ws.onmessage = (e) => {
        let msg;
        try {
          msg = JSON.parse(e.data);
        } catch {
          return;
        }
        const fire = (key) => (listeners.current.get(key) || []).forEach((fn) => fn(msg.data, msg));
        fire(msg.type);
        fire("*");
      };
      ws.onclose = (e) => {
        setConnected(false);
        clearInterval(pingTimer);
        if (stopped || e.code === 4401) return;
        reconnectTimer = setTimeout(connect, retry);
        retry = Math.min(retry * 2, 15000);
      };
      ws.onerror = () => ws.close();
    };
    connect();
    return () => {
      stopped = true;
      clearInterval(pingTimer);
      clearTimeout(reconnectTimer);
      wsRef.current?.close();
    };
  }, [enabled]);

  const subscribe = (types, fn) => {
    const list = Array.isArray(types) ? types : [types];
    list.forEach((t) => {
      if (!listeners.current.has(t)) listeners.current.set(t, []);
      listeners.current.get(t).push(fn);
    });
    return () => list.forEach((t) => listeners.current.set(t, (listeners.current.get(t) || []).filter((f) => f !== fn)));
  };

  return <RtCtx.Provider value={{ connected, subscribe }}>{children}</RtCtx.Provider>;
}

export const useRealtime = () => useContext(RtCtx);

/** Subscribe to realtime events; handler always sees latest closure. */
export function useEvent(types, handler) {
  const { subscribe } = useRealtime();
  const ref = useRef(handler);
  ref.current = handler;
  const key = Array.isArray(types) ? types.join(",") : types;
  useEffect(() => subscribe(key.split(","), (d, m) => ref.current(d, m)), [key]); // eslint-disable-line react-hooks/exhaustive-deps
}

/** Debounced refetch when any of the given events arrive. */
export function useLiveRefresh(types, refetch, delay = 600) {
  const timer = useRef();
  useEvent(types, () => {
    clearTimeout(timer.current);
    timer.current = setTimeout(refetch, delay);
  });
  useEffect(() => () => clearTimeout(timer.current), []);
}
