"use client";

import { createContext, useContext, useState, useEffect, useCallback, ReactNode } from "react";

interface User {
  id: string;
  email: string;
  name: string;
  role: "admin" | "clinician" | "coder" | "viewer";
  avatar?: string;
}

interface AuthContextType {
  user: User | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

const STORAGE_KEY = "raf_auth_user";

const DEMO_USERS: Record<string, { password: string; user: User }> = {
  "admin@raf.health": {
    password: "admin123",
    user: { id: "1", email: "admin@raf.health", name: "Admin User", role: "admin" },
  },
  "clinician@raf.health": {
    password: "clinician123",
    user: { id: "2", email: "clinician@raf.health", name: "Dr. Sarah Chen", role: "clinician" },
  },
  "coder@raf.health": {
    password: "coder123",
    user: { id: "3", email: "coder@raf.health", name: "Medical Coder", role: "coder" },
  },
};

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) {
      try {
        setUser(JSON.parse(stored));
      } catch {
        localStorage.removeItem(STORAGE_KEY);
      }
    }
    setIsLoading(false);
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    setIsLoading(true);
    
    await new Promise((resolve) => setTimeout(resolve, 800));
    
    const demoUser = DEMO_USERS[email.toLowerCase()];
    if (!demoUser || demoUser.password !== password) {
      setIsLoading(false);
      throw new Error("Invalid email or password");
    }

    const loggedInUser = demoUser.user;
    setUser(loggedInUser);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(loggedInUser));
    setIsLoading(false);
  }, []);

  const logout = useCallback(() => {
    setUser(null);
    localStorage.removeItem(STORAGE_KEY);
  }, []);

  return (
    <AuthContext.Provider
      value={{
        user,
        isLoading,
        isAuthenticated: !!user,
        login,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
