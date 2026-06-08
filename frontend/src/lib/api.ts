export async function fetchJson<T>(
  path: string,
  init?: RequestInit
): Promise<T> {
  const res = await fetch(path, init);
  if (!res.ok) {
    const raw = await res.text().catch(() => "");
    let message = raw || `${path} failed (${res.status})`;
    try {
      const parsed = JSON.parse(raw) as { detail?: string };
      if (parsed.detail) message = parsed.detail;
    } catch {
      /* use raw body */
    }
    throw new Error(message);
  }
  return res.json() as Promise<T>;
}

export type AuthStatus = {
  connected: boolean;
  address: string | null;
  has_api_keys: boolean;
  bootstrap_complete: boolean;
  redis_ok?: boolean;
  detail?: string;
};

export async function fetchAuthStatus(address?: string): Promise<AuthStatus> {
  const query = address ? `?address=${encodeURIComponent(address)}` : "";
  return fetchJson<AuthStatus>(`/api/auth/status${query}`);
}

export async function registerWallet(
  address: string,
  creds: { key: string; secret: string; passphrase: string }
): Promise<AuthStatus & { ok: boolean }> {
  return fetchJson("/api/auth/connect", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      address,
      api_key: creds.key,
      secret: creds.secret,
      passphrase: creds.passphrase,
      signature_type: 0,
    }),
  });
}

export async function bootstrapWallet(address: string): Promise<void> {
  await fetchJson(`/api/auth/bootstrap?address=${encodeURIComponent(address)}`, {
    method: "POST",
  });
}

export type WalletOverview = {
  wallet_address: string;
  proxy_wallet: string | null;
  display_name: string | null;
  positions_value_usd: number;
  holdings: Array<{
    title: string;
    outcome: string | null;
    size: number;
    avg_price: number;
    current_value: number;
    cash_pnl: number;
    condition_id: string | null;
  }>;
  holdings_count: number;
  bot_exposure_usd: number;
  bankroll_usd: number;
  investable_usd: number;
  per_trade_max_usd: number;
  max_total_exposure_usd: number;
  trading_mode: string;
  has_deposit: boolean;
};

export type InvestmentRecommendation = {
  market_id: number;
  question?: string;
  action: "buy_yes" | "buy_no" | "watch" | string;
  suggested_usd: number;
  edge_pct: number;
  confidence_pct: number;
  reasoning: string;
};

export type AdvisorResponse = {
  wallet: WalletOverview;
  opportunities: Array<{
    market_id: number;
    question: string;
    tags?: string[];
    edge_pct: number;
    edge?: number;
    confidence?: number;
    confidence_pct: number;
    market_probability: number;
    fair_probability: number;
    score: number;
    model_approved: boolean;
    research?: {
      keyword: string;
      google_search?: Array<{
        title?: string;
        link?: string;
        snippet?: string;
        displayLink?: string;
      }>;
      google_news?: Array<{
        title?: string;
        link?: string;
        published?: string;
        source?: string;
      }>;
      newsapi?: Array<{
        title?: string;
        url?: string;
        publishedAt?: string;
        source?: string;
        description?: string;
      }>;
      related_markets?: Array<{
        question?: string;
        category?: string;
        score?: number;
        slug?: string;
        condition_id?: string;
      }>;
    } | null;
  }>;
  advice: {
    summary: string;
    recommendations: InvestmentRecommendation[];
    source?: string;
  };
  source: string;
  ai_enabled: boolean;
  ai_connected: boolean;
  ai_model: string | null;
  research_sources?: {
    google_search: { configured: boolean; items: number };
    google_news: { configured: boolean; items: number };
    newsapi: { configured: boolean; items: number };
    related_markets: { configured: boolean; items: number };
  };
  research_enabled?: boolean;
  research_keyword?: string | null;
  analyzed_at: string;
  analysis_interval_sec: number;
  simulation?: {
    market_id: number;
    question: string;
    simulated_stake_usd: number;
    expected_profit_usd: number;
    chance_pct: number;
    note: string;
  } | null;
};

export type AdvisorModelsResponse = {
  available: boolean;
  active_model: string;
  models: string[];
};

export type MarketHistoryResponse = {
  market_id: number;
  points: Array<{
    snapshot_at: string;
    mid_price: number | null;
    best_bid: number | null;
    best_ask: number | null;
    spread: number | null;
    bid_depth: number | null;
    ask_depth: number | null;
    volume_24h: number | null;
  }>;
};

export type SimulationTrade = {
  market_id: number;
  question: string;
  side: string;
  entry_price: number;
  mark_price: number;
  shares: number;
  exposure_usd: number;
  pnl_usd: number;
  pnl_pct: number;
};

export type SimulationStatusResponse = {
  simulated: boolean;
  active: boolean;
  principal_usd: number;
  stop_loss_pct?: number | null;
  stop_reason?: string | null;
  started_at: string | null;
  invested_usd: number;
  current_value_usd: number;
  total_pnl_usd: number;
  total_pnl_pct: number;
  trades: SimulationTrade[];
  note?: string | null;
};

export function fetchWalletOverview(address: string) {
  return fetchJson<WalletOverview>(
    `/api/wallet/overview?address=${encodeURIComponent(address)}`
  );
}

export function fetchAdvisor(address: string, keyword?: string) {
  const query = keyword?.trim()
    ? `&keyword=${encodeURIComponent(keyword.trim())}`
    : "";
  return fetchJson<AdvisorResponse>(
    `/api/advisor/recommendations?address=${encodeURIComponent(address)}${query}`
  );
}

export function fetchAdvisorModels() {
  return fetchJson<AdvisorModelsResponse>("/api/advisor/models");
}

export function selectAdvisorModel(model: string) {
  return fetchJson<{ ok: boolean; active_model: string; models: string[] }>(
    "/api/advisor/models/select",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model }),
    }
  );
}

export function fetchMarketHistory(marketId: number, limit = 60) {
  return fetchJson<MarketHistoryResponse>(`/api/markets/${marketId}/history?limit=${limit}`);
}

export function startSimulation(
  amountUsd: number,
  stopLossPct?: number,
  allocationMode: "single" | "distributed" = "distributed",
  maxPositions = 3
) {
  return fetchJson<{
    ok: boolean;
    simulated: boolean;
    market_id: number;
    question: string;
    side: string;
    entry_price: number;
    shares: number;
    principal_usd: number;
    stop_loss_pct?: number | null;
    allocation_mode?: "single" | "distributed";
    tracked_positions?: number;
    legs?: Array<{
      market_id: number;
      question: string;
      side: string;
      entry_price: number;
      shares: number;
      exposure_usd: number;
      edge: number;
      score: number;
    }>;
  }>("/api/bot/simulation/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      amount_usd: amountUsd,
      ...(typeof stopLossPct === "number" ? { stop_loss_pct: stopLossPct } : {}),
      allocation_mode: allocationMode,
      max_positions: maxPositions,
    }),
  });
}

export function fetchSimulationStatus() {
  return fetchJson<SimulationStatusResponse>("/api/bot/simulation/status");
}

export function resetSimulation() {
  return fetchJson<{ ok: boolean; simulated: boolean }>("/api/bot/simulation/reset", {
    method: "POST",
  });
}

export function stopSimulation() {
  return fetchJson<{ ok: boolean; simulated: boolean }>("/api/bot/simulation/stop", {
    method: "POST",
  });
}
