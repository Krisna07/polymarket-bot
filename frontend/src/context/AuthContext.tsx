import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  useAccount,
  useChainId,
  useConnect,
  useDisconnect,
  useSwitchChain,
  useWalletClient,
} from "wagmi";
import { POLYGON_CHAIN_ID } from "../config/wagmi";
import {
  bootstrapWallet,
  fetchAuthStatus,
  registerWallet,
} from "../lib/api";
import { createOrDeriveClobCredentials } from "../lib/clobAuth";
import { hasInjectedProvider, pickWalletConnector } from "../lib/wallet";

export type AuthPhase =
  | "idle"
  | "connecting"
  | "wrong_network"
  | "deriving_keys"
  | "registering"
  | "bootstrapping"
  | "ready"
  | "error";

type AuthContextValue = {
  phase: AuthPhase;
  error: string | null;
  address: string | undefined;
  walletDetected: boolean;
  connectWallet: () => Promise<void>;
  disconnectWallet: () => void;
  retrySetup: () => void;
  statusMessage: string;
};

const AuthContext = createContext<AuthContextValue | null>(null);

const STORAGE_KEY = "polymarket_wallet_address";

function phaseMessage(phase: AuthPhase): string {
  switch (phase) {
    case "connecting":
      return "Connecting wallet…";
    case "wrong_network":
      return "Switch to Polygon network in your wallet.";
    case "deriving_keys":
      return "Sign the message in your wallet to create Polymarket API keys…";
    case "registering":
      return "Registering session with the bot…";
    case "bootstrapping":
      return "Syncing markets, order books, and signals…";
    case "ready":
      return "Connected";
    case "error":
      return "Something went wrong";
    default:
      return "Connect your wallet to start";
  }
}

function formatConnectError(err: unknown): string {
  if (err instanceof Error) {
    if (err.message.includes("User rejected")) {
      return "Connection cancelled in wallet.";
    }
    return err.message;
  }
  return "Could not connect wallet";
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const { address, isConnected, status, isConnecting } = useAccount();
  const chainId = useChainId();
  const {
    connectAsync,
    connectors,
    isPending: isConnectPending,
    error: connectError,
    isError: isConnectError,
  } = useConnect();
  const { disconnect } = useDisconnect();
  const { switchChainAsync } = useSwitchChain();
  const { data: walletClient } = useWalletClient();

  const [phase, setPhase] = useState<AuthPhase>("idle");
  const [error, setError] = useState<string | null>(null);
  const setupStarted = useRef(false);
  const phaseRef = useRef<AuthPhase>("idle");
  const walletDetected = hasInjectedProvider();

  phaseRef.current = phase;

  const resetSetup = useCallback(() => {
    setupStarted.current = false;
  }, []);

  const runWalletSetup = useCallback(async () => {
    if (!address || !walletClient) return;
    if (setupStarted.current) return;
    setupStarted.current = true;
    setError(null);

    try {
      const existing = await fetchAuthStatus(address);
      if (existing.redis_ok === false) {
        throw new Error(
          existing.detail ??
            "Redis is not running. Start Docker, then run: docker compose up -d redis"
        );
      }
      if (
        existing.connected &&
        existing.has_api_keys &&
        existing.bootstrap_complete
      ) {
        localStorage.setItem(STORAGE_KEY, address);
        setPhase("ready");
        return;
      }

      if (!existing.connected || !existing.has_api_keys) {
        setPhase("deriving_keys");
        const creds = await createOrDeriveClobCredentials(walletClient);
        setPhase("registering");
        await registerWallet(address, creds);
      }

      const afterRegister = await fetchAuthStatus(address);
      if (!afterRegister.bootstrap_complete) {
        setPhase("bootstrapping");
        await bootstrapWallet(address);
      }

      localStorage.setItem(STORAGE_KEY, address);
      setPhase("ready");
    } catch (err) {
      setupStarted.current = false;
      setPhase("error");
      setError(err instanceof Error ? err.message : "Wallet setup failed");
    }
  }, [address, walletClient]);

  // Post-connect: network switch + API setup (do NOT reset phase while connecting)
  useEffect(() => {
    const connecting =
      isConnectPending || isConnecting || status === "reconnecting";

    if (connecting) {
      setPhase("connecting");
      return;
    }

    if (!isConnected || !address) {
      setPhase((current) => (current === "error" ? "error" : "idle"));
      resetSetup();
      return;
    }

    if (chainId !== POLYGON_CHAIN_ID) {
      setPhase("wrong_network");
      switchChainAsync({ chainId: POLYGON_CHAIN_ID }).catch((err) => {
        setupStarted.current = false;
        setPhase("error");
        setError(formatConnectError(err));
      });
      return;
    }

    if (
      walletClient &&
      phaseRef.current !== "error" &&
      phaseRef.current !== "ready"
    ) {
      void runWalletSetup();
    }
  }, [
    isConnected,
    address,
    chainId,
    walletClient,
    isConnectPending,
    isConnecting,
    status,
    switchChainAsync,
    runWalletSetup,
    resetSetup,
  ]);

  useEffect(() => {
    if (isConnectError && connectError) {
      setPhase("error");
      setError(formatConnectError(connectError));
    }
  }, [isConnectError, connectError]);

  const connectWallet = useCallback(async () => {
    setError(null);
    setPhase("connecting");

    if (isConnectPending || isConnecting || status === "reconnecting") {
      return;
    }

    if (isConnected && address) {
      resetSetup();
      void runWalletSetup();
      return;
    }

    if (!walletDetected) {
      setPhase("error");
      setError(
        "No Web3 wallet detected. Install MetaMask (or similar), then refresh this page."
      );
      return;
    }

    const connector = pickWalletConnector(connectors);
    if (!connector) {
      setPhase("error");
      setError("No wallet connector available. Refresh and try again.");
      return;
    }

    try {
      await connectAsync({
        connector,
        chainId: POLYGON_CHAIN_ID,
      });
    } catch (err) {
      setPhase("error");
      setError(formatConnectError(err));
    }
  }, [
    isConnectPending,
    isConnecting,
    status,
    isConnected,
    address,
    resetSetup,
    runWalletSetup,
    connectAsync,
    connectors,
    walletDetected,
  ]);

  const disconnectWallet = useCallback(() => {
    localStorage.removeItem(STORAGE_KEY);
    resetSetup();
    setPhase("idle");
    setError(null);
    disconnect();
  }, [disconnect, resetSetup]);

  const retrySetup = useCallback(() => {
    if (!isConnected || !address) {
      void connectWallet();
      return;
    }
    resetSetup();
    setError(null);
    void runWalletSetup();
  }, [resetSetup, runWalletSetup, isConnected, address, connectWallet]);

  const value: AuthContextValue = {
    phase,
    error,
    address,
    walletDetected,
    connectWallet,
    disconnectWallet,
    retrySetup,
    statusMessage: phaseMessage(phase),
  };

  return (
    <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within AuthProvider");
  }
  return ctx;
}
