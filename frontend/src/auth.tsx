import { createContext, ReactNode, useCallback, useContext, useEffect, useState } from "react";
import { get, getToken, post, setToken, setUnauthorizedHandler } from "./api";
import { User } from "./types";

interface AuthState {
  user: User | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
  refresh: () => void;
}

const AuthContext = createContext<AuthState>(null as unknown as AuthState);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  const logout = useCallback(() => {
    setToken("");
    setUser(null);
  }, []);

  const refresh = useCallback(() => {
    if (!getToken()) {
      setUser(null);
      setLoading(false);
      return;
    }
    get<User>("/api/auth/me")
      .then(setUser)
      .catch(() => {
        setToken("");
        setUser(null);
      })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(() => {
      setToken("");
      setUser(null);
    });
    refresh();
  }, [refresh]);

  const login = useCallback(async (username: string, password: string) => {
    const resp = await post<{ token: string; user: User }>("/api/auth/login", {
      username,
      password,
    });
    setToken(resp.token);
    setUser(resp.user);
  }, []);

  return (
    <AuthContext.Provider value={{ user, loading, login, logout, refresh }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthState {
  return useContext(AuthContext);
}
