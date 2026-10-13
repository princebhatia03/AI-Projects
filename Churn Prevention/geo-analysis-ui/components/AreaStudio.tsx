"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { ChevronRight } from "lucide-react";
import { InfoTip } from "@/components/InfoTip";
import { SearchableSelect } from "@/components/SearchableSelect";
import {
  API_URL,
  CampaignRecord,
  ContractChurn,
  CustomerCard,
  Offer,
  PincodeDetail,
  Place,
  DomainChurnMetric,
  UpsellOpportunity,
  formatEuro,
  formatShare,
  formatSignedShare,
  predictionSign,
  realisticUpsellGain,
  totalRealisticUpsellGain,
  totalYearlyUpsell,
  yearlyUpsellAmount,
} from "@/lib/types";

function formatWhen(iso?: string) {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

const TIPS = {
  riskImpact:
    "Combined view: high-risk customer count and the euro CLV at risk if those customers churn.",
  totalClv: "Sum of customer lifetime value (€) across all subscribers still active in this zip.",
  predictedRisk: "Share of active customers in this zip predicted as high risk of churn.",
  byContract: "Churn prediction rates split by service line: Fixed, Mobile, or Bundle.",
  upsell:
    "Yearly upsell (€/year): customers × yearly ARPU uplift from behaviour gaps. Subtitle shows expected gain after take-rate and upsell CLV. Open the arrow for product plays.",
  churnDomains:
    "Churn risk broken down by domain: Demographics, Location, Population, Services, and Status.",
  customers:
    "Per-customer view: open AI Suggested Campaigns Only to review problem-fit offers and trigger one.",
};

const RISK_LEVELS = ["High", "Medium", "Low"] as const;

function ConfidenceBadge({
  score,
  level,
}: {
  score?: number | null;
  level?: string | null;
}) {
  if (score == null) return null;
  const tone = level === "high" || level === "medium" || level === "low" ? level : "low";
  return (
    <span className={`confidence-badge ${tone}`} title="AI confidence that this campaign fits the customer">
      {Math.round(score)}% {tone}
    </span>
  );
}

function riskClass(prediction: string) {
  if (prediction === "High") return "risk high";
  if (prediction === "Medium") return "risk medium";
  return "risk low";
}

type AreaStudioProps = {
  initialCity?: string;
  initialState?: string;
  initialZip?: string;
  onBack?: () => void;
  sharedPlaces?: Place[];
  onPlacesChange?: (places: Place[]) => void;
};

export function AreaStudio({
  initialCity = "",
  initialState = "",
  initialZip = "",
  onBack,
  sharedPlaces,
  onPlacesChange,
}: AreaStudioProps) {
  const [places, setPlaces] = useState<Place[]>(sharedPlaces || []);
  const [offers, setOffers] = useState<Offer[]>([]);
  const [city, setCity] = useState(initialCity);
  const [zip, setZip] = useState(initialZip);
  const [detail, setDetail] = useState<PincodeDetail | null>(null);
  const [status, setStatus] = useState("Checking backend…");
  const [running, setRunning] = useState(false);
  const [campaignBusy, setCampaignBusy] = useState(false);
  const [actionsBusy, setActionsBusy] = useState(false);
  const [explainingId, setExplainingId] = useState<string | null>(null);
  const aiRequested = useRef<Set<string>>(new Set());
  const [riskDialog, setRiskDialog] = useState<{
    open: boolean;
    loading: boolean;
    customerRef: string;
    customerId: string;
    prediction?: string;
    probability?: number;
    text: string | null;
    error: string | null;
  }>({
    open: false,
    loading: false,
    customerRef: "",
    customerId: "",
    text: null,
    error: null,
  });
  const [campaignDialog, setCampaignDialog] = useState<{
    open: boolean;
    customer: CustomerCard | null;
    selectedOfferId: string | null;
  }>({
    open: false,
    customer: null,
    selectedOfferId: null,
  });
  const [bulkDialog, setBulkDialog] = useState<{
    open: boolean;
    levels: string[];
    confirming: boolean;
  }>({ open: false, levels: [], confirming: false });
  const [campaigns, setCampaigns] = useState<CampaignRecord[]>([]);
  const [historyScope, setHistoryScope] = useState<"all" | "zip">("all");
  const [showCampaignHistory, setShowCampaignHistory] = useState(false);
  const [upsellDialogOpen, setUpsellDialogOpen] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (sharedPlaces) setPlaces(sharedPlaces);
  }, [sharedPlaces]);

  useEffect(() => {
    if (initialCity) setCity(initialCity);
  }, [initialCity]);

  useEffect(() => {
    if (initialZip) setZip(initialZip);
  }, [initialZip]);

  const cities = useMemo(() => {
    const counts = new Map<string, number>();
    for (const place of places) {
      if (initialState && (place.state || "").trim() !== initialState) continue;
      const name = (place.city || "").trim();
      if (!name) continue;
      counts.set(name, (counts.get(name) || 0) + 1);
    }
    return Array.from(counts.entries())
      .map(([name, zipCount]) => ({ name, zipCount }))
      .sort((a, b) => a.name.localeCompare(b.name));
  }, [places, initialState]);

  const zipsForCity = useMemo(() => {
    if (!city) return [];
    return places
      .filter(
        (p) =>
          (p.city || "").trim() === city &&
          (!initialState || (p.state || "").trim() === initialState),
      )
      .sort(
        (a, b) =>
          (b.business_impact_eur || 0) - (a.business_impact_eur || 0) ||
          a.zip_code.localeCompare(b.zip_code, undefined, { numeric: true }),
      );
  }, [places, city, initialState]);

  const place = places.find((p) => p.zip_code === zip && (p.city || "").trim() === city) || null;

  const cityOptions = useMemo(
    () =>
      cities.map(({ name, zipCount }) => ({
        value: name,
        label: name,
        hint: `${zipCount} pincode${zipCount === 1 ? "" : "s"}`,
        searchText: name,
      })),
    [cities],
  );

  const zipOptions = useMemo(
    () =>
      zipsForCity.map((item) => {
        const hints = [
          item.business_impact_eur != null
            ? item.business_impact_eur > 0
              ? `−${formatEuro(item.business_impact_eur)}`
              : formatEuro(item.business_impact_eur)
            : null,
          item.high_risk_customers != null ? `${item.high_risk_customers} high risk` : null,
          item.customers != null ? `n=${item.customers}` : null,
        ].filter(Boolean);
        return {
          value: item.zip_code,
          label: item.zip_code,
          hint: hints.join(" · ") || undefined,
          searchText: `${item.zip_code} ${item.city || ""}`,
        };
      }),
    [zipsForCity],
  );

  async function refreshStatus() {
    try {
      const res = await fetch(`${API_URL}/pipeline/status`);
      const body = await res.json();
      setStatus(
        [
          body.loaded ? "Live" : "Empty",
          body.pincode_count != null ? `${body.pincode_count} zips` : null,
          body.diagnosis_count != null ? `${body.diagnosis_count} diagnoses` : null,
        ]
          .filter(Boolean)
          .join(" · "),
      );
    } catch {
      setStatus("Offline");
    }
  }

  async function loadPlaces() {
    try {
      const res = await fetch(`${API_URL}/pincodes?include_thin=true`);
      const body = await res.json();
      const list: Place[] = body.places ?? [];
      setPlaces(list);
      onPlacesChange?.(list);
      setError(null);

      if (!list.length) {
        setCity("");
        setZip("");
        return;
      }

      setCity((prevCity) => {
        const normalized = (prevCity || initialCity || "").trim();
        const stillValid =
          normalized &&
          list.some(
            (p) =>
              (p.city || "").trim() === normalized &&
              (!initialState || (p.state || "").trim() === initialState),
          );
        if (stillValid) return normalized;
        if (initialCity) return initialCity;

        const counts = new Map<string, number>();
        for (const p of list) {
          if (initialState && (p.state || "").trim() !== initialState) continue;
          const name = (p.city || "").trim();
          if (!name) continue;
          counts.set(name, (counts.get(name) || 0) + 1);
        }
        let best = "";
        let bestCount = -1;
        for (const [name, count] of counts) {
          if (count > bestCount || (count === bestCount && name.localeCompare(best) < 0)) {
            best = name;
            bestCount = count;
          }
        }
        return best;
      });
    } catch {
      setError("Failed to load areas");
    }
  }

  async function loadOffers() {
    try {
      const res = await fetch(`${API_URL}/offers`);
      const body = await res.json();
      setOffers(body.offers ?? []);
    } catch {
      setOffers([]);
    }
  }

  async function loadCampaigns(scopeZip?: string | null) {
    try {
      const params = new URLSearchParams({ limit: "100" });
      if (scopeZip) params.set("zip_code", scopeZip);
      const res = await fetch(`${API_URL}/campaigns?${params}`);
      const body = await res.json();
      setCampaigns(body.campaigns ?? []);
    } catch {
      setCampaigns([]);
    }
  }

  async function loadDetail(selectedZip: string) {
    try {
      const res = await fetch(`${API_URL}/pincode/${encodeURIComponent(selectedZip)}`);
      if (!res.ok) throw new Error("missing");
      const body = (await res.json()) as PincodeDetail;
      setDetail(body);
      const campaigns = body.suggested_campaigns || [];
      const needsAi =
        !campaigns.length || campaigns.every((item) => item.suggested_by !== "ai");
      if (needsAi && !aiRequested.current.has(selectedZip)) {
        aiRequested.current.add(selectedZip);
        void refreshActions(selectedZip);
      }
    } catch {
      setDetail(null);
    }
  }

  async function refreshActions(selectedZip?: string) {
    const target = selectedZip || zip;
    if (!target) return;
    setActionsBusy(true);
    setError(null);
    try {
      const res = await fetch(`${API_URL}/pincode/${encodeURIComponent(target)}/suggest-actions`, {
        method: "POST",
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.detail || res.statusText);
      setDetail(body);
      const customerHits = (body.customers_detail || []).filter(
        (c: CustomerCard) => c.high_risk && (c.suggested_campaign || c.primary_offer_id),
      ).length;
      setMessage(
        customerHits
          ? `AI suggested campaigns ready for ${customerHits} high-risk customer${customerHits === 1 ? "" : "s"}.`
          : "Behaviour upsells & campaign drafts ready.",
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not suggest actions");
    } finally {
      setActionsBusy(false);
    }
  }

  useEffect(() => {
    void refreshStatus();
    void loadPlaces();
    void loadOffers();
    void loadCampaigns();
  }, []);

  useEffect(() => {
    if (historyScope === "zip" && zip) void loadCampaigns(zip);
    else void loadCampaigns();
  }, [historyScope, zip]);

  useEffect(() => {
    setUpsellDialogOpen(false);
  }, [zip]);

  useEffect(() => {
    if (!city) {
      setZip("");
      return;
    }
    const inCity = places
      .filter(
        (p) =>
          (p.city || "").trim() === city &&
          (!initialState || (p.state || "").trim() === initialState),
      )
      .sort((a, b) => (b.business_impact_eur || 0) - (a.business_impact_eur || 0));
    if (!inCity.length) {
      setZip("");
      return;
    }
    setZip((prev) => {
      if (prev && inCity.some((p) => p.zip_code === prev)) return prev;
      if (initialZip && inCity.some((p) => p.zip_code === initialZip)) return initialZip;
      return inCity[0].zip_code;
    });
  }, [city, places, initialState, initialZip]);

  useEffect(() => {
    if (zip) void loadDetail(zip);
    else setDetail(null);
  }, [zip]);

  function onCityChange(next: string) {
    setCity(next.trim());
    setZip("");
    setMessage(null);
  }

  async function runPipeline() {
    setRunning(true);
    setError(null);
    setMessage(null);
    try {
      const res = await fetch(`${API_URL}/pipeline/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: "auto" }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || res.statusText);
      }
      await refreshStatus();
      await loadPlaces();
      await loadOffers();
      if (zip) await loadDetail(zip);
      setMessage("Prediction complete — metrics and customer CLV are ready.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Pipeline failed");
    } finally {
      setRunning(false);
    }
  }

  async function explainCustomer(customer: CustomerCard) {
    if (!zip || !customer.customer_id) return;
    setExplainingId(customer.customer_id);
    setRiskDialog({
      open: true,
      loading: true,
      customerRef: customer.customer_ref,
      customerId: customer.customer_id,
      prediction: customer.churn_prediction,
      probability: customer.churn_probability,
      text: null,
      error: null,
    });
    try {
      const res = await fetch(
        `${API_URL}/pincode/${encodeURIComponent(zip)}/customers/${encodeURIComponent(customer.customer_id)}/explain`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ use_agent: true }),
        },
      );
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.detail || res.statusText);
      if (body.profile) setDetail(body.profile);
      setRiskDialog((prev) => ({
        ...prev,
        loading: false,
        text: body.risk_why || null,
        error: body.risk_why ? null : "Agent returned an empty explanation",
      }));
    } catch (err) {
      setRiskDialog((prev) => ({
        ...prev,
        loading: false,
        text: null,
        error: err instanceof Error ? err.message : "Explain failed",
      }));
    } finally {
      setExplainingId(null);
    }
  }

  function closeRiskDialog() {
    setRiskDialog((prev) => ({ ...prev, open: false }));
  }

  type CampaignOption = {
    offer_id: string;
    name: string;
    campaign_type?: string;
    description?: string;
    channel?: string;
    matched_patterns?: string[];
    suggested_by?: string;
    confidence_score?: number | null;
    confidence_level?: string | null;
    problems: { label: string; detail?: string }[];
    aiSuggested: boolean;
  };

  function problemsFor(customer: CustomerCard, tags: string[] | undefined) {
    const wanted = new Set((tags || []).map((tag) => tag.toLowerCase()));
    if (!wanted.size) return [];
    return (customer.risk_factors || [])
      .filter((factor) => wanted.has(factor.code.toLowerCase()))
      .map((factor) => ({ label: factor.label, detail: factor.detail }));
  }

  function customerAiOptions(customer: CustomerCard): CampaignOption[] {
    const fromOffers = (customer.suggested_offers || [])
      .filter((o) => o.offer_id)
      .map((o) => {
        const catalog = offers.find((item) => item.offer_id === o.offer_id);
        const fromRisk = (o.churn_risk?.factors || [])
          .filter((factor) => factor.label)
          .map((factor) => ({ label: factor.label as string, detail: factor.detail }));
        return {
          offer_id: o.offer_id,
          name: o.offer_name || o.offer_id,
          campaign_type: o.campaign_type,
          description: catalog?.description || o.description || o.suggested_resolution,
          channel: o.channel,
          matched_patterns: o.matched_patterns,
          suggested_by: o.suggested_by,
          confidence_score: o.confidence_score,
          confidence_level: o.confidence_level,
          problems: fromRisk.length
            ? fromRisk
            : problemsFor(customer, o.addresses_patterns || catalog?.addresses_patterns || o.matched_patterns),
          aiSuggested: true,
        };
      });
    if (fromOffers.length) return fromOffers;
    const sc = customer.suggested_campaign;
    if (sc?.offer_id) {
      return [{
        offer_id: sc.offer_id,
        name: sc.name || sc.offer_name || sc.offer_id,
        campaign_type: sc.campaign_type,
        description: sc.objective || sc.suggested_resolution,
        channel: sc.channel || undefined,
        matched_patterns: sc.behaviour_basis,
        suggested_by: sc.suggested_by,
        confidence_score: sc.confidence_score,
        confidence_level: sc.confidence_level,
        problems: problemsFor(customer, sc.behaviour_basis),
        aiSuggested: true,
      }];
    }
    return [];
  }

  function customerCampaignOptions(customer: CustomerCard): {
    ai: CampaignOption[];
    remaining: CampaignOption[];
  } {
    const ai = customerAiOptions(customer);
    const aiIds = new Set(ai.map((o) => o.offer_id));
    const remaining = offers
      .filter((o) => o.offer_id && !aiIds.has(o.offer_id))
      .map((o) => ({
        offer_id: o.offer_id,
        name: o.name || o.offer_id,
        description: o.description,
        channel: o.channel,
        problems: problemsFor(customer, o.addresses_patterns),
        aiSuggested: false,
      }));
    return { ai, remaining };
  }

  function openCampaignDialog(customer: CustomerCard) {
    const { ai, remaining } = customerCampaignOptions(customer);
    const defaultId =
      customer.primary_offer_id ||
      ai[0]?.offer_id ||
      remaining[0]?.offer_id ||
      null;
    setCampaignDialog({
      open: true,
      customer,
      selectedOfferId: defaultId,
    });
  }

  function closeCampaignDialog() {
    setCampaignDialog({ open: false, customer: null, selectedOfferId: null });
  }

  async function triggerCustomerCampaignFromDialog() {
    if (!zip || !campaignDialog.customer || !campaignDialog.selectedOfferId) return;
    const customer = campaignDialog.customer;
    const { ai, remaining } = customerCampaignOptions(customer);
    const chosen =
      [...ai, ...remaining].find((o) => o.offer_id === campaignDialog.selectedOfferId) || null;
    if (!chosen?.offer_id) {
      setError("Select a campaign before triggering");
      return;
    }
    setCampaignBusy(true);
    setError(null);
    setMessage(null);
    try {
      const res = await fetch(`${API_URL}/pincode/${encodeURIComponent(zip)}/campaign`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          all_high_risk: false,
          customer_ids: [customer.customer_id],
          offer_id: chosen.offer_id,
        }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.detail || res.statusText);
      if (body.profile) {
        setDetail((prev) => ({
          ...(body.profile as PincodeDetail),
          upsell_opportunities: prev?.upsell_opportunities || body.profile.upsell_opportunities,
          suggested_campaigns: prev?.suggested_campaigns || body.profile.suggested_campaigns,
        }));
      }
      const record = body.campaign;
      setMessage(
        record
          ? `${chosen.name} · ${record.campaign_id} → ${record.customer_count} customer · ${formatEuro(record.clv_eur)} CLV`
          : "Campaign triggered",
      );
      closeCampaignDialog();
      await loadPlaces();
      await loadCampaigns(historyScope === "zip" ? zip : null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Campaign failed");
    } finally {
      setCampaignBusy(false);
    }
  }

  function openBulkDialog() {
    setBulkDialog({ open: true, levels: ["High"], confirming: false });
  }

  function closeBulkDialog() {
    if (campaignBusy) return;
    setBulkDialog({ open: false, levels: [], confirming: false });
  }

  function toggleBulkLevel(level: string) {
    setBulkDialog((prev) => ({
      ...prev,
      confirming: false,
      levels: prev.levels.includes(level)
        ? prev.levels.filter((item) => item !== level)
        : [...prev.levels, level],
    }));
  }

  async function triggerBulkCampaign() {
    if (!zip || !bulkDialog.levels.length) return;
    setCampaignBusy(true);
    setError(null);
    setMessage(null);
    try {
      const res = await fetch(`${API_URL}/pincode/${encodeURIComponent(zip)}/campaign`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          all_high_risk: false,
          risk_levels: bulkDialog.levels,
        }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.detail || res.statusText);
      if (body.profile) {
        setDetail((prev) => ({
          ...(body.profile as PincodeDetail),
          upsell_opportunities: prev?.upsell_opportunities || body.profile.upsell_opportunities,
          suggested_campaigns: prev?.suggested_campaigns || body.profile.suggested_campaigns,
        }));
      }
      const record = body.campaign as CampaignRecord | undefined;
      setMessage(
        record
          ? `${record.campaign_id} → ${record.customer_count} customer${record.customer_count === 1 ? "" : "s"} (${bulkDialog.levels.join(" + ")} risk), each sent their highest-confidence AI campaign · ${formatEuro(record.clv_eur)} CLV`
          : "Bulk campaign triggered",
      );
      setCampaignBusy(false);
      setBulkDialog({ open: false, levels: [], confirming: false });
      await loadPlaces();
      await loadCampaigns(historyScope === "zip" ? zip : null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Bulk campaign failed");
      setBulkDialog((prev) => ({ ...prev, confirming: false }));
    } finally {
      setCampaignBusy(false);
    }
  }

  const riskHere = detail?.risk_rate ?? detail?.churn_rate ?? place?.risk_rate ?? place?.churn_rate ?? null;
  const riskBase =
    detail?.risk_baseline ?? detail?.churn_baseline ?? place?.risk_baseline ?? place?.churn_baseline ?? null;
  const riskLift = riskHere != null && riskBase != null ? riskHere - riskBase : null;
  const impact =
    detail?.business_impact_eur ?? detail?.at_risk_clv_eur ?? place?.business_impact_eur ?? null;
  const totalClv = detail?.total_clv_eur ?? place?.total_clv_eur ?? null;
  const highRisk =
    detail?.high_risk_customers ?? place?.high_risk_customers ?? null;
  const byContract: ContractChurn[] =
    detail?.churn_by_contract || place?.churn_by_contract || [];
  const customers: CustomerCard[] = detail?.customers_detail || [];
  const upsells: UpsellOpportunity[] = detail?.upsell_opportunities || [];
  const upsellYearly = totalYearlyUpsell(upsells, detail?.upsell_yearly_eur);
  const upsellGain = totalRealisticUpsellGain(upsells, detail?.upsell_potential_gain_eur);
  const upsellClv = detail?.upsell_clv_eur ?? null;
  const domainMetrics: DomainChurnMetric[] = detail?.churn_by_domain || [];
  const offerName = detail?.diagnosis?.offer_name || place?.offer_name;

  return (
    <div className="shell">
      <header className="topbar">
        <div className="logo">
          <span className="logo-mark" aria-hidden />
          Churn <em>Impact</em>
          {initialState ? <span className="logo-state">{initialState}</span> : null}
        </div>
        <div className="top-meta">
          <span className="status">{status}</span>
          {error && <p className="error">{error}</p>}
          {message && !error && <p className="ok-msg">{message}</p>}
          {onBack && (
            <button type="button" className="btn ghost" onClick={onBack}>
              ← Honeycomb
            </button>
          )}
          <button type="button" className="btn ghost" onClick={() => void loadPlaces()}>
            Reload
          </button>
          <button type="button" className="btn" disabled={running} onClick={() => void runPipeline()}>
            {running ? "Running…" : "Run prediction"}
          </button>
        </div>
      </header>

      <section className="filters" aria-label="Area filters">
        <div className="filter-steps" aria-hidden>
          <span className={city ? "step-pill on" : "step-pill"}>1 · City</span>
          <span className="step-arrow">→</span>
          <span className={zip ? "step-pill on" : "step-pill"}>2 · Pincode</span>
        </div>

        <div className="filter-field grow">
          <SearchableSelect
            id="city"
            label="1. City"
            value={city}
            options={cityOptions}
            onChange={onCityChange}
            disabled={!cities.length}
            placeholder="Search city…"
            emptyMessage={cities.length ? "No cities match" : "No cities loaded"}
          />
        </div>

        <div className="filter-field grow">
          <SearchableSelect
            id="zip"
            key={city || "no-city"}
            label={city ? `2. Pincode in ${city}` : "2. Pincode"}
            value={zip}
            options={zipOptions}
            onChange={(next) => {
              setZip(next);
              setMessage(null);
            }}
            disabled={!city || !zipsForCity.length}
            placeholder={city ? "Search pincode…" : "Select a city first"}
            emptyMessage={
              !city ? "Select a city first" : zipsForCity.length ? "No pincodes match" : "No pincodes in this city"
            }
          />
        </div>
      </section>

      <main className="main">
        {!place || !detail ? (
          <div className="empty">
            <div>
              <h2>{cities.length ? "Select city, then pincode" : "No area data yet"}</h2>
              <p>
                {cities.length
                  ? "Open a zip to see euro impact, contract churn, and customer CLV."
                  : "Click Run prediction to process customers and build the impact dashboard."}
              </p>
            </div>
          </div>
        ) : (
          <>
            <div className="page-head">
              <div>
                <h1>
                  {place.city || "Area"} · {place.zip_code}
                </h1>
                <p>
                  {place.state || "California"} · behaviour-led upsell & campaigns
                  {offerName ? ` · focus: ${offerName}` : ""}
                </p>
              </div>
              <div className="page-head-actions">
                <button
                  type="button"
                  className="btn ghost"
                  disabled={actionsBusy}
                  onClick={() => void refreshActions()}
                  title="Refresh per-customer AI campaign matches from Neo4j problems"
                >
                  {actionsBusy ? "Suggesting…" : "Refresh AI suggestions"}
                </button>
              </div>
            </div>

            <div className="kpi-row kpi-row-5">
              <article className="widget accent">
                <div className="widget-head">
                  <h3 className="widget-title">
                    Business Impact <InfoTip text={TIPS.riskImpact} />
                  </h3>
                </div>
                <p className="kpi-value danger">
                  {impact != null && impact > 0 ? `−${formatEuro(impact)}` : formatEuro(impact)}
                </p>
                <p className="kpi-label">
                  {(highRisk ?? 0) > 0 ? "+" : ""}
                  {(highRisk ?? 0).toLocaleString()} high-risk /{" "}
                  {(detail.customers ?? place.customers ?? 0).toLocaleString()} customers · CLV at
                  risk
                </p>
                {riskLift != null && (
                  <p className={`kpi-delta ${riskLift < 0 ? "down" : "up"}`}>
                    Risk {formatShare(riskHere)} ({formatSignedShare(riskLift)} vs state)
                  </p>
                )}
              </article>

              <article className="widget">
                <div className="widget-head">
                  <h3 className="widget-title">
                    Predicted risk <InfoTip text={TIPS.predictedRisk} />
                  </h3>
                </div>
                <p className="kpi-value">{formatShare(riskHere)}</p>
                <p className={`kpi-delta ${riskLift != null && riskLift < 0 ? "down" : "up"}`}>
                  {riskLift != null
                    ? `${formatSignedShare(riskLift)} vs state (${formatShare(riskBase)})`
                    : "Share above risk threshold"}
                </p>
              </article>

              <article className="widget accent gain-kpi">
                <div className="widget-head">
                  <h3 className="widget-title">
                    Yearly upsell <InfoTip text={TIPS.upsell} />
                  </h3>
                  <button
                    type="button"
                    className="btn ghost compact icon-btn"
                    aria-label="Show what we can upsell"
                    title="What can we upsell"
                    onClick={() => setUpsellDialogOpen(true)}
                  >
                    <ChevronRight size={18} strokeWidth={2.5} />
                  </button>
                </div>
                <p className="kpi-value gain">
                  {upsellYearly > 0 ? `+${formatEuro(upsellYearly)}` : formatEuro(0)}
                  <span className="kpi-period">/yr</span>
                </p>
                <p className="kpi-label">
                  {upsellGain > 0 ? `Expected +${formatEuro(upsellGain)}/yr after take-rate` : "Expected gain after take-rate"}
                  {upsellClv != null ? ` · Upsell CLV ${formatEuro(upsellClv)}` : ""}
                </p>
              </article>

              <article className="widget">
                <div className="widget-head">
                  <h3 className="widget-title">
                    Total CLV <InfoTip text={TIPS.totalClv} />
                  </h3>
                </div>
                <p className="kpi-value">{formatEuro(totalClv)}</p>
                <p className="kpi-label">All customers in zip</p>
              </article>

              <article className="widget">
                <div className="widget-head">
                  <h3 className="widget-title">
                    By contract <InfoTip text={TIPS.byContract} />
                  </h3>
                </div>
                <div className="contract-kpis">
                  {byContract.map((item) => {
                    const rate = item.churn_rate;
                    const sign =
                      rate == null ? "" : rate >= 0.65 ? "+" : rate <= 0.35 ? "−" : "±";
                    return (
                      <div className="contract-kpi" key={item.contract_type}>
                        <span>{item.contract_type}</span>
                        <strong className={sign === "+" ? "up" : sign === "−" ? "down" : ""}>
                          {sign ? `${sign} ` : ""}
                          {formatShare(rate)}
                        </strong>
                        <em>
                          {item.high_risk_customers > 0 ? "+" : ""}
                          {item.high_risk_customers}/{item.customers}
                        </em>
                      </div>
                    );
                  })}
                  {!byContract.length && <p className="kpi-label">Re-run prediction to load contract split</p>}
                </div>
              </article>
            </div>

            <article className="widget">
              <div className="widget-head">
                <h3 className="widget-title">
                  Churn × domain metrics <InfoTip text={TIPS.churnDomains} />
                </h3>
                <span className="widget-action">
                  {domainMetrics.length ? `${domainMetrics.length} domains` : "run prediction"}
                </span>
              </div>
              {!domainMetrics.length ? (
                <p className="offer-desc">
                  Domain churn metrics will appear after prediction — Demographics, Location, Population,
                  Services, Status.
                </p>
              ) : (
                <div className="domain-grid">
                  {domainMetrics.map((domain) => (
                    <div className="domain-card" key={domain.domain}>
                      <div className="action-top">
                        <strong>{domain.domain}</strong>
                        <span className="mono">{formatShare(domain.risk_rate)}</span>
                      </div>
                      <p>{domain.headline}</p>
                      <p className="action-meta">
                        score {domain.churn_score_mean != null ? domain.churn_score_mean.toFixed(1) : "—"}
                        {domain.domain_pressure != null
                          ? ` · pressure ${formatSignedShare(domain.domain_pressure)}`
                          : ""}
                      </p>
                      <div className="domain-segments">
                        {(domain.segments || []).slice(0, 4).map((seg) => (
                          <div className="domain-seg" key={`${domain.domain}-${seg.segment}`}>
                            <span>{seg.label}</span>
                            <strong
                              className={
                                (seg.delta_vs_overall || 0) > 0
                                  ? "up"
                                  : (seg.delta_vs_overall || 0) < 0
                                    ? "down"
                                    : ""
                              }
                            >
                              {formatShare(seg.risk_rate)}
                              {seg.delta_vs_overall != null
                                ? ` (${formatSignedShare(seg.delta_vs_overall)})`
                                : ""}
                            </strong>
                          </div>
                        ))}
                        {(domain.value_cuts || []).slice(0, 3).map((seg) => (
                          <div className="domain-seg" key={`${domain.domain}-cut-${seg.segment}`}>
                            <span>{seg.label}</span>
                            <strong>{formatShare(seg.risk_rate)}</strong>
                          </div>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </article>

            <article className="widget">
              <div className="widget-head">
                <h3 className="widget-title">
                  Customers after processing <InfoTip text={TIPS.customers} />
                </h3>
                <div className="history-controls">
                  <span className="widget-action">{customers.length} rows</span>
                  {customers.length > 0 && (
                    <button
                      type="button"
                      className="btn compact"
                      disabled={campaignBusy || !zip}
                      onClick={openBulkDialog}
                    >
                      Bulk trigger
                    </button>
                  )}
                </div>
              </div>

              {!customers.length ? (
                <p className="offer-desc">
                  No per-customer rows yet. Click <strong>Run prediction</strong> to compute CLV, contract
                  type, and churn prediction for every customer in this pincode.
                </p>
              ) : (
                <div className="table-wrap">
                  <table className="table">
                    <thead>
                      <tr>
                        <th>Customer</th>
                        <th>Contract</th>
                        <th>Churn prediction</th>
                        <th>CLV (€)</th>
                        <th>Monthly (€)</th>
                        <th>Risk</th>
                        <th>AI suggested campaign</th>
                        <th>Confidence</th>
                      </tr>
                    </thead>
                    <tbody>
                      {customers.map((customer) => (
                        <tr key={customer.customer_id || customer.customer_ref}>
                          <td className="name mono">{customer.customer_ref}</td>
                          <td>{customer.contract_type}</td>
                          <td>
                            <span className={riskClass(customer.churn_prediction)}>
                              <span className="sign" aria-hidden>
                                {predictionSign(customer.churn_prediction)}
                              </span>{" "}
                              {customer.churn_prediction}
                              <span className="prob">
                                {" "}
                                {formatSignedShare(customer.churn_probability)}
                              </span>
                            </span>
                          </td>
                          <td className="mono">
                            {customer.high_risk ? "+" : ""}
                            {formatEuro(customer.clv_eur)}
                          </td>
                          <td className="mono">{formatEuro(customer.monthly_charge_eur)}</td>
                          <td>
                            {customer.high_risk ? (
                              <button
                                type="button"
                                className="btn ghost compact"
                                disabled={explainingId === customer.customer_id}
                                onClick={() => void explainCustomer(customer)}
                              >
                                {explainingId === customer.customer_id ? "Explaining…" : "Explain risk"}
                              </button>
                            ) : (
                              <span className="mono">—</span>
                            )}
                          </td>
                          <td>
                            {!customer.campaign_eligible && customer.campaign_status !== "triggered" ? (
                              <span className="mono">—</span>
                            ) : (
                              <div className="customer-campaign-cell inline">
                                <button
                                  type="button"
                                  className="btn ghost compact"
                                  disabled={campaignBusy}
                                  onClick={() => openCampaignDialog(customer)}
                                >
                                  AI Suggested Campaigns Only
                                </button>
                                {customer.campaign_status === "triggered" ? (
                                  <span className="campaign-done">Triggered</span>
                                ) : null}
                              </div>
                            )}
                          </td>
                          <td>
                            {customer.suggested_campaign?.confidence_score != null ? (
                              <div className="confidence-cell">
                                <ConfidenceBadge
                                  score={customer.suggested_campaign.confidence_score}
                                  level={customer.suggested_campaign.confidence_level}
                                />
                                <span className="action-meta">
                                  {customer.suggested_campaign.offer_name ||
                                    customer.suggested_campaign.name ||
                                    customer.suggested_campaign.offer_id}
                                </span>
                              </div>
                            ) : (
                              <span className="mono">—</span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              <div className="history-controls" style={{ marginTop: 12 }}>
                <button
                  type="button"
                  className={`btn ghost compact ${showCampaignHistory ? "active-scope" : ""}`}
                  onClick={() => setShowCampaignHistory((open) => !open)}
                >
                  {showCampaignHistory ? "Hide campaign target history" : "Campaign target history"}
                </button>
                {showCampaignHistory && (
                  <span className="widget-action">{campaigns.length} saved in SQLite</span>
                )}
              </div>

              {showCampaignHistory && (
                <div style={{ marginTop: 12 }}>
                  <div className="history-controls" style={{ marginBottom: 8 }}>
                    <button
                      type="button"
                      className={`btn ghost compact ${historyScope === "all" ? "active-scope" : ""}`}
                      onClick={() => setHistoryScope("all")}
                    >
                      All zips
                    </button>
                    <button
                      type="button"
                      className={`btn ghost compact ${historyScope === "zip" ? "active-scope" : ""}`}
                      onClick={() => setHistoryScope("zip")}
                      disabled={!zip}
                    >
                      This zip
                    </button>
                  </div>
                  {!campaigns.length ? (
                    <p className="offer-desc">
                      No campaigns triggered yet. Pick an AI suggested campaign on a customer row and
                      click <strong>Trigger</strong> — history is stored in local SQLite (
                      <code>artifacts/campaigns.db</code>).
                    </p>
                  ) : (
                    <div className="table-wrap">
                      <table className="table">
                        <thead>
                          <tr>
                            <th>When</th>
                            <th>Campaign</th>
                            <th>City / Zip</th>
                            <th>Customers</th>
                            <th>CLV targeted</th>
                            <th>Offer</th>
                            <th>Refs</th>
                          </tr>
                        </thead>
                        <tbody>
                          {campaigns.map((item) => (
                            <tr key={item.campaign_id}>
                              <td className="mono">{formatWhen(item.created_at)}</td>
                              <td className="name mono">{item.campaign_id}</td>
                              <td>
                                {item.city || "—"} · {item.zip_code}
                              </td>
                              <td className="mono">+{item.customer_count}</td>
                              <td className="mono danger-text">−{formatEuro(item.clv_eur)}</td>
                              <td className="mono">{item.offer_id || "—"}</td>
                              <td className="mono refs">
                                {(item.customer_refs || []).slice(0, 4).join(", ") || "—"}
                                {(item.customer_refs || []).length > 4
                                  ? ` +${(item.customer_refs || []).length - 4}`
                                  : ""}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              )}
            </article>

            {offers.length > 0 && offerName && (
              <p className="foot-note">
                Campaign offer for this zip: <strong>{offerName}</strong>
                {detail?.diagnosis?.offer_rationale ? ` — ${detail.diagnosis.offer_rationale}` : ""}
              </p>
            )}
          </>
        )}

        {campaignDialog.open && campaignDialog.customer && (() => {
          const customer = campaignDialog.customer!;
          const { ai, remaining } = customerCampaignOptions(customer);
          const all = [...ai, ...remaining];
          const selected =
            all.find((o) => o.offer_id === campaignDialog.selectedOfferId) || all[0] || null;
          const alreadyTriggered = customer.campaign_status === "triggered";
          const concreteRisks = (customer.risk_factors || []).filter(
            (factor) => factor.code !== "high_churn_score" && factor.code !== "high_risk",
          );
          const nothingMissing = !(customer.services?.missing || []).length;
          const scoreOnly = nothingMissing && concreteRisks.length === 0;
          const scoreLabel =
            customer.churn_score != null
              ? `${customer.churn_score}/100`
              : formatShare(customer.churn_probability);

          function renderCampaignCard(opt: CampaignOption) {
            const isSelected = selected?.offer_id === opt.offer_id;
            return (
              <button
                key={`${opt.aiSuggested ? "ai" : "rest"}-${opt.offer_id}`}
                type="button"
                className={`campaign-pick-card ${isSelected ? "selected" : ""}`}
                onClick={() =>
                  setCampaignDialog((prev) => ({
                    ...prev,
                    selectedOfferId: opt.offer_id,
                  }))
                }
              >
                <div className="campaign-pick-top">
                  <strong>{opt.name}</strong>
                  <span className="campaign-pick-badges">
                    <ConfidenceBadge score={opt.confidence_score} level={opt.confidence_level} />
                    <span className="campaign-pick-badge">
                      {opt.aiSuggested ? "AI" : "Menu"}
                      {opt.campaign_type ? ` · ${opt.campaign_type}` : ""}
                    </span>
                  </span>
                </div>
                <dl className="campaign-facts">
                  <dt>Problem</dt>
                  <dd>
                    {scoreOnly &&
                    (!opt.problems.length ||
                      opt.problems.every((problem) =>
                        /predictive risk|high risk/i.test(problem.label),
                      )) ? (
                      <span>
                        No product is missing. This is a precaution because the churn model
                        scores them {scoreLabel}, not because a service is absent.
                      </span>
                    ) : opt.problems.length ? (
                      <ul>
                        {opt.problems.slice(0, 3).map((problem) => (
                          <li key={problem.label}>
                            <strong>{problem.label}</strong>
                            {problem.detail ? <span> — {problem.detail}</span> : null}
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <span className="muted">No matching risk found for this customer</span>
                    )}
                  </dd>
                  <dt>Solution</dt>
                  <dd>{opt.description || "—"}</dd>
                </dl>
                <p className="action-meta">
                  {opt.offer_id}
                  {opt.channel ? ` · ${opt.channel} channel` : ""}
                </p>
              </button>
            );
          }

          return (
            <div className="dialog-backdrop" role="presentation" onClick={closeCampaignDialog}>
              <div
                className="dialog dialog-campaign"
                role="dialog"
                aria-modal="true"
                aria-labelledby="campaign-dialog-title"
                onClick={(event) => event.stopPropagation()}
              >
                <div className="dialog-head">
                  <div>
                    <h2 id="campaign-dialog-title">AI suggested campaign</h2>
                    <p>
                      Customer {customer.customer_ref} · {customer.churn_prediction} risk ·{" "}
                      {formatEuro(customer.clv_eur)} CLV
                    </p>
                  </div>
                  <button
                    type="button"
                    className="btn ghost compact"
                    onClick={closeCampaignDialog}
                  >
                    Close
                  </button>
                </div>
                <div className="dialog-body campaign-dialog-body">
                  <div className="campaign-dialog-scroll">
                    <section className="campaign-dialog-section">
                      <h3>AI suggested campaign{ai.length === 1 ? "" : "s"}</h3>
                      {!ai.length ? (
                        <p className="offer-desc">No AI matches yet for this customer.</p>
                      ) : (
                        <div className="campaign-pick-list">{ai.map(renderCampaignCard)}</div>
                      )}
                    </section>
                    <section className="campaign-dialog-section">
                      <h3>All remaining campaigns</h3>
                      {!remaining.length ? (
                        <p className="offer-desc">No other offers in the menu.</p>
                      ) : (
                        <div className="campaign-pick-list">{remaining.map(renderCampaignCard)}</div>
                      )}
                    </section>
                  </div>
                  <div className="campaign-dialog-footer">
                    <div className="campaign-dialog-selected">
                      <span className="campaign-select-label">Selected</span>
                      <strong>{selected?.name || "None"}</strong>
                      {scoreOnly ? (
                        <p className="offer-desc">Precaution for a high model score. No product gap.</p>
                      ) : selected?.problems.length ? (
                        <p className="offer-desc">
                          Solves: {selected.problems.map((problem) => problem.label).join(", ")}
                        </p>
                      ) : null}
                    </div>
                    {alreadyTriggered ? (
                      <span className="campaign-done">Already triggered</span>
                    ) : (
                      <button
                        type="button"
                        className="btn"
                        disabled={campaignBusy || !selected?.offer_id}
                        onClick={() => void triggerCustomerCampaignFromDialog()}
                      >
                        {campaignBusy ? "Triggering…" : "Trigger campaign for customer"}
                      </button>
                    )}
                  </div>
                </div>
              </div>
            </div>
          );
        })()}

        {bulkDialog.open && (() => {
          const tiers = RISK_LEVELS.map((level) => {
            const inTier = customers.filter((c) => c.churn_prediction === level);
            const pending = inTier.filter((c) => c.campaign_status !== "triggered");
            return {
              level,
              total: inTier.length,
              pending: pending.length,
              clv: pending.reduce((sum, c) => sum + (c.clv_eur || 0), 0),
            };
          }).filter((tier) => tier.total > 0);
          const selectedTiers = tiers.filter((tier) => bulkDialog.levels.includes(tier.level));
          const targetCount = selectedTiers.reduce((sum, tier) => sum + tier.pending, 0);
          const targetClv = selectedTiers.reduce((sum, tier) => sum + tier.clv, 0);

          return (
            <div className="dialog-backdrop" role="presentation" onClick={closeBulkDialog}>
              <div
                className="dialog dialog-bulk"
                role="dialog"
                aria-modal="true"
                aria-labelledby="bulk-dialog-title"
                onClick={(event) => event.stopPropagation()}
              >
                <div className="dialog-head">
                  <div>
                    <h2 id="bulk-dialog-title">Bulk trigger campaign</h2>
                    <p>
                      {place?.city || detail?.city || "This zip"} · {zip} · pick the churn risk levels to target
                    </p>
                  </div>
                  <button
                    type="button"
                    className="btn ghost compact"
                    disabled={campaignBusy}
                    onClick={closeBulkDialog}
                  >
                    Close
                  </button>
                </div>
                <div className="dialog-body bulk-dialog-body">
                  <div className="bulk-tier-list">
                    {tiers.map((tier) => {
                      const checked = bulkDialog.levels.includes(tier.level);
                      return (
                        <label
                          key={tier.level}
                          className={`bulk-tier ${checked ? "selected" : ""} ${tier.pending === 0 ? "empty" : ""}`}
                        >
                          <input
                            type="checkbox"
                            checked={checked}
                            disabled={campaignBusy || tier.pending === 0}
                            onChange={() => toggleBulkLevel(tier.level)}
                          />
                          <span className={riskClass(tier.level)}>{tier.level} risk</span>
                          <span className="bulk-tier-meta">
                            {tier.pending} to target
                            {tier.total !== tier.pending ? ` · ${tier.total - tier.pending} already triggered` : ""}
                            {tier.pending ? ` · ${formatEuro(tier.clv)} CLV` : ""}
                          </span>
                        </label>
                      );
                    })}
                  </div>

                  <p className="bulk-summary">
                    {targetCount
                      ? `${targetCount} customer${targetCount === 1 ? "" : "s"} selected · ${formatEuro(targetClv)} CLV`
                      : "Select at least one risk level with customers left to target."}
                  </p>

                  {bulkDialog.confirming ? (
                    <div className="bulk-warning" role="alert">
                      <strong>Heads up</strong>
                      <p>
                        This will trigger the <strong>highest-confidence AI selected campaign</strong> for each of the{" "}
                        {targetCount} selected customer{targetCount === 1 ? "" : "s"}. Every customer gets their own
                        best-fit campaign, so different customers may receive different offers.
                      </p>
                      <div className="bulk-warning-actions">
                        <button
                          type="button"
                          className="btn ghost compact"
                          disabled={campaignBusy}
                          onClick={() => setBulkDialog((prev) => ({ ...prev, confirming: false }))}
                        >
                          Cancel
                        </button>
                        <button
                          type="button"
                          className="btn compact"
                          disabled={campaignBusy}
                          onClick={() => void triggerBulkCampaign()}
                        >
                          {campaignBusy ? "Triggering…" : "Okay, trigger"}
                        </button>
                      </div>
                    </div>
                  ) : (
                    <div className="bulk-footer">
                      <button
                        type="button"
                        className="btn"
                        disabled={campaignBusy || targetCount === 0}
                        onClick={() => setBulkDialog((prev) => ({ ...prev, confirming: true }))}
                      >
                        Send trigger campaign
                      </button>
                    </div>
                  )}
                </div>
              </div>
            </div>
          );
        })()}

        {riskDialog.open && (
          <div className="dialog-backdrop" role="presentation" onClick={closeRiskDialog}>
            <div
              className="dialog"
              role="dialog"
              aria-modal="true"
              aria-labelledby="risk-dialog-title"
              onClick={(event) => event.stopPropagation()}
            >
              <div className="dialog-head">
                <div>
                  <h2 id="risk-dialog-title">Why this customer may churn</h2>
                  <p>
                    {riskDialog.customerRef}
                    {riskDialog.prediction
                      ? ` · ${riskDialog.prediction} risk (${formatSignedShare(riskDialog.probability)})`
                      : ""}
                  </p>
                </div>
                <button type="button" className="btn ghost compact" onClick={closeRiskDialog}>
                  Close
                </button>
              </div>
              <div className="dialog-body">
                {riskDialog.loading && (
                  <p className="offer-desc">Asking the agent…</p>
                )}
                {!riskDialog.loading && riskDialog.error && (
                  <p className="error">{riskDialog.error}</p>
                )}
                {!riskDialog.loading && riskDialog.text && (
                  <p className="dialog-text">{riskDialog.text}</p>
                )}
              </div>
            </div>
          </div>
        )}

        {upsellDialogOpen && (
          <div
            className="dialog-backdrop"
            role="presentation"
            onClick={() => setUpsellDialogOpen(false)}
          >
            <div
              className="dialog dialog-wide"
              role="dialog"
              aria-modal="true"
              aria-labelledby="upsell-dialog-title"
              onClick={(event) => event.stopPropagation()}
            >
              <div className="dialog-head">
                <div>
                  <h2 id="upsell-dialog-title">Yearly upsell plays</h2>
                  <p>
                    {upsellYearly > 0 ? `+${formatEuro(upsellYearly)}/yr` : formatEuro(0)} yearly upsell
                    {upsellGain > 0 ? ` · expected +${formatEuro(upsellGain)}/yr` : ""}
                    {upsellClv != null ? ` · CLV ${formatEuro(upsellClv)}` : ""} ·{" "}
                    {upsells.length} behaviour play{upsells.length === 1 ? "" : "s"}
                  </p>
                </div>
                <button
                  type="button"
                  className="btn ghost compact"
                  onClick={() => setUpsellDialogOpen(false)}
                >
                  Close
                </button>
              </div>
              <div className="dialog-body">
                {!upsells.length ? (
                  <p className="offer-desc">
                    {actionsBusy
                      ? "Reading behaviour signals…"
                      : "No strong upsell gaps in this zip yet. Refresh AI suggestions after prediction."}
                  </p>
                ) : (
                  <div className="action-list action-list-grid">
                    {upsells.map((item) => {
                      const yearly = yearlyUpsellAmount(item);
                      const gain = realisticUpsellGain(item);
                      const perCustomer =
                        item.yearly_uplift_eur ??
                        (item.customers > 0 ? yearly / item.customers : 0);
                      return (
                        <div className="action-card" key={item.signal}>
                          <div className="action-top">
                            <strong>{item.title}</strong>
                            <span className="mono gain-text">
                              {yearly > 0 ? `+${formatEuro(yearly)}/yr` : formatEuro(0)}
                            </span>
                          </div>
                          <p className="upsell-why">{item.evidence?.[0] || item.reason}</p>
                          <div className="upsell-stats">
                            <div>
                              <span>Customers</span>
                              <strong>{item.customers}</strong>
                            </div>
                            <div>
                              <span>Per customer</span>
                              <strong>{formatEuro(perCustomer)}/yr</strong>
                            </div>
                            <div>
                              <span>Expected</span>
                              <strong className="gain-text">
                                {gain > 0 ? `+${formatEuro(gain)}/yr` : "—"}
                              </strong>
                            </div>
                          </div>
                          <p className="upsell-offer">
                            <span>Offer</span> {item.offer_name || item.product}
                          </p>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

      </main>
    </div>
  );
}
