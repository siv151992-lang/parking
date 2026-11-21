import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { get, getToken, post, setMediaToken, setToken, setUnauthorizedHandler } from "./api";

const AuthCtx = createContext(null);
const MEDIA_REFRESH_MS = 30 * 60 * 1000; // media tokens live 60 minutes

async function refreshMediaToken() {
  try {
    setMediaToken((await post("/api/auth/media-token")).token);
  } catch {
    setMediaToken(null);
  }
}

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(() => !!getToken()); // nothing to check without a token

  // Sign in with the user returned by the server (fetches the media token first, so images work at once).
  const adopt = useCallback(async (u) => {
    if (u && !u.must_change_password) await refreshMediaToken();
    setUser(u);
  }, []);

  const logout = useCallback(async (callServer = true) => {
    if (callServer && getToken()) {
      try {
        await post("/api/auth/logout");
      } catch {
        /* ignore */
      }
    }
    setToken(null);
    setMediaToken(null);
    setUser(null);
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(() => {
      setToken(null);
      setMediaToken(null);
      setUser(null);
    });
    if (!getToken()) return;
    get("/api/auth/me")
      .then(adopt)
      .catch(() => setToken(null))
      .finally(() => setLoading(false));
  }, [adopt]);

  useEffect(() => {
    if (!user || user.must_change_password) return undefined;
    const t = setInterval(refreshMediaToken, MEDIA_REFRESH_MS);
    return () => clearInterval(t);
  }, [user]);

  const login = async (username, password) => {
    const r = await post("/api/auth/login", { username, password });
    setToken(r.access_token);
    await adopt(r.user);
    return r.user;
  };

  /** Change your own password. Other sessions of the account are signed out; this one gets a new token. */
  const changePassword = async (current_password, new_password) => {
    const r = await post("/api/auth/change-password", { current_password, new_password });
    setToken(r.access_token);
    await adopt(r.user);
  };

  const can = useCallback((perm) => !!user?.permissions?.includes(perm), [user]);

  return <AuthCtx.Provider value={{ user, loading, login, logout, can, changePassword }}>{children}</AuthCtx.Provider>;
}

export const useAuth = () => useContext(AuthCtx);
