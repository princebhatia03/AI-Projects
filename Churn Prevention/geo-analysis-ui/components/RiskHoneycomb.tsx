"use client";

import { useEffect, useMemo, useState } from "react";
import { GridGenerator, HexGrid, Hexagon, Layout, Text } from "react-hexgrid";
import { Place, formatEuro, formatShare } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { SearchableSelect } from "@/components/SearchableSelect";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ZoomPanViewport } from "@/components/ZoomPanViewport";

export type HoneycombCity = {
  state: string;
  city: string;
  zipCount: number;
  customers: number;
  highRisk: number;
  avgRisk: number;
  businessImpactEur: number;
};

type Props = {
  places: Place[];
  status: string;
  running: boolean;
  error: string | null;
  onReload: () => void;
  onRunPipeline: () => void;
  onSelectCity: (city: string, state: string, zip?: string) => void;
};

const COLS_MAX = 6;
/** Fewest cities that still form a multi-row honeycomb (not a single diagonal). */
const COMB_MIN = 3;
const HEX_SIZE = { x: 11, y: 11 };
const HEX_SPACING = 1.14;

/**
 * Pick column count so small sets still read as a comb.
 * Below COMB_MIN, keep a short line; from COMB_MIN up, aim for ~√n cols
 * (capped at COLS_MAX) and force at least 2 rows when possible.
 */
function layoutCols(count: number): number {
  if (count <= 0) return 1;
  if (count < COMB_MIN) return count;
  let cols = Math.min(COLS_MAX, Math.max(2, Math.ceil(Math.sqrt(count))));
  // One full row still looks like a diagonal with flat-top hexes — shrink cols.
  if (cols >= count) {
    cols = Math.ceil(count / 2);
  }
  return Math.max(2, cols);
}

/** Flat-top axial → pixel (same math as react-hexgrid HexUtils.hexToPixel). */
function hexCenter(q: number, r: number) {
  const x = 1.5 * q * HEX_SIZE.x * HEX_SPACING;
  const y = (Math.sqrt(3) / 2 * q + Math.sqrt(3) * r) * HEX_SIZE.y * HEX_SPACING;
  return { x, y };
}

function riskTone(avgRisk: number) {
  if (avgRisk >= 0.55) {
    return { fill: "#c53050", label: "High" as const, badge: "high" as const, className: "risk-high" };
  }
  if (avgRisk >= 0.4) {
    return {
      fill: "#b7791f",
      label: "Medium" as const,
      badge: "medium" as const,
      className: "risk-medium",
    };
  }
  return { fill: "#1f8a5b", label: "Low" as const, badge: "low" as const, className: "risk-low" };
}

function buildCities(places: Place[]): HoneycombCity[] {
  const map = new Map<string, HoneycombCity>();
  for (const place of places) {
    const city = (place.city || "").trim();
    const state = (place.state || "Unknown").trim() || "Unknown";
    if (!city) continue;
    const key = `${state}::${city}`;
    const risk = place.risk_rate ?? place.churn_rate ?? 0;
    const existing = map.get(key);
    if (!existing) {
      map.set(key, {
        state,
        city,
        zipCount: 1,
        customers: place.customers || 0,
        highRisk: place.high_risk_customers || 0,
        avgRisk: risk || 0,
        businessImpactEur: place.business_impact_eur || 0,
      });
      continue;
    }
    const nextZip = existing.zipCount + 1;
    existing.avgRisk = (existing.avgRisk * existing.zipCount + (risk || 0)) / nextZip;
    existing.zipCount = nextZip;
    existing.customers += place.customers || 0;
    existing.highRisk += place.high_risk_customers || 0;
    existing.businessImpactEur += place.business_impact_eur || 0;
  }
  return Array.from(map.values()).sort(
    (a, b) =>
      b.businessImpactEur - a.businessImpactEur ||
      b.customers - a.customers ||
      b.avgRisk - a.avgRisk ||
      a.city.localeCompare(b.city),
  );
}

export function RiskHoneycomb({
  places,
  status,
  running,
  error,
  onReload,
  onRunPipeline,
  onSelectCity,
}: Props) {
  const [query, setQuery] = useState("");
  const [stateFilter, setStateFilter] = useState<string>("");
  const [pickedZip, setPickedZip] = useState("");
  const [hovered, setHovered] = useState<HoneycombCity | null>(null);
  const [selected, setSelected] = useState<HoneycombCity | null>(null);
  const preview = selected ?? hovered;

  const cities = useMemo(() => buildCities(places), [places]);
  const states = useMemo(() => {
    const set = new Set(cities.map((c) => c.state));
    return Array.from(set).sort((a, b) => a.localeCompare(b));
  }, [cities]);

  const activeState = stateFilter || states[0] || "";

  useEffect(() => {
    if (!states.length) {
      setStateFilter("");
      return;
    }
    if (!stateFilter || !states.includes(stateFilter)) {
      setStateFilter(states[0]);
    }
  }, [states, stateFilter]);

  useEffect(() => {
    setSelected(null);
    setHovered(null);
    setPickedZip("");
    setQuery("");
  }, [activeState]);

  const citiesInState = useMemo(
    () => cities.filter((c) => c.state === activeState),
    [cities, activeState],
  );

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return citiesInState.filter((c) => !q || c.city.toLowerCase().includes(q));
  }, [citiesInState, query]);

  const stateSummary = useMemo(() => {
    if (!citiesInState.length) return null;
    const customers = citiesInState.reduce((s, c) => s + c.customers, 0);
    const highRisk = citiesInState.reduce((s, c) => s + c.highRisk, 0);
    const impact = citiesInState.reduce((s, c) => s + c.businessImpactEur, 0);
    const zipCount = citiesInState.reduce((s, c) => s + c.zipCount, 0);
    const avgRisk =
      citiesInState.reduce((s, c) => s + c.avgRisk * Math.max(c.zipCount, 1), 0) /
      citiesInState.reduce((s, c) => s + Math.max(c.zipCount, 1), 0);
    return { customers, highRisk, impact, avgRisk, cityCount: citiesInState.length, zipCount };
  }, [citiesInState]);

  const stateOptions = useMemo(
    () =>
      states.map((state) => {
        const inState = cities.filter((c) => c.state === state);
        const zips = inState.reduce((s, c) => s + c.zipCount, 0);
        return {
          value: state,
          label: state,
          hint: `${inState.length} cities · ${zips} pincodes`,
          searchText: state,
        };
      }),
    [states, cities],
  );

  const zipsForCity = useMemo(() => {
    if (!selected || !activeState) return [];
    return places
      .filter(
        (p) =>
          (p.city || "").trim() === selected.city &&
          (p.state || "").trim() === activeState,
      )
      .sort(
        (a, b) =>
          (b.business_impact_eur || 0) - (a.business_impact_eur || 0) ||
          a.zip_code.localeCompare(b.zip_code, undefined, { numeric: true }),
      );
  }, [places, selected, activeState]);

  const zipOptions = useMemo(
    () =>
      zipsForCity.map((item) => {
        const risk = item.risk_rate ?? item.churn_rate;
        const hints = [
          risk != null ? formatShare(risk) : null,
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

  useEffect(() => {
    if (!selected) {
      setPickedZip("");
      return;
    }
    if (!zipsForCity.length) {
      setPickedZip("");
      return;
    }
    setPickedZip((prev) =>
      zipsForCity.some((p) => p.zip_code === prev) ? prev : zipsForCity[0].zip_code,
    );
  }, [selected, zipsForCity]);

  function pinCity(city: HoneycombCity) {
    setSelected(city);
    setHovered(city);
  }

  const cols = layoutCols(visible.length);
  const rows = Math.ceil(visible.length / cols) || 1;
  const hexCoords = useMemo(() => GridGenerator.rectangle(cols, rows), [cols, rows]);
  const viewBox = useMemo(() => {
    const used = hexCoords.slice(0, visible.length);
    if (!used.length) return { minX: 0, minY: 0, width: 100, height: 80 };
    let minX = Infinity;
    let minY = Infinity;
    let maxX = -Infinity;
    let maxY = -Infinity;
    for (const hex of used) {
      const { x, y } = hexCenter(hex.q, hex.r);
      minX = Math.min(minX, x);
      minY = Math.min(minY, y);
      maxX = Math.max(maxX, x);
      maxY = Math.max(maxY, y);
    }
    const padX = HEX_SIZE.x * 1.2;
    const padY = HEX_SIZE.y * 1.2;
    return {
      minX: minX - padX,
      minY: minY - padY,
      width: maxX - minX + padX * 2,
      height: maxY - minY + padY * 2,
    };
  }, [hexCoords, visible.length]);
  const svgHeight = Math.max(420, Math.round((viewBox.height / Math.max(viewBox.width, 1)) * 820));

  return (
    <TooltipProvider delayDuration={200}>
      <div className="shell honeycomb-shell">
        <header className="topbar">
          <div className="logo">
            <span className="logo-mark" aria-hidden />
            Risk <em>Honeycomb</em>
          </div>
          <div className="top-meta">
            <Badge variant="secondary">{status}</Badge>
            {error && <p className="error">{error}</p>}
            <Button type="button" variant="outline" size="sm" onClick={onReload}>
              Reload
            </Button>
            <Button type="button" size="sm" disabled={running} onClick={onRunPipeline}>
              {running ? "Running…" : "Run prediction"}
            </Button>
          </div>
        </header>

        <section className="honeycomb-hero">
          <div>
            <p className="honeycomb-kicker">Screen 1 · State overview</p>
            <h1>{activeState || "Select a state"}</h1>
            <p>
              Choose a state in the dropdown. The honeycomb shows every city in that state — click a
              hex, then pick a pincode for details.
            </p>
          </div>
          {stateSummary && (
            <Card className="min-w-[260px]">
              <CardContent className="grid grid-cols-2 gap-3 p-4">
                <div>
                  <span className="text-[0.68rem] font-bold uppercase tracking-wider text-[var(--text-dim)]">
                    Cities
                  </span>
                  <strong className="mt-1 block font-[family-name:var(--font-mono)] text-[1.05rem]">
                    {stateSummary.cityCount.toLocaleString()}
                  </strong>
                </div>
                <div>
                  <span className="text-[0.68rem] font-bold uppercase tracking-wider text-[var(--text-dim)]">
                    Avg risk
                  </span>
                  <strong
                    className={cn(
                      "mt-1 block font-[family-name:var(--font-mono)] text-[1.05rem]",
                      riskTone(stateSummary.avgRisk).className,
                    )}
                  >
                    {formatShare(stateSummary.avgRisk)}
                  </strong>
                </div>
                <div>
                  <span className="text-[0.68rem] font-bold uppercase tracking-wider text-[var(--text-dim)]">
                    Pincodes
                  </span>
                  <strong className="mt-1 block font-[family-name:var(--font-mono)] text-[1.05rem]">
                    {stateSummary.zipCount.toLocaleString()}
                  </strong>
                </div>
                <div>
                  <span className="text-[0.68rem] font-bold uppercase tracking-wider text-[var(--text-dim)]">
                    CLV at risk
                  </span>
                  <strong className="danger-text mt-1 block font-[family-name:var(--font-mono)] text-[1.05rem]">
                    −{formatEuro(stateSummary.impact)}
                  </strong>
                </div>
              </CardContent>
            </Card>
          )}
        </section>

        <section className="honeycomb-toolbar">
          <div className="honeycomb-state-select">
            <SearchableSelect
              id="honeycomb-state"
              label="State"
              value={activeState}
              options={stateOptions}
              onChange={(next) => setStateFilter(next)}
              disabled={!states.length}
              placeholder="Search state…"
              emptyMessage={states.length ? "No states match" : "No states loaded"}
            />
          </div>
          <label className="honeycomb-search">
            <span>Find city</span>
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Filter cities in this state…"
              disabled={!activeState}
            />
          </label>
          <div className="risk-legend" aria-label="Risk legend">
            <Badge variant="low">
              <i className="swatch low" /> Low
            </Badge>
            <Badge variant="medium">
              <i className="swatch medium" /> Medium
            </Badge>
            <Badge variant="high">
              <i className="swatch high" /> High
            </Badge>
          </div>
        </section>

        <main className="honeycomb-main">
          {!places.length ? (
            <Card className="mx-auto max-w-md">
              <CardHeader>
                <CardTitle>No area data yet</CardTitle>
                <CardDescription>Click Run prediction to build the state risk honeycomb.</CardDescription>
              </CardHeader>
            </Card>
          ) : !visible.length ? (
            <Card className="mx-auto max-w-md">
              <CardHeader>
                <CardTitle>No cities match</CardTitle>
                <CardDescription>
                  Try another search in {activeState}, or pick a different state.
                </CardDescription>
              </CardHeader>
            </Card>
          ) : (
            <div className="honeycomb-canvas-wrap">
              <Card className="honeycomb-map-card p-0">
                <ZoomPanViewport>
                  <HexGrid
                    className="honeycomb-canvas"
                    width="100%"
                    height={svgHeight}
                    viewBox={`${viewBox.minX} ${viewBox.minY} ${viewBox.width} ${viewBox.height}`}
                    role="img"
                    aria-label={`City honeycomb for ${activeState}`}
                    style={{ touchAction: "none" }}
                    preserveAspectRatio="xMidYMid meet"
                  >
                    <Layout
                      size={HEX_SIZE}
                      flat
                      spacing={HEX_SPACING}
                      origin={{ x: 0, y: 0 }}
                    >
                      {visible.map((city, index) => {
                        const hex = hexCoords[index];
                        if (!hex) return null;
                        const tone = riskTone(city.avgRisk);
                        const isSelected =
                          selected?.city === city.city && selected?.state === city.state;
                        const label =
                          city.city.length > 14 ? `${city.city.slice(0, 13)}…` : city.city;
                        return (
                          <Hexagon
                            key={`${city.state}-${city.city}`}
                            q={hex.q}
                            r={hex.r}
                            s={hex.s}
                            className={cn("hex", tone.className, isSelected && "hex-selected")}
                            cellStyle={{
                              fill: tone.fill,
                              stroke: isSelected ? "#1a1520" : "#fff",
                              strokeWidth: isSelected ? 1.5 : 0.7,
                              cursor: "pointer",
                            }}
                            onMouseEnter={() => setHovered(city)}
                            onMouseLeave={() => setHovered(null)}
                            onMouseDown={() => pinCity(city)}
                            onClick={() => pinCity(city)}
                            onDragStart={(e) => {
                              e.preventDefault();
                            }}
                          >
                            <Text className="hex-label" y={-2.2}>
                              {label}
                            </Text>
                            <Text className="hex-metric" y={0.8}>
                              {formatShare(city.avgRisk)}
                            </Text>
                            <Text className="hex-metric" y={3.4}>
                              {city.zipCount} zip{city.zipCount === 1 ? "" : "s"}
                            </Text>
                          </Hexagon>
                        );
                      })}
                    </Layout>
                  </HexGrid>
                </ZoomPanViewport>
              </Card>

              <Card className="honeycomb-hover" aria-live="polite">
                <CardHeader className="p-4 pb-2">
                  {preview ? (
                    <>
                      <div className="flex items-start justify-between gap-2">
                        <CardTitle>{preview.city}</CardTitle>
                        <Badge variant={riskTone(preview.avgRisk).badge}>
                          {riskTone(preview.avgRisk).label}
                        </Badge>
                      </div>
                      <CardDescription>
                        {preview.state}
                        {selected?.city === preview.city ? " · pinned" : " · hover"}
                      </CardDescription>
                    </>
                  ) : (
                    <>
                      <CardTitle className="text-sm font-medium text-[var(--text-dim)]">
                        City preview
                      </CardTitle>
                      <CardDescription>
                        Click a city hex in the honeycomb to pin it, then choose a pincode.
                      </CardDescription>
                    </>
                  )}
                </CardHeader>
                <CardContent className="space-y-3 p-4 pt-0 text-sm">
                  {preview && (
                    <>
                      <p>
                        Risk <strong>{formatShare(preview.avgRisk)}</strong>
                      </p>
                      <p className="text-[var(--text-dim)]">
                        {preview.zipCount} pincode{preview.zipCount === 1 ? "" : "s"} ·{" "}
                        {preview.customers.toLocaleString()} customers · +{preview.highRisk} high-risk
                      </p>
                      <p className="danger-text font-semibold">
                        −{formatEuro(preview.businessImpactEur)} CLV at risk
                      </p>
                    </>
                  )}

                  {selected && (
                    <div className="honeycomb-drilldowns">
                      <SearchableSelect
                        id="honeycomb-zip"
                        key={`${selected.state}-${selected.city}`}
                        label={`Pincode in ${selected.city}`}
                        value={pickedZip}
                        options={zipOptions}
                        onChange={setPickedZip}
                        disabled={!zipsForCity.length}
                        placeholder="Search pincode…"
                        emptyMessage="No pincodes in this city"
                      />
                    </div>
                  )}

                  <div className="flex flex-col gap-2 pt-1">
                    <Button
                      type="button"
                      size="sm"
                      className="w-full"
                      disabled={!selected || !pickedZip}
                      onClick={() =>
                        selected && onSelectCity(selected.city, selected.state, pickedZip)
                      }
                    >
                      View details →
                    </Button>
                    {selected && (
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="w-full"
                        onClick={() => {
                          setSelected(null);
                          setHovered(null);
                          setPickedZip("");
                        }}
                      >
                        Clear selection
                      </Button>
                    )}
                  </div>
                </CardContent>
              </Card>
            </div>
          )}
          {query && citiesInState.length > visible.length ? (
            <p className="honeycomb-note">
              Showing {visible.length} of {citiesInState.length} cities matching search.
            </p>
          ) : (
            <p className="honeycomb-note">
              Showing all {visible.length} cities in {activeState}.
            </p>
          )}
        </main>
      </div>
    </TooltipProvider>
  );
}
