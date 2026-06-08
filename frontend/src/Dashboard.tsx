import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useAuth } from "./context/AuthContext";
import {
  type AdvisorResponse,
  type SimulationStatusResponse,
  fetchAdvisor,
  fetchAdvisorModels,
  fetchMarketHistory,
  fetchSimulationStatus,
  fetchJson,
  resetSimulation,
  selectAdvisorModel,
  startSimulation,
} from "./lib/api";

type Signal = {
  id: number;
  market_id: number;
  fair_probability: number;
  market_probability: number;
  edge: number;
  confidence: number;
  position_size: number;
  approved: boolean;
  rejection_reason: string | null;
  llm_summary: string | null;
};

function actionLabel(action: string) {
  if (action === "buy_yes") return "Buy YES";
  if (action === "buy_no") return "Buy NO";
  return "Watch";
}

function formatTime(timestamp: string) {
  return new Date(timestamp).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function formatCurrency(value: number | null | undefined) {
  return `$${(value ?? 0).toFixed(2)}`;
}

function formatWholeDollar(value: number | null | undefined) {
  return `$${Math.round(value ?? 0).toLocaleString()}`;
}

function formatSignedPercent(value: number, digits = 1) {
  return `${value >= 0 ? "+" : ""}${value.toFixed(digits)}%`;
}

function formatProbability(value: number | null | undefined) {
  if (value == null) return "—";
  return `${(value * 100).toFixed(1)}%`;
}

function sourceState(configured: boolean, items: number): "ok" | "warn" | "no" {
  if (!configured) return "no";
  if (items > 0) return "ok";
  return "warn";
}

function evidenceScore(opportunity: AdvisorResponse["opportunities"][number] | null): number {
  if (!opportunity) return 0;
  const confidence = Math.max(0, Math.min(100, opportunity.confidence_pct ?? 0));
  const research = opportunity.research;
  const evidenceCount =
    (research?.google_search?.length ?? 0) +
    (research?.google_news?.length ?? 0) +
    (research?.newsapi?.length ?? 0) +
    (research?.related_markets?.length ?? 0);
  return Math.round(Math.min(100, confidence * 0.7 + Math.min(30, evidenceCount * 3.5)));
}

function evidenceBand(score: number): "high" | "mid" | "low" {
  if (score >= 75) return "high";
  if (score >= 45) return "mid";
  return "low";
}

function countResearchItems(opportunity: AdvisorResponse["opportunities"][number] | null) {
  if (!opportunity?.research) return 0;
  return (
    (opportunity.research.google_search?.length ?? 0) +
    (opportunity.research.google_news?.length ?? 0) +
    (opportunity.research.newsapi?.length ?? 0) +
    (opportunity.research.related_markets?.length ?? 0)
  );
}

export default function Dashboard() {
  const { address, disconnectWallet } = useAuth();
  const [switchingModel, setSwitchingModel] = useState(false);
  const [countdown, setCountdown] = useState(60);
  const [selectedMarketId, setSelectedMarketId] = useState<number | null>(null);
  const [researchInput, setResearchInput] = useState("");
  const [appliedKeyword, setAppliedKeyword] = useState("");
  const [simulationAmount, setSimulationAmount] = useState("100");
  const [simulationAllocationMode, setSimulationAllocationMode] = useState<"single" | "distributed">("distributed");
  const [simulationMaxPositions, setSimulationMaxPositions] = useState("3");
  const [runningSimulation, setRunningSimulation] = useState(false);

  const advisor = useQuery({
    queryKey: ["advisor", address, appliedKeyword],
    queryFn: () => fetchAdvisor(address!, appliedKeyword),
    enabled: Boolean(address),
    staleTime: 10_000,
    refetchInterval: 60_000,
    refetchIntervalInBackground: true,
  });

  const advisorModels = useQuery({
    queryKey: ["advisorModels"],
    queryFn: fetchAdvisorModels,
    refetchInterval: 60_000,
    refetchIntervalInBackground: true,
  });

  const signals = useQuery({
    queryKey: ["signals"],
    queryFn: () => fetchJson<Signal[]>("/api/signals?limit=20"),
    refetchInterval: 30_000,
  });

  const simulation = useQuery({
    queryKey: ["simulationStatus"],
    queryFn: () => fetchSimulationStatus(),
    refetchInterval: (query): number => {
      const status = query.state.data as SimulationStatusResponse | undefined;
      return status?.active ? 5_000 : 15_000;
    },
  });

  const wallet = advisor.data?.wallet;
  const advice = advisor.data?.advice;
  const opportunities = advisor.data?.opportunities ?? [];
  const aiPickedMarketId = advice?.recommendations?.[0]?.market_id ?? advisor.data?.simulation?.market_id ?? null;
  const activeTradeMarketId = simulation.data?.trades?.[0]?.market_id ?? null;
  const focusMarketId = selectedMarketId ?? aiPickedMarketId ?? opportunities[0]?.market_id ?? null;
  const selectedOpportunity = opportunities.find((item) => item.market_id === focusMarketId) ?? null;
  const primaryRecommendation = advice?.recommendations?.[0] ?? null;
  const analysisIntervalSec = advisor.data?.analysis_interval_sec ?? 60;

  const sourceBadges = useMemo(() => {
    const sources = advisor.data?.research_sources;
    if (!sources) return [];
    return [
      {
        label: "Web Search",
        state: sourceState(sources.google_search.configured, sources.google_search.items),
        items: sources.google_search.items,
      },
      {
        label: "Google News",
        state: sourceState(sources.google_news.configured, sources.google_news.items),
        items: sources.google_news.items,
      },
      {
        label: "News Feed",
        state: sourceState(sources.newsapi.configured, sources.newsapi.items),
        items: sources.newsapi.items,
      },
      {
        label: "Related Markets",
        state: sourceState(sources.related_markets.configured, sources.related_markets.items),
        items: sources.related_markets.items,
      },
    ];
  }, [advisor.data?.research_sources]);

  const focusHistory = useQuery({
    queryKey: ["marketHistory", focusMarketId],
    queryFn: () => fetchMarketHistory(focusMarketId!),
    enabled: Boolean(focusMarketId),
    refetchInterval: 30_000,
  });

  const activeTradeHistory = useQuery({
    queryKey: ["marketHistory", "active", activeTradeMarketId],
    queryFn: () => fetchMarketHistory(activeTradeMarketId!),
    enabled: Boolean(activeTradeMarketId),
    refetchInterval: 15_000,
  });

  const chartData = opportunities.slice(0, 8).map((opportunity) => ({
    name: `M${opportunity.market_id}`,
    edge: opportunity.edge_pct,
  }));

  const shortAddress = address ? `${address.slice(0, 6)}…${address.slice(-4)}` : "—";
  const visibleRecommendations = advice?.recommendations.slice(0, 3) ?? [];
  const hiddenRecommendationCount = Math.max(
    0,
    (advice?.recommendations.length ?? 0) - visibleRecommendations.length,
  );
  const selectedEvidence = evidenceScore(selectedOpportunity);
  const selectedResearchItems = countResearchItems(selectedOpportunity);
  const totalResearchItems = sourceBadges.reduce((sum, source) => sum + source.items, 0);
  const advisorErrorMessage =
    advisor.error instanceof Error
      ? advisor.error.message
      : "Could not load advisor. Check whether the API is reachable on port 8000.";
  const analysisTone = advisor.error
    ? "error"
    : advisor.isFetching
      ? "active"
      : opportunities.length > 0
        ? "ok"
        : "warn";
  const analysisHeadline = advisor.error
    ? "Advisor unavailable"
    : advisor.isFetching
      ? "Refreshing market analysis"
      : opportunities.length > 0
        ? "Latest analysis is ready"
        : "Waiting for enough market data";
  const analysisDetail = advisor.error
    ? advisorErrorMessage
    : advisor.isFetching
      ? "The advisor is pulling fresh market data, research results, and ranking updates now."
      : opportunities.length > 0
        ? `${opportunities.length} ranked opportunities available. Next refresh is scheduled automatically.`
        : "The connection is live, but there are no ranked opportunities yet.";
  const simulationStatusLabel = simulation.data?.active
    ? "A paper trade is currently active and updating in real time."
    : simulation.data?.simulated
      ? "A completed paper simulation is available for review."
      : "No paper simulation is running right now.";
  const selectedMarketSummary = selectedOpportunity
    ? selectedOpportunity.model_approved
      ? "The active model currently approves this market as tradable under the configured rules."
      : "This market is being monitored, but it does not currently pass the active trading rules."
    : "Select a recommendation or ranked market to see why the model is paying attention to it.";

  useEffect(() => {
    setCountdown(analysisIntervalSec);
  }, [advisor.data?.analyzed_at, analysisIntervalSec]);

  useEffect(() => {
    if (!selectedMarketId && aiPickedMarketId) {
      setSelectedMarketId(aiPickedMarketId);
    }
  }, [selectedMarketId, aiPickedMarketId]);

  useEffect(() => {
    const timer = setInterval(() => {
      setCountdown((value) => {
        if (advisor.isFetching) return analysisIntervalSec;
        return value > 0 ? value - 1 : 0;
      });
    }, 1000);
    return () => clearInterval(timer);
  }, [advisor.isFetching, analysisIntervalSec]);

  const nextAnalysisLabel = useMemo(() => {
    if (advisor.isFetching) return "Refreshing analysis now";
    return `Next analysis in ${countdown}s`;
  }, [advisor.isFetching, countdown]);

  const focusChartData = (focusHistory.data?.points ?? []).map((point) => ({
    time: formatTime(point.snapshot_at),
    mid: point.mid_price ? point.mid_price * 100 : null,
    bid: point.best_bid ? point.best_bid * 100 : null,
    ask: point.best_ask ? point.best_ask * 100 : null,
  }));

  const activeChartData = (activeTradeHistory.data?.points ?? []).map((point) => ({
    time: formatTime(point.snapshot_at),
    mid: point.mid_price ? point.mid_price * 100 : null,
    volume: point.volume_24h,
  }));

  return (
    <div className="app dashboard-app">
      <header className="page-hero">
        <div className="page-hero-main">
          <span className="page-kicker">Decision center</span>
          <h1>Polymarket Bot</h1>
          <p className="page-summary">
            The dashboard now leads with what matters first: wallet readiness, the current AI recommendation, and the state of simulation and signals.
          </p>

          <div className="hero-meta">
            <span className="badge ok">Wallet {shortAddress}</span>
            {wallet?.display_name && <span className="badge">{wallet.display_name}</span>}
            {advisor.data && (
              <span className="badge">
                {advisor.data.source === "ollama" ? "AI analysis" : "Model analysis"}
              </span>
            )}
            {advisor.data && (
              <span className={`badge ${advisor.data.ai_connected ? "ok" : "no"}`}>
                {advisor.data.ai_connected
                  ? `AI connected${advisor.data.ai_model ? ` · ${advisor.data.ai_model}` : ""}`
                  : "AI disconnected"}
              </span>
            )}
          </div>

          <div className={`status-banner status-${analysisTone}`}>
            <div className="status-banner-head">
              <span className={`ai-pulse ${advisor.isFetching ? "active" : ""}`} />
              <strong>{analysisHeadline}</strong>
            </div>
            <p>{analysisDetail}</p>
          </div>

          <div className="analysis-cycle-row">
            <span className="badge">{nextAnalysisLabel}</span>
            {advisor.data?.analyzed_at && (
              <span className="analysis-time">Last updated {formatTime(advisor.data.analyzed_at)}</span>
            )}
          </div>

          {sourceBadges.length > 0 && (
            <div className="source-health-row">
              {sourceBadges.map((source) => (
                <span key={source.label} className={`badge health-${source.state}`}>
                  {source.label}: {source.items}
                </span>
              ))}
            </div>
          )}
        </div>

        <div className="card control-panel">
          <div className="control-group">
            <span className="control-label">Paper simulation</span>
            <div className="control-row">
              <input
                className="research-input"
                value={simulationAmount}
                onChange={(event) => setSimulationAmount(event.target.value)}
                placeholder="Simulation amount (USD)"
                inputMode="decimal"
              />
              <select
                className="research-input"
                value={simulationAllocationMode}
                onChange={(event) => setSimulationAllocationMode(event.target.value as "single" | "distributed")}
              >
                <option value="distributed">Distributed</option>
                <option value="single">Single</option>
              </select>
              <input
                className="research-input"
                value={simulationMaxPositions}
                onChange={(event) => setSimulationMaxPositions(event.target.value)}
                placeholder="Max positions"
                inputMode="numeric"
              />
              <button
                type="button"
                className="connect-btn header-btn"
                disabled={runningSimulation}
                onClick={async () => {
                  const amount = Number(simulationAmount);
                  const maxPositions = Number(simulationMaxPositions);
                  if (!Number.isFinite(amount) || amount <= 0) {
                    return;
                  }
                  if (!Number.isFinite(maxPositions) || maxPositions <= 0) {
                    return;
                  }
                  setRunningSimulation(true);
                  try {
                    await startSimulation(amount, undefined, simulationAllocationMode, Math.max(1, Math.floor(maxPositions)));
                    await Promise.all([simulation.refetch(), focusHistory.refetch()]);
                  } finally {
                    setRunningSimulation(false);
                  }
                }}
              >
                {runningSimulation ? "Running…" : "Run simulation"}
              </button>
            </div>
            <p className="control-helper">Creates one paper trade or a distributed basket, then tracks each leg without deploying live funds.</p>
            <button
              type="button"
              className="connect-btn secondary header-btn"
              onClick={async () => {
                await resetSimulation();
                await simulation.refetch();
              }}
            >
              Reset simulation
            </button>
          </div>

          <div className="control-group">
            <span className="control-label">Research keyword</span>
            <div className="control-row">
              <input
                className="research-input"
                value={researchInput}
                onChange={(event) => setResearchInput(event.target.value)}
                placeholder="Example: election, CPI, Fed"
              />
              <button
                type="button"
                className="connect-btn secondary header-btn"
                onClick={() => {
                  setAppliedKeyword(researchInput.trim());
                  void advisor.refetch();
                }}
              >
                Run research
              </button>
            </div>
            <p className="control-helper">
              {appliedKeyword
                ? `Current keyword: ${appliedKeyword}`
                : "Leave blank to let the advisor choose its own research theme."}
            </p>
          </div>

          {advisorModels.data && advisorModels.data.models.length > 0 && (
            <div className="control-group">
              <span className="control-label">Advisor model</span>
              <select
                className="model-select"
                value={advisorModels.data.active_model}
                disabled={switchingModel}
                onChange={async (event) => {
                  const model = event.target.value;
                  setSwitchingModel(true);
                  try {
                    await selectAdvisorModel(model);
                    await Promise.all([advisorModels.refetch(), advisor.refetch()]);
                  } finally {
                    setSwitchingModel(false);
                  }
                }}
              >
                {advisorModels.data.models.map((model) => (
                  <option key={model} value={model}>
                    {model}
                  </option>
                ))}
              </select>
            </div>
          )}

          <div className="action-row">
            <button
              type="button"
              className="connect-btn secondary header-btn"
              onClick={() => advisor.refetch()}
              disabled={advisor.isFetching}
            >
              {advisor.isFetching ? "Analyzing…" : "Refresh analysis"}
            </button>
            <button
              type="button"
              className="connect-btn secondary header-btn"
              onClick={disconnectWallet}
            >
              Disconnect
            </button>
          </div>
        </div>
      </header>

      {advisor.isLoading && (
        <div className="inline-alert info">
          Loading wallet context, market data, and the first advisor pass.
        </div>
      )}

      {advisor.error && <div className="inline-alert error">{advisorErrorMessage}</div>}

      {wallet && (
        <section className="overview-grid">
          <div className="card overview-card">
            <span className="overview-label">Current holdings</span>
            <strong className="overview-value">{formatCurrency(wallet.positions_value_usd)}</strong>
            <p className="overview-body">
              {wallet.holdings_count} open position{wallet.holdings_count === 1 ? "" : "s"}
            </p>
            {wallet.proxy_wallet && (
              <p className="overview-meta mono">
                Proxy {wallet.proxy_wallet.slice(0, 6)}…{wallet.proxy_wallet.slice(-4)}
              </p>
            )}
          </div>

          <div className="card overview-card">
            <span className="overview-label">Capital available</span>
            <strong className="overview-value">{formatCurrency(wallet.investable_usd)}</strong>
            <p className="overview-body">
              Up to {formatWholeDollar(wallet.per_trade_max_usd)} per trade and {formatWholeDollar(wallet.max_total_exposure_usd)} total exposure.
            </p>
            <p className="overview-meta">Bot exposure {formatCurrency(wallet.bot_exposure_usd)} · {wallet.trading_mode}</p>
          </div>

          <div className="card overview-card">
            <span className="overview-label">Simulation state</span>
            <strong className="overview-value">{simulation.data?.active ? "Running" : simulation.data?.simulated ? "Ready" : "Idle"}</strong>
            <p className="overview-body">{simulationStatusLabel}</p>
            <p className="overview-meta">
              {simulation.data?.trades?.length ?? 0} simulated trade{simulation.data?.trades?.length === 1 ? "" : "s"} tracked
            </p>
          </div>

          <div className="card overview-card">
            <span className="overview-label">Research coverage</span>
            <strong className="overview-value">{totalResearchItems}</strong>
            <p className="overview-body">Source items attached to the latest analysis cycle.</p>
            <p className="overview-meta">
              {advisor.data?.research_keyword
                ? `Manual keyword: ${advisor.data.research_keyword}`
                : "Automatic keyword discovery enabled."}
            </p>
          </div>
        </section>
      )}

      <section className="decision-grid">
        <div className="card feature-card highlight-card">
          <div className="feature-header">
            <div>
              <h2>What the AI thinks now</h2>
              <p className="chart-subtitle">
                Only the strongest current recommendations are shown here. Lower-priority opportunities stay in the detail section below.
              </p>
            </div>
            {primaryRecommendation && (
              <span className={`badge action-${primaryRecommendation.action}`}>
                {actionLabel(primaryRecommendation.action)}
              </span>
            )}
          </div>

          {advice ? (
            <>
              <p className="advice-summary">{advice.summary}</p>
              {visibleRecommendations.length > 0 ? (
                <div className="rec-list">
                  {visibleRecommendations.map((recommendation) => {
                    const opportunity =
                      opportunities.find((item) => item.market_id === recommendation.market_id) ?? null;
                    const score = evidenceScore(opportunity);
                    return (
                      <div
                        key={recommendation.market_id}
                        className={`rec-item ${selectedMarketId === recommendation.market_id ? "selected" : ""}`}
                        onClick={() => setSelectedMarketId(recommendation.market_id)}
                        role="button"
                        tabIndex={0}
                        onKeyDown={(event) => {
                          if (event.key === "Enter" || event.key === " ") {
                            event.preventDefault();
                            setSelectedMarketId(recommendation.market_id);
                          }
                        }}
                      >
                        <div className="rec-header">
                          <span className={`badge action-${recommendation.action}`}>
                            {actionLabel(recommendation.action)}
                          </span>
                          <span className={`badge evidence-${evidenceBand(score)}`}>
                            Evidence {score}/100
                          </span>
                          <span className="rec-edge">{formatSignedPercent(recommendation.edge_pct)} edge</span>
                          {recommendation.suggested_usd > 0 && (
                            <span className="rec-size">Stake {formatCurrency(recommendation.suggested_usd)}</span>
                          )}
                        </div>
                        <p className="rec-question">
                          #{recommendation.market_id} {recommendation.question ?? opportunity?.question}
                        </p>
                        <p className="rec-reason">{recommendation.reasoning}</p>
                      </div>
                    );
                  })}
                </div>
              ) : (
                <div className="empty-state">
                  <strong>No strong picks right now</strong>
                  <p>The advisor is connected, but nothing currently clears the model thresholds.</p>
                </div>
              )}

              {hiddenRecommendationCount > 0 && (
                <p className="section-note">
                  {hiddenRecommendationCount} additional ranked opportunit{hiddenRecommendationCount === 1 ? "y is" : "ies are"} available in the detailed market list below.
                </p>
              )}

              {advisor.data?.simulation && (
                <div className="simulation-note">
                  <strong>Live funds unavailable.</strong>
                  <p>
                    The advisor would place {formatCurrency(advisor.data.simulation.simulated_stake_usd)} on #{advisor.data.simulation.market_id} for an expected {formatCurrency(advisor.data.simulation.expected_profit_usd)} outcome at {advisor.data.simulation.chance_pct.toFixed(1)}% confidence.
                  </p>
                </div>
              )}
            </>
          ) : (
            <div className="empty-state">
              <strong>Waiting for the first advisor response</strong>
              <p>Once analysis completes, the highest-priority recommendation will appear here.</p>
            </div>
          )}
        </div>

        <div className="card selected-market-card">
          <div className="feature-header">
            <div>
              <h2>Selected market</h2>
              <p className="chart-subtitle">Pick a recommendation or ranked opportunity to inspect the case for it.</p>
            </div>
            {selectedOpportunity && (
              <span className={`badge ${selectedOpportunity.model_approved ? "ok" : "no"}`}>
                {selectedOpportunity.model_approved ? "Tradable" : "Watch only"}
              </span>
            )}
          </div>

          {selectedOpportunity ? (
            <>
              <p className="market-question">#{selectedOpportunity.market_id} {selectedOpportunity.question}</p>
              <p className="market-caption">{selectedMarketSummary}</p>
              <div className="market-stat-grid">
                <div className="market-stat">
                  <span className="market-stat-label">Edge</span>
                  <strong className={selectedOpportunity.edge_pct >= 0 ? "edge-positive" : "edge-negative"}>
                    {formatSignedPercent(selectedOpportunity.edge_pct)}
                  </strong>
                </div>
                <div className="market-stat">
                  <span className="market-stat-label">Confidence</span>
                  <strong>{selectedOpportunity.confidence_pct.toFixed(0)}%</strong>
                </div>
                <div className="market-stat">
                  <span className="market-stat-label">Market price</span>
                  <strong>{formatProbability(selectedOpportunity.market_probability)}</strong>
                </div>
                <div className="market-stat">
                  <span className="market-stat-label">Fair value</span>
                  <strong>{formatProbability(selectedOpportunity.fair_probability)}</strong>
                </div>
                <div className="market-stat">
                  <span className="market-stat-label">Evidence score</span>
                  <strong>{selectedEvidence}/100</strong>
                </div>
                <div className="market-stat">
                  <span className="market-stat-label">Research items</span>
                  <strong>{selectedResearchItems}</strong>
                </div>
              </div>
              {selectedOpportunity.research?.keyword && (
                <p className="section-note">Research keyword used: {selectedOpportunity.research.keyword}</p>
              )}
            </>
          ) : (
            <div className="empty-state">
              <strong>No market selected yet</strong>
              <p>When the advisor produces candidates, this panel will explain why one market is worth attention.</p>
            </div>
          )}
        </div>
      </section>

      {wallet && wallet.holdings.length > 0 && (
        <section className="card content-card">
          <div className="feature-header">
            <div>
              <h2>Open positions</h2>
              <p className="chart-subtitle">Your live Polymarket holdings and current paper PnL snapshot.</p>
            </div>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Market</th>
                  <th>Side</th>
                  <th>Value</th>
                  <th>PnL</th>
                </tr>
              </thead>
              <tbody>
                {wallet.holdings.map((holding, index) => (
                  <tr key={index}>
                    <td>{holding.title}</td>
                    <td>{holding.outcome ?? "—"}</td>
                    <td>{formatCurrency(holding.current_value)}</td>
                    <td className={holding.cash_pnl >= 0 ? "edge-positive" : "edge-negative"}>
                      {formatCurrency(holding.cash_pnl)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      <section className="operations-grid">
        <div className="card content-card">
          <div className="feature-header">
            <div>
              <h2>Paper simulation</h2>
              <p className="chart-subtitle">Run a sample trade to understand expected return, stake sizing, and live mark tracking.</p>
            </div>
            <span className={`badge ${simulation.data?.active ? "ok" : simulation.data?.simulated ? "health-warn" : "no"}`}>
              {simulation.data?.active ? "Running" : simulation.data?.simulated ? "Paused result" : "Idle"}
            </span>
          </div>

          <p className="section-note">{simulationStatusLabel}</p>

          <div className="bot-live-grid">
            <div className="bot-live-card">
              <span className="bot-live-label">Principal</span>
              <strong>{formatCurrency(simulation.data?.principal_usd)}</strong>
            </div>
            <div className="bot-live-card">
              <span className="bot-live-label">Current value</span>
              <strong>{formatCurrency(simulation.data?.current_value_usd)}</strong>
            </div>
            <div className="bot-live-card">
              <span className="bot-live-label">Total PnL</span>
              <strong className={(simulation.data?.total_pnl_usd ?? 0) >= 0 ? "edge-positive" : "edge-negative"}>
                {formatCurrency(simulation.data?.total_pnl_usd)}
              </strong>
            </div>
          </div>

          {simulation.data?.trades && simulation.data.trades.length > 0 ? (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Market</th>
                    <th>Side</th>
                    <th>Exposure</th>
                    <th>Entry</th>
                    <th>PnL</th>
                  </tr>
                </thead>
                <tbody>
                  {simulation.data.trades.map((trade) => (
                    <tr key={`${trade.market_id}-${trade.side}-${trade.entry_price}`}>
                      <td className="q-cell" title={trade.question}>
                        #{trade.market_id} {trade.question}
                      </td>
                      <td>{trade.side.toUpperCase()}</td>
                      <td>{formatCurrency(trade.exposure_usd)}</td>
                      <td>{(trade.entry_price * 100).toFixed(1)}%</td>
                      <td className={trade.pnl_usd >= 0 ? "edge-positive" : "edge-negative"}>
                        {formatCurrency(trade.pnl_usd)}
                        <div className="bot-live-meta">{trade.pnl_pct.toFixed(1)}%</div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="empty-state compact">
              <strong>No simulation trades yet</strong>
              <p>Run a simulation from the control panel to populate this section.</p>
            </div>
          )}
        </div>

        <div className="card content-card">
          <div className="feature-header">
            <div>
              <h2>Signal queue</h2>
              <p className="chart-subtitle">Recent model outputs and whether they were approved for trading.</p>
            </div>
          </div>

          {signals.data && signals.data.length > 0 ? (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Market</th>
                    <th>Edge</th>
                    <th>Confidence</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {signals.data.slice(0, 8).map((signal) => (
                    <tr key={signal.id}>
                      <td>#{signal.market_id}</td>
                      <td className={signal.edge >= 0 ? "edge-positive" : "edge-negative"}>
                        {(signal.edge * 100).toFixed(1)}%
                      </td>
                      <td>{(signal.confidence * 100).toFixed(0)}%</td>
                      <td>
                        <span className={`badge ${signal.approved ? "ok" : "no"}`}>
                          {signal.approved ? "Approved" : signal.rejection_reason ?? "Rejected"}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="empty-state compact">
              <strong>No signals yet</strong>
              <p>Signals will appear after the backend has synced enough market data to score opportunities.</p>
            </div>
          )}
        </div>
      </section>

      <details className="detail-section" open={Boolean(selectedOpportunity?.research)}>
        <summary className="detail-summary">Research evidence</summary>
        <div className="card detail-card">
          <div className="chart-card-header">
            <div>
              <h2>Source detail for the selected market</h2>
              <p className="chart-subtitle">
                {selectedOpportunity?.research?.keyword
                  ? `Sources pulled for keyword: ${selectedOpportunity.research.keyword}`
                  : "Select a ranked market to see what external evidence the advisor attached to it."}
              </p>
            </div>
            {selectedOpportunity && (
              <span className={`badge evidence-${evidenceBand(selectedEvidence)}`}>
                Evidence {selectedEvidence}/100
              </span>
            )}
          </div>

          {selectedOpportunity?.research ? (
            <div className="research-grid">
              <div className="research-panel">
                <h3>Web Search</h3>
                {(selectedOpportunity.research.google_search ?? []).length > 0 ? (
                  <ul className="research-list">
                    {(selectedOpportunity.research.google_search ?? []).map((item, index) => (
                      <li key={index}>
                        <a href={item.link} target="_blank" rel="noreferrer">
                          {item.title ?? item.link}
                        </a>
                        {item.snippet && <p>{item.snippet}</p>}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="chart-empty">No web results were attached to this market.</p>
                )}
              </div>

              <div className="research-panel">
                <h3>Google News</h3>
                {(selectedOpportunity.research.google_news ?? []).length > 0 ? (
                  <ul className="research-list">
                    {(selectedOpportunity.research.google_news ?? []).map((item, index) => (
                      <li key={index}>
                        <a href={item.link} target="_blank" rel="noreferrer">
                          {item.title ?? item.link}
                        </a>
                        <p>{[item.source, item.published].filter(Boolean).join(" · ")}</p>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="chart-empty">No Google News results were attached to this market.</p>
                )}
              </div>

              <div className="research-panel">
                <h3>News Feed</h3>
                {(selectedOpportunity.research.newsapi ?? []).length > 0 ? (
                  <ul className="research-list">
                    {(selectedOpportunity.research.newsapi ?? []).map((item, index) => (
                      <li key={index}>
                        <a href={item.url} target="_blank" rel="noreferrer">
                          {item.title ?? item.url}
                        </a>
                        {item.description && <p>{item.description}</p>}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="chart-empty">No news feed items were attached to this market.</p>
                )}
              </div>

              <div className="research-panel">
                <h3>Related markets</h3>
                {(selectedOpportunity.research.related_markets ?? []).length > 0 ? (
                  <ul className="research-list">
                    {(selectedOpportunity.research.related_markets ?? []).map((item, index) => (
                      <li key={index}>
                        <strong>{item.question}</strong>
                        <p>{[item.category, item.slug].filter(Boolean).join(" · ")}</p>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="chart-empty">No related Polymarket markets were attached to this market.</p>
                )}
              </div>
            </div>
          ) : (
            <div className="empty-state compact">
              <strong>No research detail yet</strong>
              <p>Research evidence appears after you select a market that includes attached source results.</p>
            </div>
          )}
        </div>
      </details>

      <details className="detail-section">
        <summary className="detail-summary">Charts and ranked opportunities</summary>
        <div className="grid detail-grid">
          <div className="card chart-card chart-card-wide">
            <div className="chart-card-header">
              <div>
                <h2>Selected market history</h2>
                <p className="chart-subtitle">
                  {focusMarketId
                    ? `Order book curve for #${focusMarketId}${selectedMarketId === aiPickedMarketId ? " · current AI focus" : ""}`
                    : "No market selected yet."}
                </p>
              </div>
              {focusMarketId && <span className="badge ok">Selected</span>}
            </div>
            {focusChartData.length > 0 ? (
              <ResponsiveContainer width="100%" height={280}>
                <LineChart data={focusChartData}>
                  <CartesianGrid stroke="#2d3142" strokeDasharray="3 3" />
                  <XAxis dataKey="time" stroke="#9aa0a6" minTickGap={28} />
                  <YAxis stroke="#9aa0a6" unit="%" />
                  <Tooltip />
                  <Line type="monotone" dataKey="mid" stroke="#34a853" strokeWidth={2.2} dot={false} name="Mid" />
                  <Line type="monotone" dataKey="bid" stroke="#4285f4" strokeWidth={1.3} dot={false} name="Bid" />
                  <Line type="monotone" dataKey="ask" stroke="#f9ab00" strokeWidth={1.3} dot={false} name="Ask" />
                </LineChart>
              </ResponsiveContainer>
            ) : (
              <p className="chart-empty">
                {focusHistory.isLoading
                  ? "Loading market history..."
                  : "Not enough order book history is available for the selected market yet."}
              </p>
            )}
          </div>

          <div className="card chart-card">
            <div className="chart-card-header">
              <div>
                <h2>Active simulation market</h2>
                <p className="chart-subtitle">
                  {activeTradeMarketId
                    ? `Latest simulation is tracking #${activeTradeMarketId}`
                    : "No active or recent simulation trade is available yet."}
                </p>
              </div>
              {activeTradeMarketId && <span className="badge">Simulation focus</span>}
            </div>
            {activeChartData.length > 0 ? (
              <ResponsiveContainer width="100%" height={250}>
                <AreaChart data={activeChartData}>
                  <CartesianGrid stroke="#2d3142" strokeDasharray="3 3" />
                  <XAxis dataKey="time" stroke="#9aa0a6" minTickGap={28} />
                  <YAxis stroke="#9aa0a6" unit="%" />
                  <Tooltip />
                  <Area type="monotone" dataKey="mid" stroke="#8ab4f8" fill="#1e3a5f" strokeWidth={2} name="Mid" />
                </AreaChart>
              </ResponsiveContainer>
            ) : (
              <p className="chart-empty">
                {activeTradeHistory.isLoading
                  ? "Loading simulation market history..."
                  : "Once a simulation is running, its recent curve will appear here."}
              </p>
            )}
          </div>

          <div className="card content-card">
            <div className="feature-header">
              <div>
                <h2>Ranked opportunities</h2>
                <p className="chart-subtitle">Click any market to update the selected-market and research panels above.</p>
              </div>
            </div>
            {opportunities.length > 0 ? (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Market</th>
                      <th>Edge</th>
                      <th>Confidence</th>
                      <th>Market %</th>
                    </tr>
                  </thead>
                  <tbody>
                    {opportunities.map((opportunity) => (
                      <tr
                        key={opportunity.market_id}
                        className={selectedMarketId === opportunity.market_id ? "market-row-selected" : ""}
                        onClick={() => setSelectedMarketId(opportunity.market_id)}
                      >
                        <td className="q-cell" title={opportunity.question}>
                          #{opportunity.market_id} {opportunity.question.length > 58 ? `${opportunity.question.slice(0, 58)}…` : opportunity.question}
                        </td>
                        <td className={opportunity.edge_pct >= 0 ? "edge-positive" : "edge-negative"}>
                          {formatSignedPercent(opportunity.edge_pct)}
                        </td>
                        <td>{opportunity.confidence_pct.toFixed(0)}%</td>
                        <td>{formatProbability(opportunity.market_probability)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="empty-state compact">
                <strong>No ranked opportunities yet</strong>
                <p>Wait for bootstrap and analysis to complete, then ranked markets will appear here.</p>
              </div>
            )}
          </div>

          <div className="card content-card">
            <div className="feature-header">
              <div>
                <h2>Edge by market</h2>
                <p className="chart-subtitle">Quick comparison of the strongest currently ranked markets.</p>
              </div>
            </div>
            {chartData.length > 0 ? (
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={chartData}>
                  <XAxis dataKey="name" stroke="#9aa0a6" />
                  <YAxis stroke="#9aa0a6" />
                  <Tooltip />
                  <Bar dataKey="edge" fill="#4285f4" />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <p className="chart-empty">Edge comparison will appear once markets have been ranked.</p>
            )}
          </div>
        </div>
      </details>

      {wallet && !wallet.has_deposit && (
        <div className="inline-alert warn">
          No funded Polymarket balance detected. You can still inspect analysis and run simulations, but recommendations remain informational until funds are available.
        </div>
      )}
    </div>
  );
}
