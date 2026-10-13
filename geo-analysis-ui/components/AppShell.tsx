"use client";

import { useCallback, useEffect, useState } from "react";
import { AreaStudio } from "@/components/AreaStudio";
import { RiskHoneycomb } from "@/components/RiskHoneycomb";
import { API_URL, Place } from "@/lib/types";

type Screen = "honeycomb" | "detail";

export function AppShell() {
  const [screen, setScreen] = useState<Screen>("honeycomb");
  const [places, setPlaces] = useState<Place[]>([]);
  const [status, setStatus] = useState("Checking backend…");
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedCity, setSelectedCity] = useState("");
  const [selectedState, setSelectedState] = useState("");
  const [selectedZip, setSelectedZip] = useState("");

  const refreshStatus = useCallback(async () => {
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
  }, []);

  const loadPlaces = useCallback(async () => {
    try {
      const res = await fetch(`${API_URL}/pincodes?include_thin=true`);
      const body = await res.json();
      setPlaces(body.places ?? []);
      setError(null);
    } catch {
      setError("Failed to load areas");
    }
  }, []);

  useEffect(() => {
    void refreshStatus();
    void loadPlaces();
  }, [refreshStatus, loadPlaces]);

  async function runPipeline() {
    setRunning(true);
    setError(null);
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
    } catch (err) {
      setError(err instanceof Error ? err.message : "Pipeline failed");
    } finally {
      setRunning(false);
    }
  }

  function openCity(city: string, state: string, zip?: string) {
    setSelectedCity(city);
    setSelectedState(state);
    setSelectedZip(zip || "");
    setScreen("detail");
  }

  function backToHoneycomb() {
    setScreen("honeycomb");
  }

  if (screen === "detail") {
    return (
      <AreaStudio
        initialCity={selectedCity}
        initialState={selectedState}
        initialZip={selectedZip}
        onBack={backToHoneycomb}
        sharedPlaces={places}
        onPlacesChange={setPlaces}
      />
    );
  }

  return (
    <RiskHoneycomb
      places={places}
      status={status}
      running={running}
      error={error}
      onReload={() => {
        void refreshStatus();
        void loadPlaces();
      }}
      onRunPipeline={() => void runPipeline()}
      onSelectCity={openCity}
    />
  );
}
