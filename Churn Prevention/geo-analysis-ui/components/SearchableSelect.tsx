"use client";

import {
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from "react";

export type SearchableOption = {
  value: string;
  label: string;
  hint?: string;
  searchText?: string;
  /** Optional section header in the menu (e.g. "AI suggested campaign"). */
  group?: string;
};

type Props = {
  id?: string;
  label?: string;
  value: string;
  options: SearchableOption[];
  onChange: (value: string) => void;
  placeholder?: string;
  disabled?: boolean;
  emptyMessage?: string;
  /** Hide the field label — for dense table cells. */
  compact?: boolean;
  className?: string;
};

type MenuRow =
  | { kind: "group"; key: string; label: string }
  | { kind: "option"; key: string; option: SearchableOption; index: number };

export function SearchableSelect({
  id,
  label,
  value,
  options,
  onChange,
  placeholder = "Search…",
  disabled = false,
  emptyMessage = "No matches",
  compact = false,
  className = "",
}: Props) {
  const autoId = useId();
  const inputId = id || autoId;
  const listId = `${inputId}-listbox`;
  const rootRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLUListElement>(null);

  const selected = options.find((o) => o.value === value) || null;
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return options;
    return options.filter((o) => {
      const hay = (o.searchText || `${o.label} ${o.hint || ""} ${o.value} ${o.group || ""}`).toLowerCase();
      return hay.includes(q);
    });
  }, [options, query]);

  const menuRows = useMemo(() => {
    const rows: MenuRow[] = [];
    let lastGroup: string | undefined;
    filtered.forEach((option, index) => {
      const group = option.group;
      if (group && group !== lastGroup) {
        rows.push({ kind: "group", key: `g-${group}-${index}`, label: group });
        lastGroup = group;
      }
      rows.push({ kind: "option", key: option.value, option, index });
    });
    return rows;
  }, [filtered]);

  useEffect(() => {
    if (!open) {
      setQuery("");
      setActiveIndex(0);
      return;
    }
    const idx = filtered.findIndex((o) => o.value === value);
    setActiveIndex(idx >= 0 ? idx : 0);
  }, [open, filtered, value]);

  useEffect(() => {
    if (!open) return;
    function onDoc(e: MouseEvent) {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  useEffect(() => {
    if (!open || !listRef.current) return;
    const el = listRef.current.querySelector<HTMLElement>(`[data-index="${activeIndex}"]`);
    el?.scrollIntoView({ block: "nearest" });
  }, [activeIndex, open]);

  function openPanel() {
    if (disabled) return;
    setOpen(true);
    setQuery("");
    requestAnimationFrame(() => inputRef.current?.select());
  }

  function pick(next: string) {
    onChange(next);
    setOpen(false);
    setQuery("");
  }

  function onKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (disabled) return;
    if (!open && (e.key === "ArrowDown" || e.key === "Enter" || e.key === " ")) {
      e.preventDefault();
      openPanel();
      return;
    }
    if (!open) return;

    if (e.key === "Escape") {
      e.preventDefault();
      setOpen(false);
      setQuery("");
      return;
    }
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIndex((i) => Math.min(i + 1, Math.max(filtered.length - 1, 0)));
      return;
    }
    if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIndex((i) => Math.max(i - 1, 0));
      return;
    }
    if (e.key === "Enter") {
      e.preventDefault();
      const opt = filtered[activeIndex];
      if (opt) pick(opt.value);
      return;
    }
    if (e.key === "Tab") {
      setOpen(false);
    }
  }

  const display = open ? query : selected?.label || "";
  const showLabel = Boolean(label) && !compact;

  let labelNode: ReactNode = null;
  if (showLabel) {
    labelNode = <label htmlFor={inputId}>{label}</label>;
  }

  return (
    <div
      className={`combo ${compact ? "compact" : ""} ${disabled ? "disabled" : ""} ${className}`.trim()}
      ref={rootRef}
    >
      {labelNode}
      <div className={`combo-control ${open ? "open" : ""}`}>
        <input
          ref={inputRef}
          id={inputId}
          type="text"
          role="combobox"
          aria-expanded={open}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-label={compact ? label || placeholder : undefined}
          aria-activedescendant={
            open && filtered[activeIndex] ? `${inputId}-opt-${activeIndex}` : undefined
          }
          disabled={disabled}
          placeholder={selected ? selected.label : placeholder}
          value={display}
          onChange={(e) => {
            setQuery(e.target.value);
            setOpen(true);
            setActiveIndex(0);
          }}
          onFocus={openPanel}
          onClick={openPanel}
          onKeyDown={onKeyDown}
          autoComplete="off"
          spellCheck={false}
        />
        <button
          type="button"
          className="combo-chevron"
          tabIndex={-1}
          disabled={disabled}
          aria-label={open ? "Close options" : "Open options"}
          onClick={() => (open ? setOpen(false) : openPanel())}
        />
      </div>

      {open && !disabled && (
        <ul ref={listRef} id={listId} className="combo-menu" role="listbox">
          {filtered.length === 0 && <li className="combo-empty">{emptyMessage}</li>}
          {menuRows.map((row) => {
            if (row.kind === "group") {
              return (
                <li key={row.key} className="combo-group" role="presentation">
                  {row.label}
                </li>
              );
            }
            const { option, index } = row;
            const active = index === activeIndex;
            const isSelected = option.value === value;
            return (
              <li
                key={row.key}
                id={`${inputId}-opt-${index}`}
                data-index={index}
                role="option"
                aria-selected={isSelected}
                className={`combo-option ${active ? "active" : ""} ${isSelected ? "selected" : ""}`}
                onMouseEnter={() => setActiveIndex(index)}
                onMouseDown={(e) => {
                  e.preventDefault();
                  pick(option.value);
                }}
              >
                <span className="combo-option-label">{option.label}</span>
                {option.hint && <span className="combo-option-hint">{option.hint}</span>}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
