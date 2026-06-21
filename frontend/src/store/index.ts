import { create } from 'zustand';

const DEFAULT_USER = {
  id: 'u0010000-0000-4000-8000-000000000001',
  email: 'alice@example.com',
  name: 'Alice',
};

interface User {
  id: string;
  email: string;
  name: string | null;
}

interface AppState {
  token: string | null;
  user: User;
  isAuthenticated: boolean;
  setAuth: (token: string, user: User) => void;
  logout: () => void;
}

export const useAppStore = create<AppState>((set) => ({
  token: null,
  user: DEFAULT_USER,
  isAuthenticated: true,
  setAuth: (token, user) => set({ token, user, isAuthenticated: true }),
  logout: () => set({ token: null, user: DEFAULT_USER, isAuthenticated: false }),
}));
