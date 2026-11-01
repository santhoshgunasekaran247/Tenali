"""GST state codes for place of supply, keyed by the lower-case state/UT name used in addresses."""

STATE_CODES = {
    "jammu and kashmir": "01", "himachal pradesh": "02", "punjab": "03", "chandigarh": "04", "uttarakhand": "05",
    "haryana": "06", "delhi": "07", "rajasthan": "08", "uttar pradesh": "09", "bihar": "10", "sikkim": "11",
    "arunachal pradesh": "12", "nagaland": "13", "manipur": "14", "mizoram": "15", "tripura": "16", "meghalaya": "17",
    "assam": "18", "west bengal": "19", "jharkhand": "20", "odisha": "21", "chhattisgarh": "22", "madhya pradesh": "23",
    "gujarat": "24", "dadra and nagar haveli and daman and diu": "26", "maharashtra": "27", "karnataka": "29", "goa": "30",
    "lakshadweep": "31", "kerala": "32", "tamil nadu": "33", "puducherry": "34", "andaman and nicobar islands": "35",
    "telangana": "36", "andhra pradesh": "37", "ladakh": "38",
}
ALIASES = {"orissa": "odisha", "pondicherry": "puducherry", "uttaranchal": "uttarakhand", "new delhi": "delhi",
           "nct of delhi": "delhi", "tamilnadu": "tamil nadu", "chattisgarh": "chhattisgarh", "j&k": "jammu and kashmir",
           "andaman & nicobar islands": "andaman and nicobar islands", "daman and diu": "dadra and nagar haveli and daman and diu",
           "dadra and nagar haveli": "dadra and nagar haveli and daman and diu"}
NAMES = {code: name.title().replace(" And ", " and ") for name, code in STATE_CODES.items()}


def place_of_supply(state: str | None) -> str | None:
    """Return 'NN - State Name' for a free-text state, or None when it is not recognised."""
    key = " ".join((state or "").strip().lower().replace("&", "and").split())
    key = ALIASES.get(key, key)
    code = STATE_CODES.get(key)
    return f"{code} - {NAMES[code]}" if code else None


def place_of_supply_for_code(code: str | None) -> str | None:
    return f"{code} - {NAMES[code]}" if code in NAMES else None
