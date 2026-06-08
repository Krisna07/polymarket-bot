/// <reference types="vite/client" />

interface Window {
  ethereum?: {
    isMetaMask?: boolean;
    request?: (args: { method: string; params?: unknown[] }) => Promise<unknown>;
  };
}
