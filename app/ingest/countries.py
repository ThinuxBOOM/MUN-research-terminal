"""ISO3 country table with aliases used in UN documents (plan 6.3)."""
from __future__ import annotations

import json

# iso3: (canonical name, aliases)
COUNTRIES: dict[str, tuple[str, list[str]]] = {
    "ARG": ("Argentina", ["argentine republic"]),
    "AUS": ("Australia", []),
    "AUT": ("Austria", []),
    "BGD": ("Bangladesh", []),
    "BEL": ("Belgium", []),
    "BOL": ("Bolivia", ["plurinational state of bolivia"]),
    "BRA": ("Brazil", []),
    "BGR": ("Bulgaria", []),
    "CAN": ("Canada", []),
    "CHL": ("Chile", []),
    "CHN": ("China", ["people's republic of china", "prc"]),
    "COL": ("Colombia", []),
    "CRI": ("Costa Rica", []),
    "CIV": ("Côte d'Ivoire", ["cote d'ivoire", "ivory coast"]),
    "HRV": ("Croatia", []),
    "CUB": ("Cuba", []),
    "CZE": ("Czechia", ["czech republic"]),
    "DNK": ("Denmark", []),
    "DOM": ("Dominican Republic", []),
    "ECU": ("Ecuador", []),
    "EGY": ("Egypt", ["arab republic of egypt"]),
    "SLV": ("El Salvador", []),
    "EST": ("Estonia", []),
    "ETH": ("Ethiopia", []),
    "FJI": ("Fiji", []),
    "FIN": ("Finland", []),
    "FRA": ("France", ["french republic"]),
    "GAB": ("Gabon", []),
    "GEO": ("Georgia", []),
    "DEU": ("Germany", ["federal republic of germany"]),
    "GHA": ("Ghana", []),
    "GRC": ("Greece", ["hellenic republic"]),
    "GTM": ("Guatemala", []),
    "GUY": ("Guyana", []),
    "HTI": ("Haiti", ["republic of haiti"]),
    "HND": ("Honduras", []),
    "IND": ("India", []),
    "IDN": ("Indonesia", []),
    "IRN": ("Iran", ["islamic republic of iran"]),
    "IRQ": ("Iraq", []),
    "IRL": ("Ireland", []),
    "ISR": ("Israel", []),
    "ITA": ("Italy", []),
    "JAM": ("Jamaica", []),
    "JPN": ("Japan", []),
    "JOR": ("Jordan", ["hashemite kingdom of jordan"]),
    "KAZ": ("Kazakhstan", []),
    "KEN": ("Kenya", []),
    "KWT": ("Kuwait", []),
    "LVA": ("Latvia", []),
    "LBN": ("Lebanon", []),
    "LBY": ("Libya", []),
    "LTU": ("Lithuania", []),
    "LUX": ("Luxembourg", []),
    "MYS": ("Malaysia", []),
    "MDV": ("Maldives", []),
    "MLI": ("Mali", []),
    "MLT": ("Malta", []),
    "MEX": ("Mexico", ["mexican states"]),
    "MDA": ("Republic of Moldova", ["moldova"]),
    "MAR": ("Morocco", []),
    "MOZ": ("Mozambique", []),
    "NPL": ("Nepal", []),
    "NLD": ("Netherlands", ["kingdom of the netherlands"]),
    "NZL": ("New Zealand", []),
    "NIC": ("Nicaragua", []),
    "NER": ("Niger", []),
    "NGA": ("Nigeria", []),
    "NOR": ("Norway", []),
    "PAK": ("Pakistan", []),
    "PAN": ("Panama", []),
    "PER": ("Peru", []),
    "PHL": ("Philippines", []),
    "POL": ("Poland", []),
    "PRT": ("Portugal", []),
    "QAT": ("Qatar", []),
    "KOR": ("Republic of Korea", ["south korea", "korea, republic of"]),
    "PRK": ("Democratic People's Republic of Korea", ["north korea"]),
    "ROU": ("Romania", []),
    "RUS": ("Russian Federation", ["russia", "ussr", "soviet union"]),
    "SAU": ("Saudi Arabia", []),
    "SEN": ("Senegal", []),
    "SRB": ("Serbia", []),
    "SLE": ("Sierra Leone", []),
    "SGP": ("Singapore", []),
    "SVK": ("Slovakia", []),
    "SVN": ("Slovenia", []),
    "SOM": ("Somalia", []),
    "ZAF": ("South Africa", []),
    "ESP": ("Spain", []),
    "LKA": ("Sri Lanka", []),
    "SDN": ("Sudan", []),
    "SWE": ("Sweden", []),
    "CHE": ("Switzerland", []),
    "SYR": ("Syrian Arab Republic", ["syria"]),
    "TWN": ("Taiwan", []),
    "TJK": ("Tajikistan", []),
    "TZA": ("United Republic of Tanzania", ["tanzania"]),
    "THA": ("Thailand", []),
    "TLS": ("Timor-Leste", ["east timor"]),
    "TUN": ("Tunisia", []),
    "TUR": ("Türkiye", ["turkey", "turkiye"]),
    "UGA": ("Uganda", []),
    "UKR": ("Ukraine", []),
    "ARE": ("United Arab Emirates", ["uae"]),
    "GBR": ("United Kingdom", ["united kingdom of great britain and northern ireland",
                               "great britain", "uk", "britain"]),
    "USA": ("United States", ["united states of america", "us", "usa", "u.s."]),
    "URY": ("Uruguay", []),
    "VEN": ("Venezuela", ["bolivarian republic of venezuela"]),
    "VNM": ("Viet Nam", ["vietnam"]),
    "YEM": ("Yemen", []),
    "ZMB": ("Zambia", []),
    "ZWE": ("Zimbabwe", []),
}

UNSC_15 = ["CHN", "FRA", "RUS", "GBR", "USA", "DZA", "ECU", "GUY", "JPN", "MLT",
           "MOZ", "KOR", "SLE", "SVN", "SOM"]

_ALIAS_INDEX: dict[str, str] = {}


def _build_index() -> None:
    if _ALIAS_INDEX:
        return
    for iso3, (name, aliases) in COUNTRIES.items():
        for label in [name, name.replace("Türkiye", "Turkey"), *aliases]:
            _ALIAS_INDEX[label.lower().strip()] = iso3


def lookup(name: str | None) -> str | None:
    """Map a country name in a document to its ISO3 code."""
    if not name:
        return None
    _build_index()
    cleaned = name.strip().strip(".,;:").lower()
    cleaned = cleaned.replace("the ", "", 1) if cleaned.startswith("the ") else cleaned
    if cleaned in _ALIAS_INDEX:
        return _ALIAS_INDEX[cleaned]
    # Try without a leading article or trailing parenthetical.
    for candidate in (cleaned.split(" (")[0], cleaned.replace(".", "")):
        if candidate in _ALIAS_INDEX:
            return _ALIAS_INDEX[candidate]
    for label, iso3 in _ALIAS_INDEX.items():
        if len(label) > 3 and label in cleaned:
            return iso3
    return None


def name_of(iso3: str) -> str:
    return COUNTRIES.get(iso3, (iso3, []))[0]


def seed(conn) -> None:
    for iso3, (name, aliases) in COUNTRIES.items():
        conn.execute(
            "INSERT INTO countries(iso3, name, aliases) VALUES (?, ?, ?) "
            "ON CONFLICT(iso3) DO UPDATE SET name = excluded.name, aliases = excluded.aliases",
            (iso3, name, json.dumps(aliases)),
        )
    conn.commit()


def all_iso3() -> list[str]:
    return sorted(COUNTRIES)
