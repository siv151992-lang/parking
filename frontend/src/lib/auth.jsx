import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { get, getToken, post, setToken, setUnauthorizedHandler } from "./api";

const AuthCtx = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  const logout = useCallback(async (callServer = true) => {
    if (callServer && getToken()) {
      try {
        await post("/api/auth/logout");
      } catch {
        /* ignore */
      }
    }
    setToken(null);
    setUser(null);
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(() => {
      setToken(null);
      setUser(null);
    });
    if (!getToken()) {
      setLoading(false);
      return;
    }
    get("/api/auth/me")
      .then(setUser)
      .catch(() => setToken(null))
      .finally(() => setLoading(false));
  }, []);

  const login = async (username, password) => {
    const r = await post("/api/auth/login", { username, password });
    setToken(r.access_token);
    setUser(r.user);
    return r.user;
  };

  const can = useCallback((perm) => !!user?.permissions?.includes(perm), [user]);

  return <AuthCtx.Provider value={{ user, loading, login, logout, can }}>{children}</AuthCtx.Provider>;
}

export const useAuth = () => useContext(AuthCtx);
