export type Place = {
  zip_code: string;
  city?: string | null;
  state?: string | null;
  problem: string;
  city_value?: number | null;
  baseline_value?: number | null;
  customers?: number | null;
  risk_rate?: number | null;
  risk_baseline?: number | null;
  risk_score_mean?: number | null;
  /** @deprecated predictive risk share; prefer risk_rate */
  churn_rate?: number | null;
  churn_baseline?: number | null;
  thin_sample?: boolean;
  gap_score?: number;
  unit?: "share" | "number" | string;
  offer_id?: string | null;
  offer_name?: string | null;
  confidence?: string | null;
  business_impact_eur?: number | null;
  at_risk_clv_eur?: number | null;
  total_clv_eur?: number | null;
  upsell_yearly_eur?: number | null;
  upsell_potential_gain_eur?: number | null;
  upsell_clv_eur?: number | null;
  high_risk_customers?: number | null;
  churn_by_contract?: ContractChurn[];
  currency?: string;
};

export type ContractChurn = {
  contract_type: string;
  customers: number;
  high_risk_customers: number;
  churn_rate: number | null;
  at_risk_clv_eur: number;
  total_clv_eur: number;
};

export type RiskFactor = {
  code: string;
  label: string;
  detail: string;
  weight?: number;
};

export type SuggestedCustomerOffer = {
  offer_id: string;
  offer_name?: string;
  description?: string;
  channel?: string;
  priority?: number;
  match_score?: number;
  rank?: number;
  matched_patterns?: string[];
  suggested_resolution?: string;
  suggested_by?: string;
  campaign_type?: string;
  confidence_score?: number | null;
  confidence_level?: "high" | "medium" | "low" | string | null;
  confidence_reasons?: string[];
  why?: string;
  addresses_patterns?: string[];
  churn_risk?: {
    churn_score?: number | null;
    factors?: { code?: string; label?: string; detail?: string }[];
  };
};

export type CustomerServices = {
  active?: { name: string; detail?: string | null }[];
  missing?: string[];
  contract?: string | null;
  internet_type?: string | null;
};

export type SuggestedCustomerCampaign = {
  offer_id?: string | null;
  offer_name?: string | null;
  name?: string | null;
  campaign_type?: string;
  channel?: string | null;
  objective?: string;
  behaviour_basis?: string[];
  priority?: number;
  match_score?: number;
  suggested_by?: string;
  suggested_resolution?: string;
  confidence_score?: number | null;
  confidence_level?: "high" | "medium" | "low" | string | null;
  confidence_reasons?: string[];
  why?: string;
};

export type CustomerCard = {
  customer_id: string;
  customer_ref: string;
  contract_type: string;
  churn_prediction: "High" | "Medium" | "Low" | string;
  churn_probability: number;
  churn_score?: number | null;
  services?: CustomerServices;
  clv_eur: number;
  monthly_charge_eur: number;
  tenure_months?: number | null;
  satisfaction_score?: number | null;
  high_risk: boolean;
  campaign_eligible: boolean;
  campaign_status?: string;
  campaign_id?: string;
  risk_why?: string | null;
  risk_factors?: RiskFactor[];
  risk_why_source?: string | null;
  primary_offer_id?: string | null;
  suggested_offers?: SuggestedCustomerOffer[];
  suggested_campaign?: SuggestedCustomerCampaign | null;
};

export type Offer = {
  offer_id: string;
  name: string;
  description?: string;
  addresses_patterns?: string[];
  channel?: string;
  priority?: number;
};

export type UpsellOpportunity = {
  signal: string;
  title: string;
  product: string;
  reason: string;
  customers: number;
  addressable_clv_eur: number;
  /** Yearly ARPU uplift (€/year) if one customer takes the attach. */
  yearly_uplift_eur?: number;
  /** Gross yearly upsell for this play: customers × yearly_uplift_eur. */
  yearly_upsell_eur?: number;
  /** Realistic expected gain (€/year) after margin × ~20% take-rate. */
  potential_gain_eur?: number;
  potential_gain_period?: "year" | "month";
  /** @deprecated use yearly_uplift_eur */
  monthly_uplift_eur?: number;
  offer_id?: string;
  offer_name?: string;
  why?: string;
  evidence?: string[];
};

export type DomainChurnSegment = {
  segment: string;
  label: string;
  field?: string;
  customers: number;
  risk_rate?: number | null;
  churn_score_mean?: number | null;
  satisfaction_mean?: number | null;
  delta_vs_overall?: number | null;
};

export type DomainChurnMetric = {
  domain: string;
  source_file?: string;
  fields?: string[];
  customers?: number;
  risk_rate?: number | null;
  churn_score_mean?: number | null;
  satisfaction_mean?: number | null;
  domain_pressure?: number;
  segments?: DomainChurnSegment[];
  value_cuts?: DomainChurnSegment[];
  headline?: string;
};

export type SuggestedCampaign = {
  campaign_type: string;
  name: string;
  objective?: string;
  audience?: string;
  behaviour_basis?: string[];
  offer_id?: string | null;
  offer_name?: string | null;
  channel?: string | null;
  priority?: number;
  suggested_by?: string;
};

export type PincodeDetail = {
  zip_code: string;
  city?: string | null;
  state?: string | null;
  customers?: number | null;
  population?: number | null;
  risk_rate?: number | null;
  risk_baseline?: number | null;
  risk_score_mean?: number | null;
  churn_rate?: number | null;
  churn_baseline?: number | null;
  thin_sample?: boolean;
  gap_score?: number;
  business_impact_eur?: number | null;
  at_risk_clv_eur?: number | null;
  total_clv_eur?: number | null;
  expected_loss_eur?: number | null;
  high_risk_customers?: number | null;
  churn_by_contract?: ContractChurn[];
  customers_detail?: CustomerCard[];
  upsell_opportunities?: UpsellOpportunity[];
  /** Gross yearly upsell (€/year): sum of customers × yearly ARPU uplift. */
  upsell_yearly_eur?: number | null;
  /** Expected €/year after margin × take-rate (conservative). */
  upsell_potential_gain_eur?: number | null;
  upsell_potential_gain_period?: "year" | "month" | null;
  /** Unique CLV of behaviour-eligible upsell customers. */
  upsell_clv_eur?: number | null;
  suggested_campaigns?: SuggestedCampaign[];
  churn_by_domain?: DomainChurnMetric[];
  currency?: string;
  diagnosis?: {
    problem?: string;
    confidence?: string;
    offer_id?: string | null;
    offer_name?: string | null;
    offer_rationale?: string;
    pattern_id?: string | null;
  } | null;
  offer?: Offer | null;
};

export type CampaignRecord = {
  campaign_id: string;
  zip_code: string;
  city?: string | null;
  offer_id?: string | null;
  customer_count: number;
  clv_eur: number;
  customer_refs?: string[];
  created_at?: string;
  selection?: "explicit" | "highest_confidence" | string;
  risk_levels?: string[];
  assignments?: CampaignAssignment[];
};

export type CampaignAssignment = {
  customer_id?: string;
  customer_ref?: string;
  offer_id?: string | null;
  offer_name?: string | null;
  confidence_score?: number | null;
  confidence_level?: string | null;
};

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export function formatShare(value: number | null | undefined) {
  if (value == null || Number.isNaN(value)) return "—";
  return `${Math.round(value * 100)}%`;
}

/** Explicit + / − prefix so lifts and drops read clearly. */
export function formatSignedShare(value: number | null | undefined) {
  if (value == null || Number.isNaN(value)) return "—";
  const pct = Math.round(value * 100);
  if (pct > 0) return `+${pct}%`;
  if (pct < 0) return `−${Math.abs(pct)}%`;
  return "0%";
}

export function formatEuro(value: number | null | undefined) {
  if (value == null || Number.isNaN(value)) return "—";
  return new Intl.NumberFormat("en-IE", {
    style: "currency",
    currency: "EUR",
    maximumFractionDigits: 0,
  }).format(value);
}

/** Fallback yearly ARPU uplift (€/year) when artifacts omit yearly_uplift_eur. */
const UPSELL_YEARLY_UPLIFT: Record<string, number> = {
  phone_only_no_internet: 360, // ~€30/mo entry DE home broadband
  heavy_usage_no_unlimited: 72, // ~€6/mo unlimited step-up (not full plan)
  no_security_addon: 48, // ~€4/mo Telekom Sicherheitspaket M
  no_tech_support: 72, // ~€6/mo care/support share
  dependents: 120, // ~€10/mo extra line / Kids PlusCard
};

/** Gross yearly upsell for one behaviour play (€/year). */
export function yearlyUpsellAmount(item: UpsellOpportunity): number {
  if (item.yearly_upsell_eur != null && !Number.isNaN(item.yearly_upsell_eur)) {
    return Math.max(0, item.yearly_upsell_eur);
  }
  const yearly =
    item.yearly_uplift_eur ??
    (item.monthly_uplift_eur != null ? item.monthly_uplift_eur * 12 : undefined) ??
    UPSELL_YEARLY_UPLIFT[item.signal] ??
    96;
  return Math.max(0, Math.round(item.customers * yearly));
}

/** Expected €/year after take-rate (conservative). */
export function realisticUpsellGain(item: UpsellOpportunity): number {
  if (item.potential_gain_eur != null && !Number.isNaN(item.potential_gain_eur)) {
    return Math.max(0, item.potential_gain_eur);
  }
  const yearly =
    item.yearly_uplift_eur ??
    (item.monthly_uplift_eur != null ? item.monthly_uplift_eur * 12 : undefined) ??
    UPSELL_YEARLY_UPLIFT[item.signal] ??
    96;
  const conversion = 0.2;
  const margin = 0.6;
  const raw = item.customers * yearly * margin * conversion;
  const cap = (item.addressable_clv_eur || 0) * 0.15;
  return Math.round(cap > 0 ? Math.min(raw, cap) : raw);
}

/** Gross yearly upsell for the zip (€/year) — primary UI KPI. */
export function totalYearlyUpsell(
  upsells: UpsellOpportunity[],
  profileTotal?: number | null,
): number {
  if (profileTotal != null && !Number.isNaN(profileTotal) && profileTotal >= 0) {
    return profileTotal;
  }
  return upsells.reduce((sum, item) => sum + yearlyUpsellAmount(item), 0);
}

export function totalRealisticUpsellGain(
  upsells: UpsellOpportunity[],
  profileTotal?: number | null,
): number {
  if (profileTotal != null && !Number.isNaN(profileTotal) && profileTotal >= 0) {
    return profileTotal;
  }
  return upsells.reduce((sum, item) => sum + realisticUpsellGain(item), 0);
}

export function formatSignedEuro(value: number | null | undefined) {
  if (value == null || Number.isNaN(value)) return "—";
  const abs = formatEuro(Math.abs(value));
  if (value > 0) return `+${abs}`;
  if (value < 0) return `−${abs}`;
  return abs;
}

export function predictionSign(prediction: string) {
  if (prediction === "High") return "+";
  if (prediction === "Low") return "−";
  return "±";
}

export function formatValue(value: number | null | undefined, unit: string = "share") {
  if (value == null || Number.isNaN(value)) return "—";
  if (unit === "share") return formatShare(value);
  if (unit === "eur") return formatEuro(value);
  if (Math.abs(value) >= 100) return value.toLocaleString("en-US", { maximumFractionDigits: 0 });
  return value.toLocaleString("en-US", { maximumFractionDigits: 1 });
}

export function humanMetric(name: string) {
  return name
    .replace(/_/g, " ")
    .replace(/:/g, " · ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}
