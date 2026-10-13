import csv
import re
from pathlib import Path

from app import config


USEFUL = {
    "demographics": "Telco_customer_churn_demographics.csv",
    "services": "Telco_customer_churn_services.csv",
    "status": "Telco_customer_churn_status.csv",
    "location": "Telco_customer_churn_location.csv",
    "population": "Telco_customer_churn_population.csv",
}
WIDE = "Telco_customer_churn.csv"


def _read(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _num(value: str | None) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "").replace("$", "")
    if text == "":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _yes(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"yes", "true", "1"}:
        return "Yes"
    if text in {"no", "false", "0"}:
        return "No"
    return None


def _int(value: str | None) -> int | None:
    number = _num(value)
    if number is None:
        return None
    return int(number)


def _blank(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _row_from_parts(demo: dict, service: dict, status: dict, location: dict, population: int | None) -> dict:
    internet = _yes(service.get("Internet Service"))
    phone = _yes(service.get("Phone Service"))
    unlimited = _yes(service.get("Unlimited Data"))
    security = _yes(service.get("Online Security"))
    support = _yes(service.get("Premium Tech Support") or service.get("Tech Support"))
    dependents = _yes(demo.get("Dependents"))
    multiple = _yes(service.get("Multiple Lines"))
    contract = _blank(service.get("Contract"))
    customer_status = _blank(status.get("Customer Status"))
    churn_score = _int(status.get("Churn Score"))
    return {
        "customer_id": _blank(demo.get("Customer ID") or service.get("Customer ID")),
        "city": _blank(location.get("City")),
        "state": _blank(location.get("State")),
        "zip_code": _blank(location.get("Zip Code")),
        "population": population,
        "age": _int(demo.get("Age")),
        "under_30": _yes(demo.get("Under 30")),
        "senior_citizen": _yes(demo.get("Senior Citizen")),
        "married": _yes(demo.get("Married")),
        "dependents": dependents,
        "number_of_dependents": _int(demo.get("Number of Dependents")),
        "phone_service": phone,
        "multiple_lines": multiple,
        "internet_service": internet,
        "internet_type": _blank(service.get("Internet Type")),
        "avg_monthly_gb": _num(service.get("Avg Monthly GB Download")),
        "unlimited_data": unlimited,
        "online_security": security,
        "premium_tech_support": support,
        "contract": contract,
        "monthly_charge": _num(service.get("Monthly Charge") or service.get("Monthly Charges")),
        "total_extra_data_charges": _num(service.get("Total Extra Data Charges")) or 0.0,
        "tenure_months": _int(service.get("Tenure in Months") or service.get("Tenure Months")),
        "offer": _blank(service.get("Offer")),
        "satisfaction_score": _int(status.get("Satisfaction Score")),
        "customer_status": customer_status,
        "churn_score": churn_score,
        "churn_category": _blank(status.get("Churn Category")),
        "churn_reason": _blank(status.get("Churn Reason")),
        "cltv": _int(status.get("CLTV")),
    }


def as_active_customer(row: dict) -> dict:
    """Treat every dataset row as a current subscriber — no one has left yet.

    Past churn labels are cleared. Predictive flags are derived from
    churn_score and satisfaction_score for area-level risk scoring.
    """
    out = dict(row)
    out["customer_status"] = "Active"
    out["churn_category"] = None
    out["churn_reason"] = None
    score = out.get("churn_score")
    out["high_risk"] = (
        "Yes"
        if isinstance(score, (int, float)) and not isinstance(score, bool) and score >= config.HIGH_RISK_SCORE
        else "No"
    )
    sat = out.get("satisfaction_score")
    out["low_satisfaction"] = (
        "Yes"
        if isinstance(sat, (int, float)) and not isinstance(sat, bool) and sat <= config.LOW_SATISFACTION
        else "No"
    )
    return out


def _from_wide(row: dict) -> dict:
    demo = {
        "Customer ID": row.get("CustomerID") or row.get("Customer ID"),
        "Dependents": row.get("Dependents"),
        "Senior Citizen": row.get("Senior Citizen"),
        "Under 30": row.get("Under 30"),
        "Age": row.get("Age"),
        "Married": row.get("Partner") or row.get("Married"),
        "Number of Dependents": row.get("Number of Dependents"),
    }
    service = {
        "Customer ID": demo["Customer ID"],
        "Internet Service": row.get("Internet Service"),
        "Phone Service": row.get("Phone Service"),
        "Unlimited Data": row.get("Unlimited Data"),
        "Online Security": row.get("Online Security"),
        "Tech Support": row.get("Tech Support"),
        "Multiple Lines": row.get("Multiple Lines"),
        "Contract": row.get("Contract"),
        "Monthly Charges": row.get("Monthly Charges"),
        "Tenure Months": row.get("Tenure Months"),
        "Internet Type": row.get("Internet Type"),
        "Avg Monthly GB Download": row.get("Avg Monthly GB Download"),
        "Total Extra Data Charges": row.get("Total Extra Data Charges"),
        "Offer": row.get("Offer"),
    }
    status = {
        "Customer Status": "Churned" if _yes(row.get("Churn Label") or row.get("Churn")) == "Yes" else "Stayed",
        "Churn Score": row.get("Churn Score"),
        "Churn Category": row.get("Churn Category"),
        "Churn Reason": row.get("Churn Reason"),
        "CLTV": row.get("CLTV"),
        "Satisfaction Score": row.get("Satisfaction Score"),
    }
    location = {
        "City": row.get("City"),
        "State": row.get("State"),
        "Zip Code": row.get("Zip Code"),
    }
    return _row_from_parts(demo, service, status, location, None)


def load_directory(directory: Path) -> tuple[list[dict], list[str]]:
    files = [path.name for path in sorted(directory.glob("*.csv"))]
    useful = all((directory / name).exists() for name in USEFUL.values())
    if useful:
        demos = {row["Customer ID"]: row for row in _read(directory / USEFUL["demographics"])}
        services = {row["Customer ID"]: row for row in _read(directory / USEFUL["services"])}
        statuses = {row["Customer ID"]: row for row in _read(directory / USEFUL["status"])}
        locations = {row["Customer ID"]: row for row in _read(directory / USEFUL["location"])}
        populations: dict[str, int] = {}
        for row in _read(directory / USEFUL["population"]):
            zip_code = _blank(row.get("Zip Code"))
            people = _int(row.get("Population"))
            if zip_code and people is not None:
                populations[zip_code] = people
        rows = []
        for customer_id, demo in demos.items():
            service = services.get(customer_id)
            status = statuses.get(customer_id)
            location = locations.get(customer_id)
            if not service or not status or not location or not location.get("City"):
                continue
            zip_code = _blank(location.get("Zip Code"))
            rows.append(
                as_active_customer(
                    _row_from_parts(demo, service, status, location, populations.get(zip_code or ""))
                )
            )
        return rows, [USEFUL[key] for key in ("demographics", "services", "status", "location", "population")]

    wide = directory / WIDE
    if wide.exists():
        rows = []
        for raw in _read(wide):
            row = as_active_customer(_from_wide(raw))
            if row["customer_id"] and row["city"]:
                rows.append(row)
        return rows, [WIDE]

    raise FileNotFoundError(f"No telco files in {directory}. Found: {', '.join(files) or 'nothing'}")


def sample_preview(rows: list[dict], limit: int = 5) -> list[dict]:
    hidden = {"customer_id"}
    return [{key: value for key, value in row.items() if key not in hidden} for row in rows[:limit]]


def column_names(rows: list[dict]) -> list[str]:
    if not rows:
        return []
    return sorted(rows[0].keys())


_SAFE = re.compile(r"^[A-Za-z0-9_./ -]+$")


def resolve_directory(root: Path, directory: str) -> Path:
    if not directory or not _SAFE.match(directory):
        raise ValueError("directory contains unsupported characters")
    path = (root / directory).resolve()
    if not str(path).startswith(str(root.resolve())):
        raise ValueError("directory must stay inside the backend")
    if not path.is_dir():
        raise ValueError(f"{directory} is not a directory")
    return path
