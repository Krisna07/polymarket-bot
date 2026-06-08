import type { Connector } from "wagmi";

export function hasInjectedProvider(): boolean {
  return typeof window !== "undefined" && Boolean(window.ethereum);
}

export function pickWalletConnector(connectors: readonly Connector[]): Connector | null {
  const ready = connectors.filter((c) => c.ready);
  const preferred = ready.find((c) => c.id === "metaMaskSDK" || c.id === "io.metamask");
  if (preferred) return preferred;

  const injectedConnector = ready.find(
    (c) => c.type === "injected" || c.id === "injected"
  );
  if (injectedConnector) return injectedConnector;

  if (ready[0]) return ready[0];
  if (connectors[0]) return connectors[0];
  return null;
}

export function connectorLabel(connector: Connector): string {
  if (connector.name) return connector.name;
  return connector.id;
}
