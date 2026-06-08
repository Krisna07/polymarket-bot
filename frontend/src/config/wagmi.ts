import { http, createConfig } from "wagmi";
import { injected, metaMask } from "wagmi/connectors";
import { polygon } from "wagmi/chains";

export const POLYGON_CHAIN_ID = polygon.id;

export const wagmiConfig = createConfig({
  chains: [polygon],
  connectors: [
    injected({ shimDisconnect: true }),
    metaMask({ dappMetadata: { name: "Polymarket Bot" } }),
  ],
  transports: {
    [polygon.id]: http(),
  },
  ssr: false,
});
