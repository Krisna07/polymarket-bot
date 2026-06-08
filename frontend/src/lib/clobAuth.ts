import { ClobClient } from "@polymarket/clob-client-v2";
import type { WalletClient } from "viem";

const CLOB_HOST = "https://clob.polymarket.com";
const CHAIN_ID = 137;

export async function createOrDeriveClobCredentials(walletClient: WalletClient) {
  const client = new ClobClient({
    host: CLOB_HOST,
    chain: CHAIN_ID,
    signer: walletClient,
  });
  return client.createOrDeriveApiKey();
}
