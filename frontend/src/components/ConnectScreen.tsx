import { useAuth } from "../context/AuthContext";

type StepState = "done" | "active" | "upcoming";

function phaseContent(phase: ReturnType<typeof useAuth>["phase"]) {
  switch (phase) {
    case "connecting":
      return {
        eyebrow: "Wallet connection",
        title: "Approve the wallet connection",
        detail:
          "Your browser wallet should open a connection prompt. Approve it so the app can identify your Polygon address.",
        action: "Keep your wallet window open until the prompt completes.",
      };
    case "wrong_network":
      return {
        eyebrow: "Network switch",
        title: "Move the wallet to Polygon",
        detail:
          "The bot only works on Polygon. Accept the network switch request in your wallet before setup can continue.",
        action: "If no prompt appears, switch to Polygon manually and retry.",
      };
    case "deriving_keys":
      return {
        eyebrow: "Polymarket access",
        title: "Sign to create trading credentials",
        detail:
          "This signature creates the API credentials the backend uses for Polymarket data and trading actions. It does not send a transaction.",
        action: "Review the signature request in your wallet and approve it.",
      };
    case "registering":
      return {
        eyebrow: "Backend registration",
        title: "Saving your session to the bot",
        detail:
          "The app is storing your wallet session and Polymarket credentials so the advisor and bot can act on your behalf.",
        action: "No action needed here unless an error appears.",
      };
    case "bootstrapping":
      return {
        eyebrow: "Market sync",
        title: "Loading markets, order books, and signals",
        detail:
          "The bot is pulling the initial market dataset so the dashboard can show recommendations, pricing history, and bot state.",
        action: "This can take a short moment on first load.",
      };
    case "error":
      return {
        eyebrow: "Setup issue",
        title: "The connection flow stopped",
        detail:
          "The app could not finish wallet setup. Use the error below to decide whether you need to retry, switch networks, or start the backend services.",
        action: "Fix the issue shown below, then try again.",
      };
    case "ready":
      return {
        eyebrow: "Ready",
        title: "Wallet connected successfully",
        detail:
          "Setup is complete. The app will now load your dashboard, market analysis, and bot controls.",
        action: "You can continue directly into the dashboard.",
      };
    default:
      return {
        eyebrow: "Connect wallet",
        title: "Start by connecting your Polygon wallet",
        detail:
          "The app needs your wallet to create Polymarket credentials, sync your account state, and personalize the trading dashboard.",
        action: "Use MetaMask or another injected wallet in this browser.",
      };
  }
}

function stepState(currentPhase: ReturnType<typeof useAuth>["phase"], step: number): StepState {
  const progressMap: Record<ReturnType<typeof useAuth>["phase"], number> = {
    idle: 0,
    connecting: 1,
    wrong_network: 1,
    deriving_keys: 2,
    registering: 3,
    bootstrapping: 4,
    ready: 4,
    error: 0,
  };

  const progress = progressMap[currentPhase];
  if (progress >= step) {
    if (currentPhase !== "ready" && progress === step) return "active";
    return "done";
  }
  return "upcoming";
}

export function ConnectScreen() {
  const {
    phase,
    error,
    address,
    walletDetected,
    connectWallet,
    retrySetup,
    statusMessage,
  } = useAuth();

  const showConnect = !address && (phase === "idle" || phase === "error");
  const busy =
    phase === "connecting" ||
    phase === "wrong_network" ||
    phase === "deriving_keys" ||
    phase === "registering" ||
    phase === "bootstrapping";

  const handleConnect = () => {
    void connectWallet();
  };

  const content = phaseContent(phase);
  const steps = [
    {
      title: "Connect wallet",
      body: "Approve the site connection from your browser wallet.",
      state: stepState(phase, 1),
    },
    {
      title: "Create credentials",
      body: "Sign a message so the bot can access Polymarket APIs.",
      state: stepState(phase, 2),
    },
    {
      title: "Register session",
      body: "Store the wallet session and bot permissions on the backend.",
      state: stepState(phase, 3),
    },
    {
      title: "Sync data",
      body: "Load markets, order books, and initial signals for the dashboard.",
      state: stepState(phase, 4),
    },
  ];

  return (
    <div className="connect-screen">
      <div className="connect-card">
        <span className="connect-eyebrow">{content.eyebrow}</span>
        <h1>Polymarket Bot</h1>
        <p className="connect-lead">{content.title}</p>
        <p className="connect-detail">{content.detail}</p>

        <div className="connect-status-card">
          <div>
            <span className="connect-status-label">Current status</span>
            <p className="connect-status">{statusMessage}</p>
          </div>
          <p className="connect-action">{content.action}</p>
        </div>

        {!walletDetected && (
          <p className="connect-error">
            No wallet extension detected. Install{" "}
            <a
              href="https://metamask.io/download/"
              target="_blank"
              rel="noreferrer"
            >
              MetaMask
            </a>{" "}
            and refresh.
          </p>
        )}

        {address && (
          <div className="connect-address-card">
            <span className="connect-status-label">Connected wallet</span>
            <p className="connect-address">
              {address.slice(0, 6)}…{address.slice(-4)}
            </p>
          </div>
        )}

        {error && <p className="connect-error">{error}</p>}

        {showConnect && walletDetected && (
          <button type="button" className="connect-btn" onClick={handleConnect}>
            Connect Wallet
          </button>
        )}

        {phase === "error" && (
          <button
            type="button"
            className="connect-btn secondary"
            onClick={() => void retrySetup()}
          >
            Try Again
          </button>
        )}

        {busy && <div className="connect-spinner" aria-hidden />}

        <ul className="connect-steps">
          {steps.map((step) => (
            <li key={step.title} className={step.state}>
              <strong>{step.title}</strong>
              <span>{step.body}</span>
            </li>
          ))}
        </ul>

        <p className="connect-hint">
          Use Chrome or Edge with MetaMask unlocked. Approve the connection and
          Polygon network prompts. API must run on port 8000.
        </p>
      </div>
    </div>
  );
}
