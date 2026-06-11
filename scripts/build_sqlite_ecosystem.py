#!/usr/bin/env python3
"""Build a populated, realistic SQLite enterprise data ecosystem from a JSON spec.

Deterministic, stdlib-only engine. Given an ecosystem spec (see
references/generator-spec.md), it:

1. Validates the spec (fail fast with spec-path error messages).
2. Emits SQLite DDL artifacts (schema, indexes, views, derivations).
3. Generates source-system rows with realistic distributions, business
   calendars, personas, coherent geography, and check-digit identifiers in
   provably fictional ranges.
4. Simulates business-process state machines (status history + timestamps).
5. Runs derivation SQL in-database so staging/canonical/warehouse layers are
   genuinely derived from source rows (real lineage).
6. Injects controlled imperfections at configured rates, logging every one to
   meta_imperfection_log so validation can reconcile them.
7. Writes meta tables (meta_build_info, meta_table_stats) and a build summary.

Exit codes: 0 success, 1 build/spec failure, 2 usage error.
"""

from __future__ import annotations

import argparse
import bisect
import datetime as dt
import difflib
import hashlib
import json
import math
import os
import random
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Callable, Iterator

ENGINE_VERSION = "2.0"

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class SpecError(Exception):
    """Spec problem. Message must contain a spec path like tables[3].columns[2]."""


def suggest(value: str, options: list[str]) -> str:
    matches = difflib.get_close_matches(str(value), options, n=1)
    return f" Did you mean '{matches[0]}'?" if matches else ""


# ---------------------------------------------------------------------------
# Deterministic RNG substreams
# ---------------------------------------------------------------------------


def substream(seed: Any, *keys: Any) -> random.Random:
    """Independent RNG stream keyed by stable strings (not process-salted hash).

    Normative derivation (documented in references/generator-spec.md): parts are
    joined with \\x1f so key boundaries can never collide, hashed with sha256,
    and the first 8 bytes seed random.Random.
    """
    material = "\x1f".join([str(seed)] + [str(k) for k in keys])
    digest = hashlib.sha256(material.encode("utf-8")).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


# ---------------------------------------------------------------------------
# Distribution sampling
# ---------------------------------------------------------------------------

DISTRIBUTIONS = [
    "uniform", "normal", "lognormal", "zipf", "pareto", "poisson",
    "beta", "exponential", "geometric", "triangular", "constant",
]


def _poisson(rng: random.Random, lam: float) -> int:
    if lam <= 0:
        return 0
    if lam > 30:
        return max(0, int(round(rng.normalvariate(lam, math.sqrt(lam)))))
    threshold = math.exp(-lam)
    k, p = 0, 1.0
    while True:
        p *= rng.random()
        if p <= threshold:
            return k
        k += 1


def sample_number(rng: random.Random, cfg: dict[str, Any], where: str) -> float:
    """Sample one value from a distribution config dict."""
    dist = str(cfg.get("distribution", "uniform")).lower()
    if dist not in DISTRIBUTIONS:
        raise SpecError(f"{where}: unknown distribution '{dist}'.{suggest(dist, DISTRIBUTIONS)}")
    if dist == "constant":
        value = float(cfg.get("value", 0))
    elif dist == "uniform":
        value = rng.uniform(float(cfg.get("min", 0)), float(cfg.get("max", 1)))
    elif dist == "normal":
        value = rng.normalvariate(float(cfg.get("mean", 0)), float(cfg.get("stdev", 1)))
    elif dist == "lognormal":
        median = float(cfg.get("median", cfg.get("mean", 1)))
        if median <= 0:
            raise SpecError(f"{where}: lognormal median must be > 0.")
        value = rng.lognormvariate(math.log(median), float(cfg.get("sigma", 0.5)))
    elif dist == "pareto":
        value = rng.paretovariate(float(cfg.get("alpha", 1.5))) * float(cfg.get("xm", 1.0))
    elif dist == "poisson":
        value = float(_poisson(rng, float(cfg.get("lam", cfg.get("mean", 1)))))
    elif dist == "beta":
        value = rng.betavariate(float(cfg.get("alpha", 2)), float(cfg.get("beta", 5))) * float(cfg.get("scale", 1.0))
    elif dist == "exponential":
        mean = float(cfg.get("mean", 1.0))
        if mean <= 0:
            raise SpecError(f"{where}: exponential mean must be > 0.")
        value = rng.expovariate(1.0 / mean)
    elif dist == "geometric":
        p = float(cfg.get("p", 0.5))
        if not 0 < p < 1:
            raise SpecError(f"{where}: geometric p must be in (0,1).")
        value = float(int(math.log(max(rng.random(), 1e-12)) / math.log(1.0 - p)) + 1)
    elif dist == "triangular":
        value = rng.triangular(float(cfg.get("min", 0)), float(cfg.get("max", 1)), float(cfg.get("mode", (float(cfg.get("min", 0)) + float(cfg.get("max", 1))) / 2)))
    elif dist == "zipf":
        # Zipf as a numeric value: rank sampled from n ranks with exponent s.
        n, s = int(cfg.get("n", 100)), float(cfg.get("s", 1.1))
        weights = [1.0 / (r ** s) for r in range(1, n + 1)]
        total = sum(weights)
        target, acc = rng.random() * total, 0.0
        value = float(n)
        for idx, w in enumerate(weights):
            acc += w
            if target <= acc:
                value = float(idx + 1)
                break
    else:  # pragma: no cover
        raise SpecError(f"{where}: unhandled distribution '{dist}'.")

    if "min" in cfg and dist not in {"uniform", "triangular"}:
        value = max(value, float(cfg["min"]))
    if "max" in cfg and dist not in {"uniform", "triangular"}:
        value = min(value, float(cfg["max"]))
    return value


def round_value(value: float, cfg: dict[str, Any]) -> Any:
    if cfg.get("round") is True or cfg.get("decimals") == 0:
        return int(round(value))
    if "decimals" in cfg:
        return round(value, int(cfg["decimals"]))
    return value


def zipf_cumweights(n: int, s: float) -> list[float]:
    cum, acc = [], 0.0
    for rank in range(1, n + 1):
        acc += 1.0 / (rank ** s)
        cum.append(acc)
    return cum


# ---------------------------------------------------------------------------
# Fictional data pools (deterministic, no third-party deps, safe-by-design)
# ---------------------------------------------------------------------------

FIRST_NAMES = [
    "Aaliyah", "Adam", "Adriana", "Ahmed", "Aiko", "Aisha", "Alejandro", "Alex",
    "Amara", "Amelia", "Ananya", "Anders", "Andrea", "Anika", "Anthony", "Arjun",
    "Astrid", "Aurora", "Beatriz", "Benjamin", "Bianca", "Brandon", "Brigid",
    "Camila", "Carlos", "Carmen", "Caroline", "Chiara", "Chinedu", "Claire",
    "Daniel", "Dariusz", "David", "Deepa", "Derek", "Diego", "Dmitri", "Elena",
    "Elias", "Elif", "Emeka", "Emily", "Emma", "Erik", "Esperanza", "Ethan",
    "Eva", "Farah", "Fatima", "Felix", "Fiona", "Francesca", "Gabriel", "Gemma",
    "Giovanni", "Grace", "Hannah", "Hans", "Haruki", "Hassan", "Helena", "Henry",
    "Hiroshi", "Ibrahim", "Imani", "Ines", "Ingrid", "Isaac", "Isabella", "Ivan",
    "Jack", "Jacob", "Jasmine", "Javier", "Jin", "Joanna", "Jonas", "Jorge",
    "Julia", "Kai", "Kamala", "Karim", "Katarzyna", "Keiko", "Kevin", "Kwame",
    "Laila", "Lars", "Laura", "Leah", "Leon", "Liam", "Lin", "Lucas", "Lucia",
    "Magnus", "Malik", "Marcus", "Margaret", "Maria", "Mariam", "Mateo", "Maya",
    "Mei", "Mia", "Michael", "Miguel", "Mikhail", "Mina", "Mohammed", "Nadia",
    "Naomi", "Natalia", "Nathan", "Nia", "Nikolai", "Noah", "Noor", "Olivia",
    "Omar", "Oscar", "Padma", "Paolo", "Patricia", "Pavel", "Pedro", "Priya",
    "Quinn", "Rachel", "Rafael", "Raj", "Ravi", "Rebecca", "Renata", "Ricardo",
    "Rosa", "Ruth", "Ryan", "Sadia", "Samuel", "Sanjay", "Sara", "Sebastian",
    "Selin", "Seo-yeon", "Sofia", "Sven", "Tariq", "Tatiana", "Thomas", "Tomas",
    "Uma", "Valentina", "Victor", "Wei", "William", "Xiomara", "Yara", "Yusuf",
    "Zainab", "Zoe",
]

LAST_NAMES = [
    "Abara", "Abbott", "Acevedo", "Adler", "Aguilar", "Ahmadi", "Akhtar",
    "Almeida", "Alvarez", "Andersson", "Antonov", "Arnold", "Baker", "Banerjee",
    "Barnes", "Becker", "Bell", "Bennett", "Berg", "Bishop", "Blanc", "Bouchard",
    "Boyd", "Brennan", "Brooks", "Burton", "Calloway", "Camara", "Campos",
    "Cardoso", "Carter", "Castillo", "Chambers", "Chandra", "Chen", "Choi",
    "Clarke", "Cole", "Conti", "Cortez", "Costa", "Crawford", "Cruz", "Dalton",
    "Das", "Davies", "Delgado", "Demir", "Diallo", "Diaz", "Dimitrov", "Dixon",
    "Doyle", "Dubois", "Duran", "Eriksen", "Esposito", "Farrell", "Fernandez",
    "Ferreira", "Fischer", "Fleming", "Flores", "Fontaine", "Foster", "Fujimoto",
    "Gallagher", "Garcia", "Gibson", "Gonzalez", "Graham", "Grant", "Gruber",
    "Gupta", "Hahn", "Hamid", "Hansen", "Harper", "Hayashi", "Henderson",
    "Hernandez", "Holloway", "Horvath", "Hossain", "Huang", "Hughes", "Ibrahim",
    "Iqbal", "Ivanova", "Jackson", "Jansen", "Jimenez", "Johansson", "Kapoor",
    "Karlsson", "Kaur", "Keller", "Kennedy", "Khan", "Kim", "Kowalski", "Kumar",
    "Lambert", "Larsen", "Lawson", "Lee", "Lindqvist", "Liu", "Lopez", "Ma",
    "Mackenzie", "Maldonado", "Marino", "Marsh", "Martinez", "Mbeki", "McCarthy",
    "Mehta", "Mendez", "Mercer", "Meyer", "Mitchell", "Mohammed", "Morales",
    "Moreau", "Morgan", "Mori", "Mueller", "Murphy", "Nakamura", "Navarro",
    "Nguyen", "Nielsen", "Novak", "Obi", "O'Brien", "Okafor", "Olsen", "Ortiz",
    "Osei", "Oyelaran", "Park", "Patel", "Pavlov", "Pereira", "Petrov", "Pham",
    "Popescu", "Porter", "Quintero", "Rahman", "Ramirez", "Rao", "Reyes",
    "Richter", "Rivera", "Roberts", "Romano", "Rossi", "Roy", "Ruiz", "Sanchez",
    "Santos", "Sato", "Schmidt", "Schneider", "Sharma", "Shaw", "Silva", "Singh",
    "Sokolov", "Soto", "Steele", "Suzuki", "Takahashi", "Tanaka", "Thompson",
    "Torres", "Tran", "Vance", "Vargas", "Vasquez", "Vega", "Virtanen", "Wagner",
    "Walsh", "Wang", "Watanabe", "Weber", "Whitfield", "Wong", "Wright", "Wu",
    "Yamamoto", "Yilmaz", "Yoon", "Zhang", "Zhao",
]

STREET_NAMES = [
    "Alder", "Aspen", "Bayview", "Beacon", "Birch", "Bluff", "Boulder",
    "Briarwood", "Cardinal", "Cedar", "Chestnut", "Clearwater", "Cobblestone",
    "Crestview", "Cypress", "Dogwood", "Eastgate", "Elm", "Fairfield", "Falcon",
    "Foxglove", "Garnet", "Glenwood", "Granite", "Harbor", "Hawthorn",
    "Heather", "Hickory", "Highland", "Hillcrest", "Ironwood", "Juniper",
    "Keystone", "Lakeshore", "Larkspur", "Laurel", "Magnolia", "Maple",
    "Meadowbrook", "Mill Creek", "Monarch", "Northfield", "Oakridge", "Orchard",
    "Pinecrest", "Prairie", "Quarry", "Redwood", "Ridgeline", "Riverbend",
    "Rosewood", "Saddleback", "Sagebrush", "Sandpiper", "Silverleaf",
    "Springfield", "Sterling", "Stonebridge", "Summit", "Sycamore", "Tamarack",
    "Thornton", "Timberline", "Trailhead", "Valley View", "Walnut", "Westbrook",
    "Whispering Pines", "Willow", "Winterberry",
]

STREET_SUFFIXES = ["St", "Ave", "Blvd", "Dr", "Ln", "Rd", "Way", "Ct", "Pkwy", "Ter"]

# (city, region/state, postal prefix, phone area code) — public geography only.
PLACES = [
    ("Albany", "NY", "122", "518"), ("Albuquerque", "NM", "871", "505"),
    ("Atlanta", "GA", "303", "404"), ("Austin", "TX", "787", "512"),
    ("Baltimore", "MD", "212", "410"), ("Boise", "ID", "837", "208"),
    ("Boston", "MA", "021", "617"), ("Buffalo", "NY", "142", "716"),
    ("Charlotte", "NC", "282", "704"), ("Chicago", "IL", "606", "312"),
    ("Cincinnati", "OH", "452", "513"), ("Cleveland", "OH", "441", "216"),
    ("Columbus", "OH", "432", "614"), ("Dallas", "TX", "752", "214"),
    ("Denver", "CO", "802", "303"), ("Des Moines", "IA", "503", "515"),
    ("Detroit", "MI", "482", "313"), ("El Paso", "TX", "799", "915"),
    ("Fresno", "CA", "937", "559"), ("Grand Rapids", "MI", "495", "616"),
    ("Hartford", "CT", "061", "860"), ("Houston", "TX", "770", "713"),
    ("Indianapolis", "IN", "462", "317"), ("Jacksonville", "FL", "322", "904"),
    ("Kansas City", "MO", "641", "816"), ("Knoxville", "TN", "379", "865"),
    ("Las Vegas", "NV", "891", "702"), ("Little Rock", "AR", "722", "501"),
    ("Louisville", "KY", "402", "502"), ("Madison", "WI", "537", "608"),
    ("Memphis", "TN", "381", "901"), ("Miami", "FL", "331", "305"),
    ("Milwaukee", "WI", "532", "414"), ("Minneapolis", "MN", "554", "612"),
    ("Nashville", "TN", "372", "615"), ("New Orleans", "LA", "701", "504"),
    ("Oklahoma City", "OK", "731", "405"), ("Omaha", "NE", "681", "402"),
    ("Orlando", "FL", "328", "407"), ("Philadelphia", "PA", "191", "215"),
    ("Phoenix", "AZ", "850", "602"), ("Pittsburgh", "PA", "152", "412"),
    ("Portland", "OR", "972", "503"), ("Providence", "RI", "029", "401"),
    ("Raleigh", "NC", "276", "919"), ("Richmond", "VA", "232", "804"),
    ("Sacramento", "CA", "958", "916"), ("Salt Lake City", "UT", "841", "801"),
    ("San Antonio", "TX", "782", "210"), ("San Diego", "CA", "921", "619"),
    ("Seattle", "WA", "981", "206"), ("Spokane", "WA", "992", "509"),
    ("St. Louis", "MO", "631", "314"), ("Tampa", "FL", "336", "813"),
    ("Tucson", "AZ", "857", "520"), ("Tulsa", "OK", "741", "918"),
]

COMPANY_HEADS = [
    "Apex", "Beacon", "Blue Harbor", "Bridgewater", "Cascade", "Cedar Point",
    "Copperline", "Crestway", "Eastbrook", "Evermont", "Fairhaven", "Goldleaf",
    "Granite Peak", "Greenfield", "Harborline", "Highbridge", "Ironvale",
    "Keystone", "Lakecrest", "Longview", "Maplewood", "Meridian", "Northgate",
    "Oakhaven", "Pinnacle", "Redstone", "Ridgeway", "Riverstone", "Silverpine",
    "Southport", "Stonebrook", "Summitview", "Thornfield", "Trailside",
    "Vantage", "Westfield", "Whitewater", "Willowbrook", "Windmere", "Wolfpoint",
]

COMPANY_FLAVORS = {
    "generic": ["Group", "Partners", "Industries", "Enterprises", "Holdings", "Solutions", "Services"],
    "food": ["Foods", "Provisions", "Kitchens", "Catering", "Produce", "Bakery", "Beverage Co"],
    "restaurant": ["Grill", "Bistro", "Tavern", "Diner", "Cafe", "Kitchen", "Eatery", "Pizzeria", "Cantina"],
    "healthcare": ["Health", "Medical Group", "Clinic", "Care Partners", "Wellness Center", "Health System"],
    "finance": ["Capital", "Asset Management", "Financial", "Advisors", "Investments", "Trust"],
    "tech": ["Systems", "Software", "Technologies", "Labs", "Digital", "Analytics", "Cloud"],
    "logistics": ["Freight", "Logistics", "Carriers", "Transport", "Shipping", "Distribution"],
    "manufacturing": ["Manufacturing", "Fabrication", "Components", "Industrial", "Precision Works", "Tooling"],
    "retail": ["Retail Group", "Stores", "Outfitters", "Supply Co", "Trading Co", "Market"],
    "insurance": ["Insurance", "Mutual", "Assurance", "Underwriters", "Risk Partners"],
    "energy": ["Energy", "Power", "Utilities", "Renewables", "Grid Services"],
    "realestate": ["Properties", "Realty", "Development", "Estates", "Property Group"],
}

EMAIL_DOMAINS = ["example.com", "example.org", "example.net"]

TEXT_POOLS = {
    "support_topic": [
        "billing discrepancy", "login issue", "delivery delay", "damaged item",
        "missing invoice", "duplicate charge", "account access", "pricing question",
        "order change request", "statement question", "integration error",
        "report mismatch", "password reset", "address update", "credit request",
    ],
    "support_action": [
        "Escalated to tier 2.", "Resolved on first contact.",
        "Issued credit memo.", "Requested supporting documents.",
        "Scheduled follow-up call.", "Updated account record.",
        "Forwarded to billing team.", "Reprocessed the transaction.",
        "Confirmed fix with customer.", "Pending customer response.",
    ],
    "delivery_note": [
        "Left at loading dock.", "Signed by receiver.", "Receiver unavailable, redelivery scheduled.",
        "Partial delivery, balance to follow.", "Refused damaged carton.",
        "Delivered to back entrance per instructions.", "Gate code required, see account notes.",
        "Temperature check passed.", "Pallet count verified.", "Short one case, credit requested.",
    ],
    "audit_comment": [
        "Adjusted per supervisor approval.", "Corrected data entry error.",
        "Backdated per source document.", "Override approved by manager.",
        "Reclassified after review.", "Updated following customer call.",
        "Matched to source statement.", "Adjusted during month-end close.",
    ],
    "exception_note": [
        "Awaiting source file resend.", "Vendor confirmed mapping change.",
        "Duplicate suspected, under review.", "Tolerance breach, investigating.",
        "Manual match applied.", "Aged break escalated.", "Root cause: late feed.",
        "Pending counterparty confirmation.",
    ],
}

JOB_TITLES = [
    "Analyst", "Senior Analyst", "Manager", "Senior Manager", "Director",
    "Coordinator", "Specialist", "Team Lead", "Supervisor", "Associate",
    "VP", "Administrator", "Consultant", "Officer",
]

PRODUCT_WORDS = {
    "food": ["Diced Tomatoes", "Chicken Breast", "Olive Oil", "Cheddar Block", "Romaine Hearts",
             "Ground Beef", "Basmati Rice", "Black Beans", "Mozzarella Shred", "Pork Loin",
             "Atlantic Salmon", "Penne Pasta", "Marinara Sauce", "Russet Potatoes", "Yellow Onions",
             "Heavy Cream", "Butter Solids", "Maple Syrup", "Coffee Beans", "Orange Juice",
             "Flour Tortillas", "Bacon Strips", "Turkey Breast", "Greek Yogurt", "Mixed Greens"],
    "generic": ["Standard Unit", "Premium Unit", "Economy Pack", "Bulk Carton", "Service Kit",
                "Starter Set", "Replacement Part", "Accessory Pack", "Maintenance Kit"],
}


# ---------------------------------------------------------------------------
# Identifier factories — all constrained to fictional / reserved ranges
# ---------------------------------------------------------------------------


def luhn_check_digit(digits: str) -> int:
    total = 0
    for idx, ch in enumerate(reversed(digits)):
        d = int(ch)
        if idx % 2 == 0:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return (10 - total % 10) % 10


def gen_masked_card(rng: random.Random) -> str:
    return "************" + f"{rng.randrange(10000):04d}"


def gen_luhn(rng: random.Random, prefix: str, length: int) -> str:
    body = prefix + "".join(str(rng.randrange(10)) for _ in range(length - len(prefix) - 1))
    return body + str(luhn_check_digit(body))


def gen_aba_routing(rng: random.Random) -> str:
    # Prefix 99 is outside assigned Federal Reserve districts: fictional by design.
    base = "99" + "".join(str(rng.randrange(10)) for _ in range(6))
    weights = [3, 7, 1, 3, 7, 1, 3, 7]
    checksum = sum(int(d) * w for d, w in zip(base, weights)) % 10
    return base + str((10 - checksum) % 10)


def gen_iban(rng: random.Random) -> str:
    # Country code ZZ is not assigned; mod-97 check digits are valid.
    bban = "".join(str(rng.randrange(10)) for _ in range(16))
    rearranged = bban + "ZZ00"
    numeric = "".join(str(int(c, 36)) for c in rearranged)
    check = 98 - int(numeric) % 97
    return f"ZZ{check:02d}{bban}"


def gen_isin(rng: random.Random) -> str:
    # ZZ country prefix (unassigned). Check digit per ISO 6166 (Luhn over expanded digits).
    base = "ZZ" + "".join(rng.choice("0123456789ABCDEFGHJKLMNPQRSTUVWXYZ") for _ in range(9))
    expanded = "".join(str(int(c, 36)) for c in base)
    return base + str(_isin_check(expanded))


def _isin_check(expanded: str) -> int:
    total = 0
    for idx, ch in enumerate(reversed(expanded)):
        d = int(ch)
        if idx % 2 == 0:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return (10 - total % 10) % 10


def gen_cusip(rng: random.Random) -> str:
    # 99xxxxxx range is reserved for internal/user assignment.
    chars = "0123456789ABCDEFGHJKLMNPQRSTUVWXYZ"
    base = "99" + "".join(rng.choice(chars) for _ in range(6))
    total = 0
    for idx, ch in enumerate(base):
        v = int(ch, 36)
        if idx % 2 == 1:
            v *= 2
        total += v // 10 + v % 10
    return base + str((10 - total % 10) % 10)


def gen_npi_like(rng: random.Random) -> str:
    # Real NPIs start with 1 or 2; we use 9 so the value can never be real,
    # while keeping the standard 80840-prefixed Luhn check digit.
    base = "9" + "".join(str(rng.randrange(10)) for _ in range(8))
    return base + str(luhn_check_digit("80840" + base))


def gen_gtin13(rng: random.Random) -> str:
    # GS1 prefix 952 is reserved for demonstrations and examples.
    base = "952" + "".join(str(rng.randrange(10)) for _ in range(9))
    total = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(base))
    return base + str((10 - total % 10) % 10)


def gen_vin_like(rng: random.Random) -> str:
    chars = "ABCDEFGHJKLMNPRSTUVWXYZ0123456789"
    return "ZZZ" + "".join(rng.choice(chars) for _ in range(14))


def gen_lei_like(rng: random.Random) -> str:
    return "ZZ00" + "".join(rng.choice("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ") for _ in range(14)) + f"{rng.randrange(100):02d}"


IDENTIFIER_KINDS = {
    "masked_card": gen_masked_card,
    "aba_routing": gen_aba_routing,
    "iban": gen_iban,
    "isin": gen_isin,
    "cusip": gen_cusip,
    "npi": gen_npi_like,
    "gtin13": gen_gtin13,
    "vin": gen_vin_like,
    "lei": gen_lei_like,
}


# ---------------------------------------------------------------------------
# Safe expression evaluator
# ---------------------------------------------------------------------------

import ast

_ALLOWED_FUNCS = {"round": round, "abs": abs, "min": min, "max": max, "int": int, "float": float}


class ExpressionEvaluator:
    def __init__(self, expression: str, where: str):
        self.where = where
        self.expression = expression
        try:
            self.tree = ast.parse(expression, mode="eval")
        except SyntaxError as exc:
            raise SpecError(f"{where}: invalid expression '{expression}': {exc.msg}")
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Call):
                if not isinstance(node.func, ast.Name) or node.func.id not in _ALLOWED_FUNCS:
                    raise SpecError(f"{where}: only {sorted(_ALLOWED_FUNCS)} calls allowed in expressions.")
            elif not isinstance(node, (
                ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant, ast.Name,
                ast.Load, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow,
                ast.USub, ast.UAdd, ast.IfExp, ast.Compare, ast.Eq, ast.NotEq, ast.Lt, ast.LtE,
                ast.Gt, ast.GtE, ast.BoolOp, ast.And, ast.Or, ast.Call,
            )):
                raise SpecError(f"{where}: expression element '{type(node).__name__}' not allowed.")

    def evaluate(self, row: dict[str, Any]) -> Any:
        try:
            return self._eval(self.tree.body, row)
        except _NullOperand:
            return None
        except SpecError:
            raise
        except Exception as exc:
            raise SpecError(f"{self.where}: expression '{self.expression}' failed: {exc}")

    def _eval(self, node: ast.AST, row: dict[str, Any]) -> Any:
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            if node.id not in row:
                raise SpecError(f"{self.where}: expression references unknown column '{node.id}'.{suggest(node.id, list(row))}")
            value = row[node.id]
            if value is None:
                raise _NullOperand()
            return value
        if isinstance(node, ast.BinOp):
            left, right = self._eval(node.left, row), self._eval(node.right, row)
            ops = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b,
                   ast.Mult: lambda a, b: a * b, ast.Div: lambda a, b: a / b,
                   ast.FloorDiv: lambda a, b: a // b, ast.Mod: lambda a, b: a % b,
                   ast.Pow: lambda a, b: a ** b}
            return ops[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp):
            value = self._eval(node.operand, row)
            return -value if isinstance(node.op, ast.USub) else +value
        if isinstance(node, ast.IfExp):
            return self._eval(node.body, row) if self._eval(node.test, row) else self._eval(node.orelse, row)
        if isinstance(node, ast.Compare):
            left = self._eval(node.left, row)
            for op, comparator in zip(node.ops, node.comparators):
                right = self._eval(comparator, row)
                ok = {ast.Eq: left == right, ast.NotEq: left != right, ast.Lt: left < right,
                      ast.LtE: left <= right, ast.Gt: left > right, ast.GtE: left >= right}[type(op)]
                if not ok:
                    return False
                left = right
            return True
        if isinstance(node, ast.BoolOp):
            if isinstance(node.op, ast.And):
                return all(self._eval(v, row) for v in node.values)
            return any(self._eval(v, row) for v in node.values)
        if isinstance(node, ast.Call):
            args = [self._eval(a, row) for a in node.args]
            return _ALLOWED_FUNCS[node.func.id](*args)
        raise SpecError(f"{self.where}: unsupported expression node {type(node).__name__}.")


class _NullOperand(Exception):
    pass


# ---------------------------------------------------------------------------
# Business calendar
# ---------------------------------------------------------------------------


class BusinessCalendar:
    """Day-weight model over the spec time horizon: weekday shape, seasonality,
    holidays, and a compounding growth trend. Supports weighted date sampling
    and business-hours-biased timestamps."""

    def __init__(self, spec: dict[str, Any]):
        time_cfg = spec.get("time", {})
        self.start = parse_date(time_cfg.get("start_date", "2024-01-01"), "time.start_date")
        self.end = parse_date(time_cfg.get("end_date", "2025-12-31"), "time.end_date")
        self.as_of = parse_date(time_cfg.get("as_of_date", time_cfg.get("end_date", "2025-12-31")), "time.as_of_date")
        if self.end < self.start:
            raise SpecError("time.end_date is before time.start_date.")
        cal = spec.get("calendar", {})
        weekday = cal.get("weekday_weights", [1.0, 1.02, 1.02, 1.0, 0.96, 0.30, 0.12])
        if len(weekday) != 7:
            raise SpecError("calendar.weekday_weights must have 7 values (Mon..Sun).")
        month = cal.get("month_weights", [1.0] * 12)
        if len(month) != 12:
            raise SpecError("calendar.month_weights must have 12 values (Jan..Dec).")
        holidays = {parse_date(h, "calendar.holidays") for h in cal.get("holidays", [])}
        growth = float(cal.get("annual_growth", 0.0))
        hours = cal.get("business_hours", [8, 18])
        self.biz_start, self.biz_end = int(hours[0]), int(hours[1])

        self.days: list[dt.date] = []
        cum, acc = [], 0.0
        day = self.start
        while day <= self.end:
            w = weekday[day.weekday()] * month[day.month - 1]
            if day in holidays:
                w *= 0.05
            w *= (1.0 + growth) ** ((day - self.start).days / 365.25)
            acc += max(w, 0.0001)
            self.days.append(day)
            cum.append(acc)
            day += dt.timedelta(days=1)
        self.cum = cum
        self.total = acc

    def sample_date(self, rng: random.Random, lo: dt.date | None = None, hi: dt.date | None = None) -> dt.date:
        # Right-censor at as_of: bare draws never land after the reporting date.
        # Deliberately future-dated columns must use date_offset with clamp_as_of false.
        ceiling = min(self.end, self.as_of)
        if hi is None or hi > ceiling:
            hi = ceiling
        lo_idx = 0 if lo is None or lo <= self.start else (lo - self.start).days
        hi_idx = len(self.days) - 1 if hi >= self.end else (hi - self.start).days
        lo_idx = max(0, min(lo_idx, len(self.days) - 1))
        hi_idx = max(lo_idx, min(hi_idx, len(self.days) - 1))
        lo_cum = self.cum[lo_idx - 1] if lo_idx > 0 else 0.0
        target = lo_cum + rng.random() * (self.cum[hi_idx] - lo_cum)
        idx = bisect.bisect_left(self.cum, target, lo_idx, hi_idx + 1)
        return self.days[min(idx, hi_idx)]

    def sample_timestamp(self, rng: random.Random, lo: dt.date | None = None,
                         hi: dt.date | None = None, business_hours: bool = True) -> dt.datetime:
        day = self.sample_date(rng, lo, hi)
        return dt.datetime.combine(day, self.sample_time(rng, business_hours))

    def sample_time(self, rng: random.Random, business_hours: bool = True) -> dt.time:
        if business_hours and rng.random() >= 0.04:
            # 4% after-hours stragglers: a 100%-in-hours histogram reads as synthetic.
            mid = (self.biz_start + self.biz_end) / 2
            hour = rng.triangular(self.biz_start, self.biz_end, mid)
        else:
            hour = rng.uniform(0, 24)
        hour = max(0.0, min(hour, 23.999))
        h = int(hour)
        m = int((hour - h) * 60)
        return dt.time(h, m, rng.randrange(60))


def parse_date(value: Any, where: str) -> dt.date:
    try:
        return dt.date.fromisoformat(str(value))
    except ValueError:
        raise SpecError(f"{where}: '{value}' is not an ISO date (YYYY-MM-DD).")


def iso(value: Any) -> Any:
    if isinstance(value, dt.datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, dt.date):
        return value.isoformat()
    return value


# ---------------------------------------------------------------------------
# Spec normalization: traits, defaults, identifiers
# ---------------------------------------------------------------------------

SQLITE_TYPES = {
    "string": "text", "text": "text", "integer": "integer", "bigint": "integer",
    "decimal": "real", "number": "real", "float": "real", "boolean": "integer",
    "date": "text", "timestamp": "text", "json": "text",
}

TRAITS = {
    "audited": [
        {"name": "created_at", "type": "timestamp", "gen": {"type": "auto_created_at"}},
        {"name": "created_by", "type": "string", "gen": {"type": "staff_user"}},
        {"name": "updated_at", "type": "timestamp", "gen": {"type": "auto_updated_at"}},
        {"name": "updated_by", "type": "string", "gen": {"type": "staff_user"}},
    ],
    "source_stamped": [
        {"name": "source_system", "type": "string", "gen": {"type": "table_source_system"}},
        {"name": "source_updated_at", "type": "timestamp", "gen": {"type": "auto_created_at"}},
        {"name": "ingested_at", "type": "timestamp", "gen": {"type": "auto_ingested_at"}},
        {"name": "batch_id", "type": "string", "gen": {"type": "batch_id"}},
    ],
    "soft_delete": [
        {"name": "active_flag", "type": "boolean", "gen": {"type": "boolean", "p_true": 0.93}},
    ],
    "effective_dated": [
        {"name": "effective_start_date", "type": "date", "gen": {"type": "auto_effective_start"}},
        {"name": "effective_end_date", "type": "date", "nullable": True, "gen": {"type": "constant", "value": None}},
        {"name": "current_flag", "type": "boolean", "gen": {"type": "constant", "value": 1}},
    ],
}

TABLE_SOURCES = {"generator", "state_machine", "derivation", "empty"}


def table_key(tbl: dict[str, Any]) -> str:
    schema = tbl.get("schema")
    return f"{schema}.{tbl['name']}" if schema else tbl["name"]


def physical_name(ref: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_]", "_", ref.replace(".", "_"))
    if not re.match(r"^[A-Za-z_]", name):
        name = "_" + name
    return name.lower()


class TableSpec:
    def __init__(self, raw: dict[str, Any], index: int, spec: dict[str, Any]):
        self.raw = raw
        self.where = f"tables[{index}]"
        if "name" not in raw:
            raise SpecError(f"{self.where}: missing 'name'.")
        self.key = table_key(raw)
        self.physical = physical_name(self.key)
        self.layer = str(raw.get("layer", "")).lower()
        self.source = str(raw.get("source", "generator")).lower()
        if self.source not in TABLE_SOURCES:
            raise SpecError(f"{self.where} ({self.key}): source '{self.source}' not in {sorted(TABLE_SOURCES)}.")
        self.source_system = raw.get("source_system")
        self.purpose = raw.get("purpose", "")
        self.grain = raw.get("grain", "")
        self.primary_key = raw.get("primary_key") or []
        if isinstance(self.primary_key, str):
            self.primary_key = [self.primary_key]
        self.natural_key = raw.get("natural_key") or []
        if isinstance(self.natural_key, str):
            self.natural_key = [self.natural_key]
        self.indexes = raw.get("indexes", [])
        self.rows_cfg = raw.get("rows", 0)
        self.scale_exempt = bool(raw.get("scale_exempt", False))
        self.history = raw.get("history")
        self.columns: list[dict[str, Any]] = [dict(c) for c in raw.get("columns", [])]

        existing = {c.get("name") for c in self.columns}
        for trait in raw.get("traits", []):
            if trait not in TRAITS:
                raise SpecError(f"{self.where} ({self.key}): unknown trait '{trait}'.{suggest(trait, list(TRAITS))}")
            for col in TRAITS[trait]:
                if col["name"] not in existing:
                    self.columns.append(dict(col))
                    existing.add(col["name"])

        self.column_names = [c.get("name") for c in self.columns]
        if self.source == "generator" and not self.columns:
            raise SpecError(f"{self.where} ({self.key}): generator table has no columns.")
        org = spec.get("organization", {})
        ident = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
        for ci, col in enumerate(self.columns):
            if not col.get("name"):
                raise SpecError(f"{self.where}.columns[{ci}]: missing 'name'.")
            if not ident.match(str(col["name"])):
                raise SpecError(f"{self.where}.columns[{ci}]: column name '{col['name']}' must match "
                                "[A-Za-z_][A-Za-z0-9_]* (it is interpolated into SQL).")
            col_where = f"{self.where} ({self.key}).columns[{col['name']}]"
            col["gen"] = normalize_gen(col.get("gen"), col_where)
            if col["gen"] is None and self.source == "generator":
                inferred = infer_gen(col, self.primary_key, org)
                if inferred is not None:
                    col["gen"] = inferred
        for label, names in (("primary_key", self.primary_key), ("natural_key", self.natural_key)):
            for name in names:
                if not ident.match(str(name)):
                    raise SpecError(f"{self.where} ({self.key}): {label} entry '{name}' is not a valid identifier.")
        for index in self.indexes:
            for name in (index if isinstance(index, list) else [index]):
                if not ident.match(str(name)):
                    raise SpecError(f"{self.where} ({self.key}): index column '{name}' is not a valid identifier.")

    def fk_refs(self) -> list[tuple[str, str]]:
        """(column, ref_table_key) pairs from column generators + explicit FKs."""
        refs = []
        for col in self.columns:
            gen = col.get("gen") or {}
            if gen.get("type") == "fk" and gen.get("ref"):
                refs.append((col["name"], str(gen["ref"])))
        for fk in self.raw.get("foreign_keys", []):
            cols = fk.get("columns", [])
            ref = fk.get("ref") or fk.get("ref_table")
            if cols and ref:
                refs.append((cols[0], str(ref)))
        return refs


# ---------------------------------------------------------------------------
# Row generation
# ---------------------------------------------------------------------------

GENERATOR_TYPES = [
    "sequence", "uuid", "pattern", "constant", "copy", "expression", "case",
    "choice", "boolean", "int", "number", "money", "date", "timestamp",
    "date_offset", "fk", "fk_copy", "self_fk", "parent_key", "parent_copy",
    "child_index", "person_first", "person_last", "person_full", "email",
    "business_email", "phone", "username", "job_title", "company_name", "addr_street",
    "addr_city", "addr_region", "addr_postal", "addr_full", "identifier",
    "text_template", "lorem_note", "staff_user", "table_source_system",
    "batch_id", "auto_created_at", "auto_updated_at", "auto_ingested_at",
    "auto_effective_start", "skip",
]

_NOARG_SHORTHANDS = {
    "uuid", "date", "timestamp", "person_first", "person_last", "person_full",
    "email", "phone", "username", "job_title", "addr_street", "addr_city",
    "addr_region", "addr_postal", "addr_full", "parent_key", "child_index",
    "staff_user", "batch_id", "skip", "self_fk",
}


def _parse_dist_args(text: str, where: str) -> dict[str, Any]:
    """Parse 'lognormal(median=5, sigma=0.8)' / 'uniform(1, 10)' into a config."""
    match = re.match(r"^\s*([a-z_]+)\s*(?:\((.*)\))?\s*$", text)
    if not match:
        raise SpecError(f"{where}: cannot parse distribution shorthand '{text}'.")
    dist, argtext = match.group(1), match.group(2)
    cfg: dict[str, Any] = {"distribution": dist}
    positional_names = {"uniform": ["min", "max"], "normal": ["mean", "stdev"],
                        "lognormal": ["median", "sigma"], "poisson": ["lam"],
                        "pareto": ["alpha", "xm"], "beta": ["alpha", "beta", "scale"],
                        "exponential": ["mean"], "geometric": ["p"],
                        "triangular": ["min", "max", "mode"], "constant": ["value"],
                        "zipf": ["n", "s"]}
    if argtext:
        pos_idx = 0
        for part in argtext.split(","):
            part = part.strip()
            if not part:
                continue
            if "=" in part:
                key, value = part.split("=", 1)
                cfg[key.strip()] = _coerce_number(value.strip())
            else:
                names = positional_names.get(dist, [])
                if pos_idx >= len(names):
                    raise SpecError(f"{where}: too many positional args in '{text}'.")
                cfg[names[pos_idx]] = _coerce_number(part)
                pos_idx += 1
    return cfg


def _coerce_number(text: str) -> Any:
    try:
        return int(text)
    except ValueError:
        try:
            return float(text)
        except ValueError:
            return text


def normalize_gen(gen: Any, where: str) -> dict[str, Any] | None:
    """Expand string shorthand generators into canonical object form.

    Supported shorthands:
      "seq" / "seq:CUST-%06d"            sequence with optional format
      "pattern:ORD-########"              pattern (# digit, @ upper, ? lower, * alnum)
      "fk:erp.product" / "fk:erp.product@zipf"
      "choice:A=0.6,B=0.3,C=0.1" / "choice:A,B,C"
      "int:uniform(1,10)" "number:lognormal(median=5,sigma=0.8)" "money:lognormal(median=120)"
      "bool:0.9"                          boolean with p_true
      "const:VALUE"                       constant string
      "copy:other_column"
      "expr:quantity * unit_price"
      "text:pool_name"                    lorem_note from a vocab pool
      "identifier:isin"                   (or other identifier kinds / luhn)
      "company:food"                      company_name with flavor
      plus bare no-arg types: "uuid", "date", "timestamp", "email", "phone", ...
    """
    if gen is None:
        return None
    if isinstance(gen, dict):
        return gen
    if not isinstance(gen, str):
        raise SpecError(f"{where}: 'gen' must be a string shorthand or object.")
    text = gen.strip()
    head, _, tail = text.partition(":")
    head = head.strip().lower()
    tail = tail.strip()
    if head in _NOARG_SHORTHANDS and not tail:
        return {"type": head}
    if head in {"seq", "sequence"}:
        return {"type": "sequence", "format": tail} if tail else {"type": "sequence"}
    if head == "pattern":
        return {"type": "pattern", "pattern": tail}
    if head == "fk":
        ref, _, weighting = tail.partition("@")
        out: dict[str, Any] = {"type": "fk", "ref": ref.strip()}
        if weighting:
            w = weighting.strip()
            zipf_match = re.match(r"^zipf\((\d+(?:\.\d+)?)\)$", w)
            if zipf_match:
                out["weighting"] = "zipf"
                out["zipf_s"] = float(zipf_match.group(1))
            else:
                out["weighting"] = w
        return out
    if head == "choice":
        values, weights, weighted = [], [], False
        for part in tail.split(","):
            part = part.strip()
            if not part:
                continue
            if "=" in part:
                value, weight = part.rsplit("=", 1)
                values.append(value.strip())
                weights.append(float(weight))
                weighted = True
            else:
                values.append(part)
                weights.append(1.0)
        if not values:
            raise SpecError(f"{where}: choice shorthand has no values.")
        out = {"type": "choice", "values": values}
        if weighted:
            out["weights"] = weights
        return out
    if head in {"int", "number", "money"}:
        cfg = _parse_dist_args(tail, where) if tail else {}
        cfg["type"] = head
        return cfg
    if head in {"bool", "boolean"}:
        return {"type": "boolean", "p_true": float(tail) if tail else 0.5}
    if head in {"const", "constant"}:
        return {"type": "constant", "value": _coerce_number(tail) if tail else None}
    if head == "copy":
        return {"type": "copy", "column": tail}
    if head in {"expr", "expression"}:
        return {"type": "expression", "expression": tail}
    if head == "text":
        return {"type": "lorem_note", "pool": tail or "support_action"}
    if head == "identifier":
        return {"type": "identifier", "kind": tail}
    if head == "company":
        return {"type": "company_name", "flavor": tail or "generic"}
    raise SpecError(f"{where}: unknown generator shorthand '{text}'."
                    f"{suggest(head, GENERATOR_TYPES + ['seq', 'expr', 'const', 'bool', 'text', 'company'])}")


_INFERENCE_RULES: list[tuple[str, dict[str, Any]]] = [
    (r"(^|_)email(_address)?$", {"type": "email"}),
    (r"(^|_)phone(_number)?$|^mobile$|^fax$", {"type": "phone"}),
    (r"^first_name$", {"type": "person_first"}),
    (r"^last_name$", {"type": "person_last"}),
    (r"^(full_name|contact_name|person_name|member_name|patient_name|employee_name)$", {"type": "person_full"}),
    (r"^(company_name|legal_name|business_name|account_name|customer_name|supplier_name|vendor_name)$",
     {"type": "company_name"}),
    (r"^(street|street_address|address_line_?1|address1)$", {"type": "addr_street"}),
    (r"^city$", {"type": "addr_city"}),
    (r"^(state|region|province|state_code)$", {"type": "addr_region"}),
    (r"^(zip|zip_code|postal_code|postcode)$", {"type": "addr_postal"}),
    (r"^country(_code)?$", {"type": "constant", "value": "US"}),
    (r"^created_by$|^updated_by$|^entered_by$|^assigned_to$", {"type": "staff_user"}),
    (r"(^|_)notes?$|^comment(s)?$", {"type": "lorem_note", "pool": "support_action"}),
]


def infer_gen(col: dict[str, Any], tbl_primary_key: list[str], org: dict[str, Any]) -> dict[str, Any] | None:
    """Infer a generator from column name/type when none is declared."""
    name = str(col.get("name", "")).lower()
    ctype = str(col.get("type", "string")).lower()
    if tbl_primary_key == [col.get("name")] and ctype in {"integer", "bigint"}:
        return {"type": "sequence"}
    if name == "currency" or name == "currency_code":
        return {"type": "constant", "value": org.get("currency", "USD")}
    for pattern, gen in _INFERENCE_RULES:
        if re.search(pattern, name):
            return dict(gen)
    return None


class GenerationContext:
    """Per-build shared state: calendar, caches, personas, staff pool."""

    def __init__(self, spec: dict[str, Any], seed: int, calendar: BusinessCalendar):
        self.spec = spec
        self.seed = seed
        self.calendar = calendar
        self.org = spec.get("organization", {})
        self.vocab = dict(TEXT_POOLS)
        for name, words in (spec.get("vocab") or {}).items():
            self.vocab[name] = list(words)
        # parent caches: table_key -> {"pks": [...], "rows": {pk: {col: val}}, "cols": set}
        self.cache: dict[str, dict[str, Any]] = {}
        rng = substream(seed, "__staff__")
        self.staff = [
            f"{rng.choice(FIRST_NAMES).lower()}.{rng.choice(LAST_NAMES).lower()}".replace("'", "").replace(" ", "")
            for _ in range(int(spec.get("staff_pool_size", 40)))
        ]
        self.staff.extend(["system", "batch_loader", "api_service"])
        # Zipf-weighted actor concentration: a handful of heavy users plus a long
        # tail, which is what a GROUP BY created_by shows in any real system.
        self.staff_cum = zipf_cumweights(len(self.staff), 1.2)

    def needed_cache_columns(self, tables: list[TableSpec]) -> dict[str, set]:
        needed: dict[str, set] = {}
        for tbl in tables:
            parent_ref = per_parent_ref(tbl.rows_cfg)
            for col in tbl.columns:
                gen = col.get("gen") or {}
                gtype = gen.get("type")
                if gtype == "fk_copy":
                    ref = gen.get("ref")
                    src = gen.get("source_column")
                    if ref and src:
                        needed.setdefault(str(ref), set()).add(src)
                if gtype == "fk" and isinstance(gen.get("match"), dict):
                    ref = gen.get("ref")
                    pcol = gen["match"].get("parent_column")
                    if ref and pcol:
                        needed.setdefault(str(ref), set()).add(pcol)
                if gtype == "parent_copy" and parent_ref:
                    src = gen.get("source_column")
                    if src:
                        needed.setdefault(parent_ref, set()).add(src)
                for ref_field in ("from", "min", "max"):
                    value = str(gen.get(ref_field, ""))
                    if value.startswith("parent.") and parent_ref:
                        needed.setdefault(parent_ref, set()).add(value.split(".", 1)[1])
        for tbl in tables:
            if isinstance(tbl.rows_cfg, dict):
                scale_by = tbl.rows_cfg.get("scale_by")
                parent = per_parent_ref(tbl.rows_cfg)
                if scale_by and parent and scale_by.get("parent_column"):
                    needed.setdefault(parent, set()).add(str(scale_by["parent_column"]))
        for machine in self.spec.get("state_machines", []):
            tkey = str(machine.get("table", ""))
            if machine.get("start_column"):
                needed.setdefault(tkey, set()).add(str(machine["start_column"]))
        return needed


def per_parent_ref(rows_cfg: Any) -> str | None:
    if isinstance(rows_cfg, dict) and rows_cfg.get("per_parent"):
        return str(rows_cfg["per_parent"])
    return None


def resolve_row_count(rows_cfg: Any, multiplier: float, exempt: bool, where: str) -> int:
    if isinstance(rows_cfg, (int, float)):
        base = float(rows_cfg)
    elif isinstance(rows_cfg, dict) and "base" in rows_cfg:
        base = float(rows_cfg["base"])
    else:
        raise SpecError(f"{where}: rows must be a number, {{'base': n}}, or {{'per_parent': ...}}.")
    if not exempt:
        base *= multiplier
    return max(0, int(round(base)))


class TableGenerator:
    def __init__(self, tbl: TableSpec, ctx: GenerationContext):
        self.tbl = tbl
        self.ctx = ctx
        self.rngs: dict[str, random.Random] = {}
        self.seq_counters: dict[str, int] = {}
        self.compiled_expr: dict[str, ExpressionEvaluator] = {}
        self.fk_pools: dict[str, dict[str, Any]] = {}
        self.unique_seen: dict[str, set] = {}
        self.own_pks: list[Any] = []
        self.track_own_pks = any((c.get("gen") or {}).get("type") == "self_fk" for c in tbl.columns)
        self.sorted_pools: dict[str, list[Any]] = {}
        self.chain_pools: dict[str, list[str]] = {}
        self.chain_counts: dict[str, dict[str, int]] = {}

    def rng_for(self, purpose: str) -> random.Random:
        if purpose not in self.rngs:
            self.rngs[purpose] = substream(self.ctx.seed, self.tbl.key, purpose)
        return self.rngs[purpose]

    # -- FK pools ---------------------------------------------------------

    def fk_pool(self, ref: str, weighting: str, where: str, zipf_s: float = 1.1) -> dict[str, Any]:
        pool_key = f"{ref}|{weighting}|{zipf_s}"
        if pool_key in self.fk_pools:
            return self.fk_pools[pool_key]
        cache = self.ctx.cache.get(ref)
        if cache is None or not cache["pks"]:
            raise SpecError(f"{where}: fk ref '{ref}' has no generated rows yet. "
                            f"Check table order / per_parent target. Known tables: {sorted(self.ctx.cache)[:20]}")
        pks = list(cache["pks"])
        pool: dict[str, Any] = {"pks": pks}
        if weighting == "zipf":
            order_rng = substream(self.ctx.seed, self.tbl.key, "fkorder", ref)
            shuffled = list(pks)
            order_rng.shuffle(shuffled)
            pool["pks"] = shuffled
            pool["cum"] = zipf_cumweights(len(shuffled), zipf_s)
        elif weighting == "recency":
            # Linear recency: later-generated parents (later insertion order) are hotter.
            cum = []
            acc = 0.0
            for i in range(len(pks)):
                acc += (i + 1)
                cum.append(acc)
            pool["cum"] = cum
        self.fk_pools[pool_key] = pool
        return pool

    def pick_fk(self, rng: random.Random, ref: str, weighting: str, where: str,
                match: dict[str, Any] | None = None, row: dict[str, Any] | None = None,
                zipf_s: float = 1.1) -> Any:
        if match and row is not None:
            # Affinity: prefer parents whose attribute matches a local column
            # (e.g. order.warehouse picked from warehouses in the customer's region),
            # with a leak_rate share of cross-matches for realism.
            local_col = match.get("local_column")
            parent_col = match.get("parent_column")
            leak = float(match.get("leak_rate", 0.05))
            if local_col not in row:
                raise SpecError(f"{where}: fk match.local_column '{local_col}' must be an earlier column.")
            local_value = row.get(local_col)
            if local_value is not None and rng.random() >= leak:
                index_key = f"{ref}|matchidx|{parent_col}"
                index = self.fk_pools.get(index_key)
                if index is None:
                    cache = self.ctx.cache.get(ref, {})
                    grouped: dict[Any, list] = {}
                    for pk_value, cached in cache.get("rows", {}).items():
                        grouped.setdefault(cached.get(parent_col), []).append(pk_value)
                    index = {"groups": grouped}
                    self.fk_pools[index_key] = index
                candidates = index["groups"].get(local_value)
                if candidates:
                    return candidates[rng.randrange(len(candidates))]
        pool = self.fk_pool(ref, weighting, where, zipf_s)
        pks = pool["pks"]
        if weighting in {"zipf", "recency"}:
            cum = pool["cum"]
            target = rng.random() * cum[-1]
            return pks[min(bisect.bisect_left(cum, target), len(pks) - 1)]
        return pks[rng.randrange(len(pks))]

    # -- Personas / places --------------------------------------------------

    def persona(self, row_state: dict[str, Any], rng: random.Random) -> dict[str, str]:
        if "__persona__" not in row_state:
            first, last = rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)
            clean = lambda s: re.sub(r"[^a-z]", "", s.lower())
            user = f"{clean(first)}.{clean(last)}{rng.randrange(100):02d}"
            row_state["__persona__"] = {
                "first": first, "last": last, "full": f"{first} {last}",
                "user": user, "email": f"{user}@{rng.choice(EMAIL_DOMAINS)}",
            }
        return row_state["__persona__"]

    def place(self, row_state: dict[str, Any], rng: random.Random) -> dict[str, str]:
        if "__place__" not in row_state:
            city, region, zip3, area = rng.choice(PLACES)
            row_state["__place__"] = {
                "street": f"{rng.randrange(100, 9900)} {rng.choice(STREET_NAMES)} {rng.choice(STREET_SUFFIXES)}",
                "city": city, "region": region,
                "postal": f"{zip3}{rng.randrange(100):02d}",
                "area": area,
            }
        return row_state["__place__"]

    # -- Column generation ---------------------------------------------------

    def generate_value(self, col: dict[str, Any], gen: dict[str, Any], row: dict[str, Any],
                       row_state: dict[str, Any], row_index: int,
                       parent: dict[str, Any] | None, child_index: int) -> Any:
        name = col["name"]
        where = f"{self.tbl.where} ({self.tbl.key}).columns[{name}]"
        gtype = str(gen.get("type", "")).lower()
        rng = self.rng_for(f"col:{name}")
        cal = self.ctx.calendar

        if gtype not in GENERATOR_TYPES:
            raise SpecError(f"{where}: unknown generator type '{gtype}'.{suggest(gtype, GENERATOR_TYPES)}")

        if gtype == "skip":
            return None
        if gtype == "sequence":
            start = int(gen.get("start", 1))
            step = int(gen.get("step", 1))
            counter = self.seq_counters.get(name, 0)
            self.seq_counters[name] = counter + 1
            value = start + counter * step
            fmt = gen.get("format")
            if fmt:
                return fmt.format(value) if "{" in fmt else fmt % value
            return value
        if gtype == "uuid":
            return hashlib.sha256(f"{self.ctx.seed}|{self.tbl.key}|{name}|{row_index}".encode()).hexdigest()[:32]
        if gtype == "pattern":
            return self._pattern(rng, str(gen.get("pattern", "######")), gen, name, where)
        if gtype == "constant":
            return gen.get("value")
        if gtype == "copy":
            src = gen.get("column")
            if src not in row:
                raise SpecError(f"{where}: copy references unknown/later column '{src}'. Columns generate in listed order.")
            return row[src]
        if gtype == "expression":
            if name not in self.compiled_expr:
                self.compiled_expr[name] = ExpressionEvaluator(str(gen.get("expression", "0")), where)
            value = self.compiled_expr[name].evaluate(row)
            if value is not None and ("decimals" in gen or gen.get("round")):
                value = round_value(float(value), gen)
            return value
        if gtype == "case":
            on = gen.get("on")
            if on not in row:
                raise SpecError(f"{where}: case 'on' column '{on}' not generated yet (column order matters).")
            cases = gen.get("cases", {})
            branch = cases.get(str(row[on]), gen.get("default"))
            if branch is None:
                return None
            if not isinstance(branch, dict):
                return branch
            return self.generate_value(col, branch, row, row_state, row_index, parent, child_index)
        if gtype == "choice":
            values = gen.get("values")
            if not values:
                raise SpecError(f"{where}: choice requires 'values'.")
            if isinstance(values[0], dict):
                opts = [v.get("value") for v in values]
                weights = [float(v.get("weight", 1)) for v in values]
            else:
                opts = list(values)
                weights = [float(w) for w in gen.get("weights", [1] * len(opts))]
            if len(weights) != len(opts):
                raise SpecError(f"{where}: weights length != values length.")
            return rng.choices(opts, weights=weights, k=1)[0]
        if gtype == "boolean":
            return 1 if rng.random() < float(gen.get("p_true", 0.5)) else 0
        if gtype in {"int", "number", "money"}:
            cfg = dict(gen)
            cfg.setdefault("distribution", "lognormal" if gtype == "money" else "uniform")
            value = sample_number(rng, cfg, where)
            if gtype == "int":
                return int(round(value))
            if gtype == "money":
                endings = gen.get("price_endings")
                if endings:
                    value = math.floor(value) + float(rng.choice(endings))
                return round(value, int(gen.get("decimals", 2)))
            return round_value(value, cfg)
        if gtype == "date":
            if name in self.sorted_pools:
                return self.sorted_pools[name][row_index]
            lo = self._bound_date(gen.get("min"), row, parent, where)
            hi = self._bound_date(gen.get("max"), row, parent, where)
            return cal.sample_date(rng, lo, hi)
        if gtype == "timestamp":
            if name in self.sorted_pools:
                return self.sorted_pools[name][row_index]
            lo = self._bound_date(gen.get("min"), row, parent, where)
            hi = self._bound_date(gen.get("max"), row, parent, where)
            return cal.sample_timestamp(rng, lo, hi, business_hours=gen.get("business_hours", True))
        if gtype == "date_offset":
            return self._date_offset(rng, gen, row, parent, where)
        if gtype == "fk":
            ref = gen.get("ref")
            if not ref:
                raise SpecError(f"{where}: fk requires 'ref' (schema.table).")
            null_p = float(gen.get("null_rate", 0))
            if null_p and rng.random() < null_p:
                return None
            return self.pick_fk(rng, str(ref), str(gen.get("weighting", "uniform")), where,
                                match=gen.get("match"), row=row,
                                zipf_s=float(gen.get("zipf_s", 1.1)))
        if gtype == "self_fk":
            # Hierarchy parent: pick among rows generated earlier in this table.
            root_share = float(gen.get("root_share", 0.25))
            if not self.own_pks or rng.random() < root_share:
                return None
            return self.own_pks[rng.randrange(len(self.own_pks))]
        if gtype == "fk_copy":
            local = gen.get("column")
            ref = gen.get("ref")
            src = gen.get("source_column")
            if not (local and ref and src):
                raise SpecError(f"{where}: fk_copy requires 'column' (local fk), 'ref', 'source_column'.")
            pk_value = row.get(local)
            if pk_value is None:
                return None
            cache = self.ctx.cache.get(str(ref), {})
            parent_row = cache.get("rows", {}).get(pk_value)
            if parent_row is None:
                return None
            value = parent_row.get(src)
            jitter = float(gen.get("jitter", 0))
            if jitter and isinstance(value, (int, float)) and value is not None:
                value = value * (1 + rng.uniform(-jitter, jitter))
                value = round(value, int(gen.get("decimals", 2)))
            return value
        if gtype == "parent_key":
            if parent is None:
                raise SpecError(f"{where}: parent_key used but table has no per_parent rows config.")
            return parent["__pk__"]
        if gtype == "parent_copy":
            if parent is None:
                raise SpecError(f"{where}: parent_copy used but table has no per_parent rows config.")
            return parent.get(str(gen.get("source_column")))
        if gtype == "child_index":
            return int(gen.get("start", 1)) + child_index
        if gtype == "person_first":
            return self.persona(row_state, rng)["first"]
        if gtype == "person_last":
            return self.persona(row_state, rng)["last"]
        if gtype == "person_full":
            return self.persona(row_state, rng)["full"]
        if gtype == "email":
            domain = gen.get("domain")
            persona = self.persona(row_state, rng)
            return f"{persona['user']}@{domain}" if domain else persona["email"]
        if gtype == "business_email":
            # Role or proprietor address on a company-derived subdomain of
            # example.com — RFC 2606 keeps every subdomain provably fictional.
            company_col = gen.get("company_column")
            if company_col not in row:
                raise SpecError(f"{where}: business_email.company_column '{company_col}' must be an "
                                f"earlier column.{suggest(str(company_col), list(row))}")
            company = row.get(company_col)
            if company is None:
                return None
            slug = re.sub(r"[^a-z0-9]+", "-", str(company).lower()).strip("-")[:32].strip("-")
            slug = re.sub(r"-?\d+$", "", slug).strip("-") or "company"  # chain locations share a brand domain
            roles = gen.get("roles", ["orders", "ap", "info", "office", "manager"])
            if rng.random() < float(gen.get("role_share", 0.55)):
                local = str(rng.choice(roles))
            else:
                persona = self.persona(row_state, rng)
                local = re.sub(r"[^a-z]", "", persona["first"].lower()) or "owner"
            return f"{local}@{slug}.example.com"
        if gtype == "username":
            return self.persona(row_state, rng)["user"]
        if gtype == "phone":
            # 555-0100..555-0199 is the officially reserved fictional range.
            place = self.place(row_state, rng)
            return f"({place['area']}) 555-01{rng.randrange(100):02d}"
        if gtype == "job_title":
            return rng.choice(JOB_TITLES)
        if gtype == "company_name":
            flavor = str(gen.get("flavor", "generic"))
            tails = COMPANY_FLAVORS.get(flavor)
            if tails is None:
                raise SpecError(f"{where}: unknown company flavor '{flavor}'.{suggest(flavor, list(COMPANY_FLAVORS))}")
            chain_pool = int(gen.get("chain_pool", 0))
            if chain_pool:
                # Multi-location chains: a small pool of shared brands, each row a
                # numbered location ("Cedar Point Cantina #3"). Unique by construction.
                pool = self.chain_pools.get(name)
                if pool is None:
                    pool_rng = substream(self.ctx.seed, self.tbl.key, "chainpool", name)
                    brands: list[str] = []
                    seen_brands: set = set()
                    while len(brands) < chain_pool:
                        brand = f"{pool_rng.choice(COMPANY_HEADS)} {pool_rng.choice(tails)}"
                        if brand not in seen_brands:
                            seen_brands.add(brand)
                            brands.append(brand)
                    pool = brands
                    self.chain_pools[name] = pool
                    self.chain_counts[name] = {}
                brand = pool[rng.randrange(len(pool))]
                counts = self.chain_counts[name]
                counts[brand] = counts.get(brand, 0) + 1
                return f"{brand} #{counts[brand]}"
            value = f"{rng.choice(COMPANY_HEADS)} {rng.choice(tails)}"
            if gen.get("unique"):
                seen = self.unique_seen.setdefault(name, set())
                for _ in range(4):
                    if value not in seen:
                        break
                    value = f"{rng.choice(COMPANY_HEADS)} {rng.choice(tails)}"
                if value in seen:
                    # Disambiguate with a city, like real multi-location businesses.
                    value = f"{value} {rng.choice(PLACES)[0]}"
                while value in seen:
                    value = f"{value} {rng.randrange(2, 99)}"
                seen.add(value)
            return value
        if gtype == "addr_street":
            return self.place(row_state, rng)["street"]
        if gtype == "addr_city":
            return self.place(row_state, rng)["city"]
        if gtype == "addr_region":
            return self.place(row_state, rng)["region"]
        if gtype == "addr_postal":
            return self.place(row_state, rng)["postal"]
        if gtype == "addr_full":
            p = self.place(row_state, rng)
            return f"{p['street']}, {p['city']}, {p['region']} {p['postal']}"
        if gtype == "identifier":
            kind = str(gen.get("kind", ""))
            if kind == "luhn":
                prefix = str(gen.get("prefix", "9"))
                return gen_luhn(rng, prefix, int(gen.get("length", 12)))
            factory = IDENTIFIER_KINDS.get(kind)
            if factory is None:
                raise SpecError(f"{where}: unknown identifier kind '{kind}'.{suggest(kind, list(IDENTIFIER_KINDS) + ['luhn'])}")
            return factory(rng)
        if gtype == "text_template":
            templates = gen.get("templates")
            if not templates:
                raise SpecError(f"{where}: text_template requires 'templates'.")
            template = rng.choice(templates)
            return self._fill_template(template, row, rng, where)
        if gtype == "lorem_note":
            pool = str(gen.get("pool", "support_action"))
            words = self.ctx.vocab.get(pool)
            if not words:
                raise SpecError(f"{where}: unknown vocab pool '{pool}'.{suggest(pool, list(self.ctx.vocab))}")
            return " ".join(rng.choice(words) for _ in range(int(gen.get("sentences", 1))))
        if gtype == "staff_user":
            cum = self.ctx.staff_cum
            target = rng.random() * cum[-1]
            return self.ctx.staff[min(bisect.bisect_left(cum, target), len(self.ctx.staff) - 1)]
        if gtype == "table_source_system":
            return self.tbl.source_system or (self.tbl.key.split(".")[0] if "." in self.tbl.key else "core")
        if gtype == "batch_id":
            base_date = row.get("ingested_at") or row.get("created_at")
            day = str(base_date)[:10].replace("-", "") if base_date else "20240101"
            return f"BATCH-{day}-{rng.randrange(1, 5):02d}"
        if gtype == "auto_created_at":
            anchor = gen.get("from") or self._first_date_column(row)
            if anchor is not None and not isinstance(anchor, (dt.date, dt.datetime)):
                anchor = row.get(str(anchor))
            if isinstance(anchor, dt.date) and not isinstance(anchor, dt.datetime):
                return dt.datetime.combine(anchor, cal.sample_time(rng))
            if isinstance(anchor, dt.datetime):
                return anchor
            return cal.sample_timestamp(rng)
        if gtype == "auto_updated_at":
            created = row.get("created_at")
            base = created if isinstance(created, dt.datetime) else cal.sample_timestamp(rng)
            lag_days = sample_number(rng, {"distribution": "lognormal", "median": 3, "sigma": 1.5, "max": 400}, where)
            updated = base + dt.timedelta(days=lag_days * (0 if rng.random() < 0.45 else 1))
            limit = dt.datetime.combine(cal.as_of, dt.time(23, 59, 59))
            # Floor at base so a base near/after as_of can't invert ordering.
            return max(min(updated, limit), base)
        if gtype == "auto_ingested_at":
            src = row.get("source_updated_at") or row.get("created_at")
            base = src if isinstance(src, dt.datetime) else cal.sample_timestamp(rng)
            lag_hours = sample_number(rng, {"distribution": "lognormal", "median": 4, "sigma": 0.8, "max": 96}, where)
            ingested = base + dt.timedelta(hours=lag_hours)
            limit = dt.datetime.combine(cal.as_of, dt.time(23, 59, 59))
            # Clamp like auto_updated_at; the late_arrival injector intentionally
            # (and loggedly) pushes ingestion past as_of afterwards.
            return max(min(ingested, limit), base)
        if gtype == "auto_effective_start":
            anchor = self._first_date_column(row)
            if isinstance(anchor, dt.datetime):
                return anchor.date()
            if isinstance(anchor, dt.date):
                return anchor
            return cal.sample_date(rng)
        raise SpecError(f"{where}: generator '{gtype}' not implemented.")  # pragma: no cover

    def _first_date_column(self, row: dict[str, Any]) -> Any:
        for value in row.values():
            if isinstance(value, (dt.date, dt.datetime)):
                return value
        return None

    def _pattern(self, rng: random.Random, pattern: str, gen: dict[str, Any], name: str, where: str) -> str:
        def render() -> str:
            out = []
            for ch in pattern:
                if ch == "#":
                    out.append(str(rng.randrange(10)))
                elif ch == "@":
                    out.append(rng.choice("ABCDEFGHJKLMNPQRSTUVWXYZ"))
                elif ch == "?":
                    out.append(rng.choice("abcdefghijklmnopqrstuvwxyz"))
                elif ch == "*":
                    out.append(rng.choice("ABCDEFGHJKLMNPQRSTUVWXYZ0123456789"))
                else:
                    out.append(ch)
            return "".join(out)

        if gen.get("unique"):
            seen = self.unique_seen.setdefault(name, set())
            for _ in range(200):
                value = render()
                if value not in seen:
                    seen.add(value)
                    return value
            raise SpecError(f"{where}: could not generate unique pattern value after 200 tries; widen the pattern.")
        return render()

    def _fill_template(self, template: str, row: dict[str, Any], rng: random.Random, where: str) -> str:
        def repl(match: re.Match) -> str:
            token = match.group(1)
            if token.startswith("col."):
                value = row.get(token[4:])
                return "" if value is None else str(value)
            words = self.ctx.vocab.get(token)
            if not words:
                raise SpecError(f"{where}: template token '{{{token}}}' is not a vocab pool or col.<name>.{suggest(token, list(self.ctx.vocab))}")
            return str(rng.choice(words))
        return re.sub(r"\{([A-Za-z0-9_.]+)\}", repl, template)

    def _bound_date(self, bound: Any, row: dict[str, Any], parent: dict[str, Any] | None, where: str) -> dt.date | None:
        if bound is None:
            return None
        text = str(bound)
        if re.match(r"^\d{4}-\d{2}-\d{2}$", text):
            return dt.date.fromisoformat(text)
        value = self._resolve_ref(text, row, parent, where)
        if isinstance(value, str):
            # Parent-cached values arrive ISO-serialized.
            try:
                value = (dt.datetime.fromisoformat(value) if len(value) > 10
                         else dt.date.fromisoformat(value))
            except ValueError:
                raise SpecError(f"{where}: date bound '{bound}' resolved to non-date '{value[:30]}'.")
        if isinstance(value, dt.datetime):
            return value.date()
        if isinstance(value, dt.date):
            return value
        if value is None:
            return None
        raise SpecError(f"{where}: date bound '{bound}' did not resolve to a date.")

    def _resolve_ref(self, ref: str, row: dict[str, Any], parent: dict[str, Any] | None, where: str) -> Any:
        if ref.startswith("parent."):
            if parent is None:
                raise SpecError(f"{where}: '{ref}' used but table has no per_parent parent.")
            return parent.get(ref.split(".", 1)[1])
        if ref in row:
            return row[ref]
        raise SpecError(f"{where}: reference '{ref}' is not an earlier column or parent.<col>.{suggest(ref, list(row))}")

    def _date_offset(self, rng: random.Random, gen: dict[str, Any], row: dict[str, Any],
                     parent: dict[str, Any] | None, where: str) -> Any:
        frm = gen.get("from")
        if not frm:
            raise SpecError(f"{where}: date_offset requires 'from' (earlier column or parent.<col>).")
        base = self._resolve_ref(str(frm), row, parent, where)
        if base is None:
            return None
        if isinstance(base, str):
            base = dt.datetime.fromisoformat(base) if len(base) > 10 else dt.date.fromisoformat(base)
        unit = str(gen.get("unit", "days"))
        amount = sample_number(rng, gen.get("offset", {"distribution": "lognormal", "median": 2, "sigma": 0.7}), where)
        if gen.get("negate"):
            amount = -amount
        delta = dt.timedelta(**{unit: amount}) if unit in {"days", "hours", "minutes"} else dt.timedelta(days=amount)
        if isinstance(base, dt.datetime):
            result: Any = base + delta
        else:
            result = base + dt.timedelta(days=round(delta.total_seconds() / 86400))
        if gen.get("business_days") and isinstance(result, (dt.date, dt.datetime)):
            while (result.weekday() if isinstance(result, dt.date) else result.date().weekday()) >= 5:
                result += dt.timedelta(days=1)
        if gen.get("clamp_as_of", True) and not gen.get("negate"):
            limit_d = self.ctx.calendar.as_of
            if isinstance(result, dt.datetime):
                clamped = min(result, dt.datetime.combine(limit_d, dt.time(23, 59, 59)))
                base_dt = base if isinstance(base, dt.datetime) else dt.datetime.combine(base, dt.time(0, 0))
                result = max(clamped, base_dt)
            elif isinstance(result, dt.date):
                base_d = base.date() if isinstance(base, dt.datetime) else base
                result = max(min(result, limit_d), base_d)
        if str(gen.get("as", "")) == "date" and isinstance(result, dt.datetime):
            return result.date()
        return result

    # -- Row loop -------------------------------------------------------------

    def default_gen(self, col: dict[str, Any]) -> dict[str, Any]:
        ctype = str(col.get("type", "string")).lower()
        defaults = {
            "integer": {"type": "int", "distribution": "uniform", "min": 0, "max": 100},
            "bigint": {"type": "int", "distribution": "uniform", "min": 0, "max": 100000},
            "decimal": {"type": "money", "median": 100, "sigma": 1.0},
            "number": {"type": "number", "distribution": "uniform", "min": 0, "max": 1000, "decimals": 2},
            "float": {"type": "number", "distribution": "uniform", "min": 0, "max": 1000, "decimals": 4},
            "boolean": {"type": "boolean", "p_true": 0.5},
            "date": {"type": "date"},
            "timestamp": {"type": "timestamp"},
        }
        return defaults.get(ctype, {"type": "pattern", "pattern": "VAL-#####"})

    def _prepare_sorted_pools(self, total: int) -> None:
        """Pre-sample and sort values for date/timestamp columns marked sorted:true,
        so sequence IDs correlate with creation dates the way real systems do."""
        for col in self.tbl.columns:
            gen = col.get("gen") or {}
            if not gen.get("sorted"):
                continue
            if gen.get("type") not in {"date", "timestamp"}:
                raise SpecError(f"{self.tbl.where} ({self.tbl.key}).columns[{col['name']}]: "
                                "'sorted' is only supported on date/timestamp generators.")
            rng = self.rng_for(f"col:{col['name']}")
            cal = self.ctx.calendar
            is_date = gen["type"] == "date"
            # backfill_share puts that fraction of entities BEFORE the data window
            # (tenured customers/products), so in-window activity doesn't ramp from zero.
            n_back = 0
            values: list[Any] = []
            if gen.get("backfill_start"):
                share = float(gen.get("backfill_share", 0.5))
                n_back = int(round(total * share))
                back_start = parse_date(gen["backfill_start"],
                                        f"{self.tbl.where} ({self.tbl.key}).columns[{col['name']}].backfill_start")
                span_days = (cal.start - back_start).days
                if span_days <= 0:
                    raise SpecError(f"{self.tbl.where} ({self.tbl.key}).columns[{col['name']}]: "
                                    "backfill_start must be before time.start_date.")
                for _ in range(n_back):
                    day = back_start + dt.timedelta(days=rng.randrange(span_days))
                    values.append(day if is_date else dt.datetime.combine(day, cal.sample_time(rng)))
            for _ in range(total - n_back):
                if is_date:
                    values.append(cal.sample_date(rng))
                else:
                    values.append(cal.sample_timestamp(rng, business_hours=gen.get("business_hours", True)))
            values.sort()
            self.sorted_pools[col["name"]] = values

    def rows(self, multiplier: float) -> Iterator[dict[str, Any]]:
        parent_ref = per_parent_ref(self.tbl.rows_cfg)
        null_rng = self.rng_for("__nulls__")
        if parent_ref:
            if any((c.get("gen") or {}).get("sorted") for c in self.tbl.columns):
                raise SpecError(f"{self.tbl.where} ({self.tbl.key}): 'sorted' generators are not "
                                "supported on per_parent tables (row count unknown upfront).")
            cache = self.ctx.cache.get(parent_ref)
            if cache is None:
                raise SpecError(f"{self.tbl.where} ({self.tbl.key}): per_parent ref '{parent_ref}' not generated before this table.")
            dist = self.tbl.rows_cfg.get("distribution", {"distribution": "lognormal", "median": 3, "sigma": 0.8})
            count_rng = self.rng_for("__rows__")
            # scale_by: parent-attribute volume conditioning (enterprise customers
            # order more); per_parent_multiplier: heavy-tailed per-parent activity
            # weight so a whale tier emerges.
            scale_by = self.tbl.rows_cfg.get("scale_by")
            mult_cfg = self.tbl.rows_cfg.get("per_parent_multiplier")
            mult_rng = self.rng_for("__parent_mult__")
            row_index = 0
            # Parent count already scales with the multiplier, so per-parent child
            # counts must NOT be scaled again (that would scale children quadratically).
            for pk in cache["pks"]:
                parent_row = dict(cache.get("rows", {}).get(pk, {}))
                parent_row["__pk__"] = pk
                n = sample_number(count_rng, dist, f"{self.tbl.where}.rows.distribution")
                if scale_by:
                    parent_value = str(parent_row.get(scale_by.get("parent_column")))
                    factor = scale_by.get("factors", {}).get(parent_value, scale_by.get("default", 1.0))
                    n *= float(factor)
                if mult_cfg:
                    n *= sample_number(mult_rng, mult_cfg, f"{self.tbl.where}.rows.per_parent_multiplier")
                n = int(round(n))
                n = max(int(self.tbl.rows_cfg.get("min", 0)), min(n, int(self.tbl.rows_cfg.get("max", 10 ** 9))))
                for child_idx in range(n):
                    yield self._build_row(row_index, parent_row, child_idx, null_rng)
                    row_index += 1
        else:
            total = resolve_row_count(self.tbl.rows_cfg, multiplier, self.tbl.scale_exempt,
                                      f"{self.tbl.where} ({self.tbl.key}).rows")
            self._prepare_sorted_pools(total)
            for row_index in range(total):
                yield self._build_row(row_index, None, 0, null_rng)

    def _build_row(self, row_index: int, parent: dict[str, Any] | None,
                   child_index: int, null_rng: random.Random) -> dict[str, Any]:
        row: dict[str, Any] = {}
        row_state: dict[str, Any] = {}
        for col in self.tbl.columns:
            gen = col.get("gen") or self.default_gen(col)
            try:
                value = self.generate_value(col, gen, row, row_state, row_index, parent, child_index)
            except SpecError:
                raise
            except Exception as exc:
                raise SpecError(f"{self.tbl.where} ({self.tbl.key}).columns[{col['name']}] "
                                f"failed at row {row_index}: {type(exc).__name__}: {exc}")
            null_rate = float(col.get("null_rate", 0))
            if null_rate and value is not None and null_rng.random() < null_rate:
                value = None
            row[col["name"]] = value
        if self.track_own_pks and self.tbl.primary_key:
            self.own_pks.append(row.get(self.tbl.primary_key[0]))
        return row


# ---------------------------------------------------------------------------
# SCD2 history expansion
# ---------------------------------------------------------------------------


def expand_scd2(tbl: TableSpec, rows: list[dict[str, Any]], ctx: GenerationContext) -> list[dict[str, Any]]:
    cfg = tbl.history or {}
    if str(cfg.get("strategy", "")).lower() != "scd2":
        return rows
    change_rate = float(cfg.get("change_rate", 0.25))
    max_versions = int(cfg.get("max_versions", 3))
    track = cfg.get("track", [])
    pk_cols = tbl.primary_key
    if len(pk_cols) != 1:
        raise SpecError(f"{tbl.where} ({tbl.key}): scd2 history requires a single-column primary key.")
    pk_col = pk_cols[0]
    rng = substream(ctx.seed, tbl.key, "__scd2__")
    gen = TableGenerator(tbl, ctx)
    out: list[dict[str, Any]] = []
    version_seq = 0
    for row in rows:
        versions = 1
        if rng.random() < change_rate:
            versions = rng.randint(2, max(2, max_versions))
        start = row.get("effective_start_date")
        if not isinstance(start, dt.date):
            start = ctx.calendar.sample_date(rng)
        spans = sorted(rng.randint(30, 600) for _ in range(versions - 1))
        prev_start = start
        history_rows = []
        for v in range(versions - 1):
            hist = dict(row)
            version_seq += 1
            hist[pk_col] = f"{row[pk_col]}-H{version_seq}" if isinstance(row[pk_col], str) else -(version_seq + 10 ** 7)
            end = max(min(prev_start + dt.timedelta(days=spans[v]), ctx.calendar.as_of), prev_start)
            hist["effective_start_date"] = prev_start
            hist["effective_end_date"] = end
            hist["current_flag"] = 0
            for tcol in track:
                col_spec = next((c for c in tbl.columns if c["name"] == tcol), None)
                if col_spec is not None:
                    g = col_spec.get("gen") or gen.default_gen(col_spec)
                    hist[tcol] = gen.generate_value(col_spec, g, dict(hist), {}, version_seq, None, 0)
            history_rows.append(hist)
            prev_start = end
        current = dict(row)
        current["effective_start_date"] = prev_start
        current["effective_end_date"] = None
        current["current_flag"] = 1
        out.extend(history_rows)
        out.append(current)
    return out


# ---------------------------------------------------------------------------
# State machines
# ---------------------------------------------------------------------------


class StateMachine:
    def __init__(self, raw: dict[str, Any], index: int, tables: dict[str, TableSpec]):
        self.where = f"state_machines[{index}]"
        self.name = raw.get("name", f"machine_{index}")
        self.table = str(raw.get("table", ""))
        if self.table not in tables:
            raise SpecError(f"{self.where}: table '{self.table}' not found.{suggest(self.table, list(tables))}")
        self.status_column = raw.get("status_column", "status")
        self.start_column = raw.get("start_column")
        if not self.start_column:
            raise SpecError(f"{self.where}: 'start_column' (timestamp/date anchor column) is required.")
        self.entry_state = raw.get("entry_state")
        self.states = list(raw.get("states", []))
        if not self.entry_state or self.entry_state not in self.states:
            raise SpecError(f"{self.where}: entry_state must be one of states.")
        self.timestamp_columns = raw.get("timestamp_columns", {})
        self.history_table = raw.get("history_table")
        self.truncate_at_as_of = bool(raw.get("truncate_at_as_of", True))
        self.transitions: dict[str, list[dict[str, Any]]] = {}
        self.notes: list[str] = []
        for ti, tr in enumerate(raw.get("transitions", [])):
            src, dst = tr.get("from"), tr.get("to")
            if src not in self.states:
                raise SpecError(f"{self.where}.transitions[{ti}]: from '{src}' is not a declared state."
                                f"{suggest(str(src), self.states)}")
            if dst not in self.states:
                raise SpecError(f"{self.where}.transitions[{ti}]: to '{dst}' is not a declared state."
                                f"{suggest(str(dst), self.states)}")
            self.transitions.setdefault(src, []).append(dict(tr))
        for src, trs in self.transitions.items():
            total = sum(float(t.get("probability", 1)) for t in trs)
            if total > 1.0001:
                # Auto-normalize so a 0.85/0.20 typo doesn't fail the build;
                # residual probability below 1.0 still means "stay in state".
                for t in trs:
                    t["probability"] = float(t.get("probability", 1)) / total
                self.notes.append(f"probabilities from '{src}' summed to {total:.3f}; normalized to 1.0")

        table_cols = tables[self.table].column_names
        if self.status_column not in table_cols:
            raise SpecError(f"{self.where}: status_column '{self.status_column}' not a column of {self.table}.")
        if self.start_column not in table_cols:
            raise SpecError(f"{self.where}: start_column '{self.start_column}' not a column of {self.table}."
                            f"{suggest(str(self.start_column), table_cols)}")
        for state, colname in self.timestamp_columns.items():
            if state not in self.states:
                raise SpecError(f"{self.where}: timestamp_columns key '{state}' is not a declared state.")
            if colname not in table_cols:
                raise SpecError(f"{self.where}: timestamp_columns['{state}'] -> '{colname}' not a column of {self.table}.")

    def dwell_delta(self, rng: random.Random, tr: dict[str, Any], cal: BusinessCalendar) -> dt.timedelta:
        dwell = tr.get("dwell", {"distribution": "lognormal", "median": 24, "sigma": 0.8})
        unit = str(dwell.get("unit", "hours"))
        amount = sample_number(rng, dwell, f"{self.where}.dwell")
        if unit == "business_days":
            return dt.timedelta(days=amount * 7 / 5)
        if unit == "days":
            return dt.timedelta(days=amount)
        if unit == "minutes":
            return dt.timedelta(minutes=amount)
        return dt.timedelta(hours=amount)

    def run(self, rng: random.Random, start: dt.datetime, cal: BusinessCalendar
            ) -> tuple[str, list[tuple[str, dt.datetime]]]:
        """Walk the machine. Returns (final_state, [(state, entered_at), ...])."""
        as_of_dt = dt.datetime.combine(cal.as_of, dt.time(23, 59, 59))
        state = self.entry_state
        t = start
        path = [(state, t)]
        for _ in range(60):  # hard stop against accidental loops
            options = self.transitions.get(state, [])
            if not options:
                break
            roll = rng.random()
            acc = 0.0
            chosen = None
            for tr in options:
                acc += float(tr.get("probability", 1))
                if roll <= acc:
                    chosen = tr
                    break
            if chosen is None:
                break  # residual probability: entity stays in current state
            t = t + self.dwell_delta(rng, chosen, cal)
            if self.truncate_at_as_of and t > as_of_dt:
                break  # still mid-flight as of the reporting date
            state = str(chosen["to"])
            path.append((state, t))
        return state, path


def apply_state_machines(conn: sqlite3.Connection, spec: dict[str, Any],
                         tables: dict[str, TableSpec], ctx: GenerationContext,
                         log: Callable[[str], None]) -> dict[str, int]:
    history_counts: dict[str, int] = {}
    machines = [StateMachine(raw, i, tables) for i, raw in enumerate(spec.get("state_machines", []))]
    for machine in machines:
        for note in machine.notes:
            log(f"  note: state machine {machine.name}: {note}")
        tbl = tables[machine.table]
        if len(tbl.primary_key) != 1:
            raise SpecError(f"{machine.where}: state machine table {machine.table} needs a single-column primary key.")
        pk = tbl.primary_key[0]
        rng = substream(ctx.seed, "machine", machine.name)
        cur = conn.execute(
            f'select "{pk}", "{machine.start_column}" from "{tbl.physical}" order by rowid'
        )
        updates = []
        history_rows = []
        for entity_pk, start_raw in cur.fetchall():
            if start_raw is None:
                continue
            text = str(start_raw)
            start = (dt.datetime.fromisoformat(text) if len(text) > 10
                     else dt.datetime.combine(dt.date.fromisoformat(text), ctx.calendar.sample_time(rng)))
            final_state, path = machine.run(rng, start, ctx.calendar)
            stamp_values = {}
            for state, entered in path:
                colname = machine.timestamp_columns.get(state)
                if colname:
                    stamp_values[colname] = iso(entered)
            updates.append((final_state, stamp_values, entity_pk))
            if machine.history_table:
                for seq, (state, entered) in enumerate(path, start=1):
                    history_rows.append((entity_pk, seq, state, iso(entered)))

        stamp_cols = sorted({c for _, stamps, _ in updates for c in stamps})
        set_clause = ", ".join([f'"{machine.status_column}" = ?'] + [f'"{c}" = ?' for c in stamp_cols])
        sql = f'update "{tbl.physical}" set {set_clause} where "{pk}" = ?'
        conn.executemany(sql, [
            tuple([final] + [stamps.get(c) for c in stamp_cols] + [entity_pk])
            for final, stamps, entity_pk in updates
        ])

        if machine.history_table:
            hkey = str(machine.history_table)
            if hkey not in tables:
                raise SpecError(f"{machine.where}: history_table '{hkey}' not declared in tables.")
            htbl = tables[hkey]
            hcols = htbl.column_names
            if len(hcols) < 4:
                raise SpecError(f"{machine.where}: history table {hkey} needs >= 4 columns "
                                "(entity pk, sequence, state, entered_at as its first four).")
            placeholders = ", ".join("?" for _ in range(4))
            conn.executemany(
                f'insert into "{htbl.physical}" ("{hcols[0]}", "{hcols[1]}", "{hcols[2]}", "{hcols[3]}") '
                f'values ({placeholders})',
                history_rows,
            )
            history_counts[hkey] = len(history_rows)
        log(f"  state machine {machine.name}: {len(updates)} entities walked"
            + (f", {len(history_rows)} history events" if machine.history_table else ""))
    return history_counts


# ---------------------------------------------------------------------------
# Imperfection injectors — every injected defect is logged
# ---------------------------------------------------------------------------

IMPERFECTION_TYPES = [
    "missing_xref", "orphan_fk", "duplicate_entity", "late_arrival",
    "conflicting_source_values", "format_drift", "typo", "restatement_reversal",
    "out_of_order_events", "duplicate_webhook", "stale_mapping",
    "manual_override", "null_field",
]


def _sample_pks(conn: sqlite3.Connection, physical: str, pk: str, rate: float,
                rng: random.Random, where_sql: str = "") -> list[Any]:
    rows = [r[0] for r in conn.execute(f'select "{pk}" from "{physical}" {where_sql} order by "{pk}"')]
    count = int(round(len(rows) * rate))
    if count <= 0 or not rows:
        return []
    return rng.sample(rows, min(count, len(rows)))


def _typo(rng: random.Random, text: str) -> str:
    if not text or len(text) < 3:
        return text
    # Digit-bearing values (phones, identifiers) only get case/whitespace noise:
    # mutating digits could push safe fictional values (555-01xx phones, test
    # ranges) into real-looking ones.
    if any(ch.isdigit() for ch in text):
        return text.upper() if rng.random() < 0.4 else " " + text + " "
    mode = rng.randrange(4)
    pos = rng.randrange(1, len(text) - 1)
    if mode == 0:  # swap
        return text[:pos] + text[pos + 1] + text[pos] + text[pos + 2:]
    if mode == 1:  # drop
        return text[:pos] + text[pos + 1:]
    if mode == 2:  # double
        return text[:pos] + text[pos] + text[pos:]
    return text.upper() if rng.random() < 0.5 else "  " + text


def apply_imperfections(conn: sqlite3.Connection, spec: dict[str, Any],
                        tables: dict[str, TableSpec], ctx: GenerationContext,
                        stage: str, log: Callable[[str], None]) -> int:
    total_logged = 0
    for idx, imp in enumerate(spec.get("imperfections", [])):
        where = f"imperfections[{idx}]"
        imp_stage = str(imp.get("stage", "pre_derivation"))
        if imp_stage != stage:
            continue
        itype = str(imp.get("type", ""))
        if itype not in IMPERFECTION_TYPES:
            raise SpecError(f"{where}: unknown type '{itype}'.{suggest(itype, IMPERFECTION_TYPES)}")
        tkey = str(imp.get("table", ""))
        if tkey not in tables:
            raise SpecError(f"{where}: table '{tkey}' not found.{suggest(tkey, list(tables))}")
        tbl = tables[tkey]
        if not tbl.primary_key:
            raise SpecError(f"{where}: table '{tkey}' needs a primary_key for imperfection targeting.")
        if len(tbl.primary_key) != 1 and itype != "out_of_order_events":
            raise SpecError(f"{where}: table '{tkey}' has a composite primary key "
                            f"({', '.join(tbl.primary_key)}); imperfections other than "
                            "out_of_order_events require a single-column primary key — "
                            "targeting by the first component would silently hit whole groups.")
        pk = tbl.primary_key[0]
        rate = float(imp.get("rate", 0.01))
        if rate > 0.5:
            raise SpecError(f"{where}: rate {rate} > 0.5 — rates are fractions, not percents "
                            f"(did you mean {rate / 100:.4f}?).")
        name = imp.get("name", f"{itype}_{idx}")
        params = imp.get("params", {})
        rng = substream(ctx.seed, "imperfection", name)
        entries: list[tuple[str, str, str, str, str]] = []

        def log_entry(pk_value: Any, detail: str) -> None:
            entries.append((name, itype, tbl.physical, str(pk_value), detail))

        def synth_pk_counter(base: int) -> list[int]:
            """Collision-free synthetic integer PK allocator: sequential from
            max(existing) within the branch's reserved range. Random draws from a
            small range birthday-collide and crash the build at scale."""
            current = conn.execute(
                f'select coalesce(max("{pk}"), 0) from "{tbl.physical}" '
                f'where "{pk}" >= ? and "{pk}" < ?', (base, base + 10 ** 7)).fetchone()[0]
            return [max(base, int(current) + 1)]

        if itype == "null_field":
            column = params.get("column")
            if column not in tbl.column_names:
                raise SpecError(f"{where}: params.column '{column}' not in {tkey}.")
            for pk_value in _sample_pks(conn, tbl.physical, pk, rate, rng):
                conn.execute(f'update "{tbl.physical}" set "{column}" = null where "{pk}" = ?', (pk_value,))
                log_entry(pk_value, f"nulled {column}")

        elif itype == "late_arrival":
            column = params.get("column", "ingested_at")
            if column not in tbl.column_names:
                raise SpecError(f"{where}: params.column '{column}' not in {tkey}.")
            lag_cfg = params.get("lag_days", {"distribution": "lognormal", "median": 3, "sigma": 0.8})
            for pk_value in _sample_pks(conn, tbl.physical, pk, rate, rng):
                lag = sample_number(rng, lag_cfg, where)
                conn.execute(
                    f'update "{tbl.physical}" set "{column}" = datetime("{column}", ?) where "{pk}" = ?',
                    (f"+{lag:.2f} days", pk_value))
                log_entry(pk_value, f"{column} delayed {lag:.1f} days")

        elif itype == "orphan_fk":
            column = params.get("column")
            if column not in tbl.column_names:
                raise SpecError(f"{where}: params.column '{column}' not in {tkey}.")
            for pk_value in _sample_pks(conn, tbl.physical, pk, rate, rng, f'where "{column}" is not null'):
                ghost = 90000000 + rng.randrange(1000000)
                conn.execute(f'update "{tbl.physical}" set "{column}" = ? where "{pk}" = ?', (ghost, pk_value))
                log_entry(pk_value, f"{column} -> ghost {ghost}")

        elif itype == "missing_xref":
            for pk_value in _sample_pks(conn, tbl.physical, pk, rate, rng):
                conn.execute(f'delete from "{tbl.physical}" where "{pk}" = ?', (pk_value,))
                log_entry(pk_value, "xref row deleted (unmapped identifier)")

        elif itype == "duplicate_entity":
            fuzz_columns = params.get("fuzz_columns", [])
            cols = tbl.column_names
            counter = synth_pk_counter(80000000)
            for pk_value in _sample_pks(conn, tbl.physical, pk, rate, rng):
                row = conn.execute(f'select * from "{tbl.physical}" where "{pk}" = ?', (pk_value,)).fetchone()
                if row is None:
                    continue
                values = dict(zip(cols, row))
                old_pk = values[pk]
                if isinstance(old_pk, str):
                    values[pk] = f"{old_pk}-DUP{counter[0]}"
                else:
                    values[pk] = counter[0]
                counter[0] += 1
                for fc in fuzz_columns:
                    if isinstance(values.get(fc), str):
                        values[fc] = _typo(rng, values[fc])
                placeholders = ", ".join("?" for _ in cols)
                collist = ", ".join(f'"{c}"' for c in cols)
                conn.execute(f'insert into "{tbl.physical}" ({collist}) values ({placeholders})',
                             tuple(values[c] for c in cols))
                log_entry(values[pk], f"duplicate of {old_pk}")

        elif itype == "conflicting_source_values":
            column = params.get("column")
            if column not in tbl.column_names:
                raise SpecError(f"{where}: params.column '{column}' not in {tkey}.")
            variants = params.get("variants")
            for pk_value in _sample_pks(conn, tbl.physical, pk, rate, rng):
                if variants:
                    new_value = rng.choice(variants)
                    conn.execute(f'update "{tbl.physical}" set "{column}" = ? where "{pk}" = ?', (new_value, pk_value))
                    log_entry(pk_value, f"{column} -> conflicting '{new_value}'")
                else:
                    old = conn.execute(f'select "{column}" from "{tbl.physical}" where "{pk}" = ?', (pk_value,)).fetchone()
                    if old and isinstance(old[0], str):
                        conn.execute(f'update "{tbl.physical}" set "{column}" = ? where "{pk}" = ?',
                                     (_typo(rng, old[0]), pk_value))
                        log_entry(pk_value, f"{column} mutated vs source")

        elif itype == "format_drift":
            column = params.get("column")
            fmt = str(params.get("format", "us_date"))
            if column not in tbl.column_names:
                raise SpecError(f"{where}: params.column '{column}' not in {tkey}.")
            for pk_value in _sample_pks(conn, tbl.physical, pk, rate, rng):
                old = conn.execute(f'select "{column}" from "{tbl.physical}" where "{pk}" = ?', (pk_value,)).fetchone()
                if not old or old[0] is None:
                    continue
                text = str(old[0])
                if fmt == "us_date" and re.match(r"^\d{4}-\d{2}-\d{2}", text):
                    new_value = f"{text[5:7]}/{text[8:10]}/{text[0:4]}"
                elif fmt == "uppercase":
                    new_value = text.upper()
                elif fmt == "padded":
                    new_value = text.zfill(len(text) + 3)
                else:
                    new_value = " " + text + " "
                conn.execute(f'update "{tbl.physical}" set "{column}" = ? where "{pk}" = ?', (new_value, pk_value))
                log_entry(pk_value, f"{column} format drift ({fmt})")

        elif itype == "typo":
            column = params.get("column")
            if column not in tbl.column_names:
                raise SpecError(f"{where}: params.column '{column}' not in {tkey}.")
            for pk_value in _sample_pks(conn, tbl.physical, pk, rate, rng, f'where "{column}" is not null'):
                old = conn.execute(f'select "{column}" from "{tbl.physical}" where "{pk}" = ?', (pk_value,)).fetchone()
                if old and isinstance(old[0], str):
                    conn.execute(f'update "{tbl.physical}" set "{column}" = ? where "{pk}" = ?',
                                 (_typo(rng, old[0]), pk_value))
                    log_entry(pk_value, f"typo in {column}")

        elif itype == "restatement_reversal":
            amount_columns = params.get("amount_columns", [])
            reason_column = params.get("reason_column")
            cols = tbl.column_names
            counters = {"-REV": synth_pk_counter(70000000), "-RST": synth_pk_counter(75000000)}
            for pk_value in _sample_pks(conn, tbl.physical, pk, rate, rng):
                row = conn.execute(f'select * from "{tbl.physical}" where "{pk}" = ?', (pk_value,)).fetchone()
                if row is None:
                    continue
                values = dict(zip(cols, row))
                base_pk = values[pk]
                for suffix, sign, reason in (("-REV", -1, "reversal"), ("-RST", 1, "restated")):
                    copy = dict(values)
                    counter = counters[suffix]
                    if isinstance(base_pk, str):
                        copy[pk] = f"{base_pk}{suffix}{counter[0]}"
                    else:
                        copy[pk] = counter[0]
                    counter[0] += 1
                    for ac in amount_columns:
                        if isinstance(copy.get(ac), (int, float)) and copy[ac] is not None:
                            adj = sign * copy[ac] if sign < 0 else copy[ac] * rng.uniform(0.95, 1.05)
                            copy[ac] = round(adj, 2)
                    if reason_column and reason_column in cols:
                        copy[reason_column] = reason
                    placeholders = ", ".join("?" for _ in cols)
                    collist = ", ".join(f'"{c}"' for c in cols)
                    conn.execute(f'insert into "{tbl.physical}" ({collist}) values ({placeholders})',
                                 tuple(copy[c] for c in cols))
                    log_entry(copy[pk], f"{reason} of {base_pk}")

        elif itype == "out_of_order_events":
            seq_column = params.get("sequence_column")
            group_column = params.get("group_column")
            if seq_column not in tbl.column_names or group_column not in tbl.column_names:
                raise SpecError(f"{where}: needs params.sequence_column and params.group_column present in {tkey}.")
            groups = [r[0] for r in conn.execute(
                f'select distinct "{group_column}" from "{tbl.physical}" order by 1')]
            chosen = rng.sample(groups, min(int(round(len(groups) * rate)), len(groups))) if groups else []
            for group in chosen:
                # rowid targeting (composite-PK safe) and a NULL-sentinel swap:
                # SQLite checks unique/PK constraints per-row, so a direct two-step
                # swap of constrained sequence values would fail mid-flight.
                rows = conn.execute(
                    f'select rowid, "{seq_column}" from "{tbl.physical}" where "{group_column}" = ? '
                    f'order by "{seq_column}"', (group,)).fetchall()
                if len(rows) < 2:
                    continue
                i = rng.randrange(len(rows) - 1)
                (rid_a, seq_a), (rid_b, seq_b) = rows[i], rows[i + 1]
                conn.execute(f'update "{tbl.physical}" set "{seq_column}" = null where rowid = ?', (rid_a,))
                conn.execute(f'update "{tbl.physical}" set "{seq_column}" = ? where rowid = ?', (seq_a, rid_b))
                conn.execute(f'update "{tbl.physical}" set "{seq_column}" = ? where rowid = ?', (seq_b, rid_a))
                log_entry(group, f"{seq_column} {seq_a}/{seq_b} swapped within group")

        elif itype == "duplicate_webhook":
            cols = tbl.column_names
            counter = synth_pk_counter(85000000)
            for pk_value in _sample_pks(conn, tbl.physical, pk, rate, rng):
                row = conn.execute(f'select * from "{tbl.physical}" where "{pk}" = ?', (pk_value,)).fetchone()
                if row is None:
                    continue
                values = dict(zip(cols, row))
                old_pk = values[pk]
                if isinstance(old_pk, str):
                    values[pk] = f"{old_pk}-RETRY{counter[0]}"
                else:
                    values[pk] = counter[0]
                counter[0] += 1
                placeholders = ", ".join("?" for _ in cols)
                collist = ", ".join(f'"{c}"' for c in cols)
                conn.execute(f'insert into "{tbl.physical}" ({collist}) values ({placeholders})',
                             tuple(values[c] for c in cols))
                log_entry(values[pk], f"duplicate delivery of {old_pk}")

        elif itype == "stale_mapping":
            column = params.get("column", "valid_to")
            if column not in tbl.column_names:
                raise SpecError(f"{where}: params.column '{column}' not in {tkey}.")
            for pk_value in _sample_pks(conn, tbl.physical, pk, rate, rng):
                stale_date = (ctx.calendar.as_of - dt.timedelta(days=rng.randrange(90, 700))).isoformat()
                conn.execute(f'update "{tbl.physical}" set "{column}" = ? where "{pk}" = ?', (stale_date, pk_value))
                log_entry(pk_value, f"mapping expired {stale_date} but still referenced")

        elif itype == "manual_override":
            column = params.get("column")
            value = params.get("value", 1)
            note_column = params.get("note_column")
            if column not in tbl.column_names:
                raise SpecError(f"{where}: params.column '{column}' not in {tkey}.")
            note_rng = substream(ctx.seed, "imperfection", name, "note")
            for pk_value in _sample_pks(conn, tbl.physical, pk, rate, rng):
                conn.execute(f'update "{tbl.physical}" set "{column}" = ? where "{pk}" = ?', (value, pk_value))
                if note_column and note_column in tbl.column_names:
                    note = note_rng.choice(ctx.vocab["audit_comment"])
                    conn.execute(f'update "{tbl.physical}" set "{note_column}" = ? where "{pk}" = ?', (note, pk_value))
                log_entry(pk_value, f"manual override on {column}")

        if entries:
            conn.executemany(
                "insert into meta_imperfection_log (imperfection_name, imperfection_type, table_name, pk_value, detail) "
                "values (?, ?, ?, ?, ?)", entries)
            total_logged += len(entries)
            log(f"  imperfection {name} ({itype}) on {tkey}: {len(entries)} rows")
    return total_logged


# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

META_DDL = """
create table if not exists meta_build_info (
  key text primary key,
  value text
);
create table if not exists meta_imperfection_log (
  log_id integer primary key autoincrement,
  imperfection_name text not null,
  imperfection_type text not null,
  table_name text not null,
  pk_value text,
  detail text
);
create table if not exists meta_table_stats (
  table_name text primary key,
  layer text,
  row_count integer,
  generated_by text
);
create table if not exists meta_derivation_stats (
  derivation_name text not null,
  statement_index integer not null,
  statement_kind text,
  rows_affected integer,
  primary key (derivation_name, statement_index)
);
"""


# ---------------------------------------------------------------------------
# Derivation execution helpers
# ---------------------------------------------------------------------------


def rewrite_logical_names(sql: str, mapping: dict[str, str]) -> str:
    """Replace logical 'schema.table' references with physical SQLite names so
    derivation SQL can be authored against the spec's logical model."""
    if not mapping:
        return sql
    pattern = re.compile(
        r"\b(" + "|".join(re.escape(k) for k in sorted(mapping, key=len, reverse=True) if "." in k) + r")\b")
    if pattern.pattern == r"\b()\b":
        return sql
    return pattern.sub(lambda m: mapping[m.group(1)], sql)


def split_statements(sql: str) -> list[str]:
    """Split a SQL string into complete statements using sqlite3.complete_statement."""
    statements: list[str] = []
    buffer = ""
    for line in sql.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            cleaned = buffer.strip()
            if cleaned and cleaned != ";":
                statements.append(cleaned)
            buffer = ""
    cleaned = buffer.strip()
    if cleaned:
        statements.append(cleaned if cleaned.endswith(";") else cleaned + ";")
    return statements


def derivation_authorizer(action: int, arg1: Any, arg2: Any, dbname: Any, source: Any) -> int:
    """Confine LLM-authored derivation SQL: no ATTACH/DETACH/PRAGMA and no
    writes to meta_* or sqlite_* tables."""
    deny = getattr(sqlite3, "SQLITE_DENY", 1)
    ok = getattr(sqlite3, "SQLITE_OK", 0)
    attach = getattr(sqlite3, "SQLITE_ATTACH", 24)
    detach = getattr(sqlite3, "SQLITE_DETACH", 25)
    pragma = getattr(sqlite3, "SQLITE_PRAGMA", 19)
    if action in (attach, detach, pragma):
        return deny
    write_actions = {getattr(sqlite3, name, -1) for name in (
        "SQLITE_INSERT", "SQLITE_UPDATE", "SQLITE_DELETE", "SQLITE_DROP_TABLE",
        "SQLITE_DROP_VIEW", "SQLITE_DROP_INDEX", "SQLITE_ALTER_TABLE")}
    # Note: CREATE VIEW/TABLE legitimately writes to sqlite_master, so only the
    # engine's meta_ tables are protected from derivation SQL.
    if action in write_actions and isinstance(arg1, str) and arg1.startswith("meta_"):
        return deny
    return ok


def allow_all_authorizer(action: int, arg1: Any, arg2: Any, dbname: Any, source: Any) -> int:
    return getattr(sqlite3, "SQLITE_OK", 0)


def clear_derivation_authorizer(conn: sqlite3.Connection) -> None:
    try:
        conn.set_authorizer(None)
    except TypeError:
        pass
    # Python/SQLite combinations differ in how reliably None disables an
    # authorizer. A permissive callback keeps post-derivation PRAGMAs portable.
    conn.set_authorizer(allow_all_authorizer)


def render_table_ddl(tbl: TableSpec, tables: dict[str, TableSpec]) -> str:
    lines = []
    for col in tbl.columns:
        ctype = SQLITE_TYPES.get(str(col.get("type", "string")).lower(), "text")
        notnull = " not null" if col.get("nullable") is False else ""
        lines.append(f'  "{col["name"]}" {ctype}{notnull}')
    if tbl.primary_key:
        pk_cols = ", ".join(f'"{c}"' for c in tbl.primary_key)
        lines.append(f"  primary key ({pk_cols})")
    for colname, ref in tbl.fk_refs():
        ref_tbl = tables.get(ref)
        if ref_tbl is not None and ref_tbl.primary_key:
            lines.append(f'  foreign key ("{colname}") references "{ref_tbl.physical}" ("{ref_tbl.primary_key[0]}")')
    comment = f"-- {tbl.key}: {tbl.purpose}" + (f" Grain: {tbl.grain}." if tbl.grain else "")
    return f'{comment}\ncreate table "{tbl.physical}" (\n' + ",\n".join(lines) + "\n);"


def render_indexes(tbl: TableSpec) -> list[str]:
    stmts = []
    for i, index in enumerate(tbl.indexes):
        cols = index if isinstance(index, list) else [index]
        collist = ", ".join(f'"{c}"' for c in cols)
        idx_name = f"ix_{tbl.physical}_{'_'.join(cols)}"[:60]
        stmts.append(f'create index if not exists "{idx_name}" on "{tbl.physical}" ({collist});')
    for colname, _ in tbl.fk_refs():
        idx_name = f"ix_{tbl.physical}_{colname}"[:60]
        stmts.append(f'create index if not exists "{idx_name}" on "{tbl.physical}" ("{colname}");')
    return sorted(set(stmts))


# ---------------------------------------------------------------------------
# Topological ordering
# ---------------------------------------------------------------------------


def generation_order(tables: list[TableSpec]) -> list[TableSpec]:
    by_key = {t.key: t for t in tables}
    gen_tables = [t for t in tables if t.source == "generator"]
    deps: dict[str, set] = {t.key: set() for t in gen_tables}
    for t in gen_tables:
        for _, ref in t.fk_refs():
            if ref in deps and ref != t.key:
                deps[t.key].add(ref)
        parent = per_parent_ref(t.rows_cfg)
        if parent:
            if parent not in by_key:
                raise SpecError(f"{t.where} ({t.key}): per_parent ref '{parent}' not in tables.{suggest(parent, list(by_key))}")
            if parent in deps:
                deps[t.key].add(parent)
        after = t.raw.get("generate_after", [])
        for a in ([after] if isinstance(after, str) else after):
            if a in deps:
                deps[t.key].add(a)

    ordered: list[TableSpec] = []
    placed: set = set()
    remaining = dict(deps)
    declared_order = [t.key for t in gen_tables]
    while remaining:
        ready = [k for k in declared_order if k in remaining and remaining[k] <= placed]
        if not ready:
            cycle = sorted(remaining)
            raise SpecError(
                "FK/per_parent dependency cycle among tables: " + ", ".join(cycle[:8]) +
                ". Break the cycle with source='derivation' on one side, a nullable fk filled by a "
                "derivation update, or 'generate_after'.")
        for key in ready:
            ordered.append(by_key[key])
            placed.add(key)
            del remaining[key]
    return ordered


# ---------------------------------------------------------------------------
# Build orchestration
# ---------------------------------------------------------------------------


def strip_notes(obj: Any) -> Any:
    """Drop keys starting with '_' (e.g. '_note') so specs can be annotated freely."""
    if isinstance(obj, dict):
        return {k: strip_notes(v) for k, v in obj.items() if not str(k).startswith("_")}
    if isinstance(obj, list):
        return [strip_notes(v) for v in obj]
    return obj


def load_spec(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            return strip_notes(json.load(handle))
    except json.JSONDecodeError as exc:
        raise SpecError(f"Spec is not valid JSON: line {exc.lineno} col {exc.colno}: {exc.msg}")


def preflight(spec: dict[str, Any]) -> list[TableSpec]:
    """Structural + semantic checks. Raises SpecError on the first fatal issue."""
    if not isinstance(spec.get("tables"), list) or not spec["tables"]:
        raise SpecError("Spec must contain a non-empty 'tables' list.")
    tables = [TableSpec(raw, i, spec) for i, raw in enumerate(spec["tables"])]
    keys = [t.key for t in tables]
    dupes = {k for k in keys if keys.count(k) > 1}
    if dupes:
        raise SpecError(f"Duplicate table keys in spec: {sorted(dupes)}.")
    by_key = {t.key: t for t in tables}

    for t in tables:
        for colname, ref in t.fk_refs():
            if ref not in by_key:
                raise SpecError(f"{t.where} ({t.key}): fk column '{colname}' references unknown table "
                                f"'{ref}'.{suggest(ref, list(by_key))}")
        has_per_parent = per_parent_ref(t.rows_cfg) is not None
        for ci, col in enumerate(t.columns):
            gen = col.get("gen")
            if gen is not None and not isinstance(gen, dict):
                raise SpecError(f"{t.where}.columns[{ci}]: 'gen' must be an object.")
            if gen and gen.get("type") == "fk_copy":
                local = gen.get("column")
                if local not in t.column_names:
                    raise SpecError(f"{t.where}.columns[{ci}]: fk_copy.column '{local}' is not a column of {t.key}.")
                if t.column_names.index(local) >= ci:
                    raise SpecError(f"{t.where}.columns[{ci}]: fk_copy.column '{local}' must be declared "
                                    f"BEFORE this column — columns generate in listed order, so a later "
                                    "fk_copy source would silently produce all-NULL values.")
            if gen and gen.get("sorted") and has_per_parent:
                raise SpecError(f"{t.where}.columns[{ci}] ({t.key}): 'sorted' generators are not supported "
                                "on per_parent tables (row count unknown upfront). For child entities use "
                                "date_offset from parent.<col> or {'type': 'timestamp', 'min': 'parent.<col>'}.")
        for pk_col in t.primary_key:
            if pk_col not in t.column_names and t.source == "generator":
                raise SpecError(f"{t.where} ({t.key}): primary_key column '{pk_col}' not in columns."
                                f"{suggest(pk_col, t.column_names)}")
        if t.source == "generator" and not t.rows_cfg and not per_parent_ref(t.rows_cfg):
            if t.rows_cfg == 0:
                raise SpecError(f"{t.where} ({t.key}): generator table needs 'rows' (count, base, or per_parent). "
                                "Use source='derivation' for tables filled by SQL, source='state_machine' for "
                                "history tables, or source='empty' for intentionally empty tables.")

    generation_order(tables)  # raises on cycles

    derivation_names = set()
    for di, deriv in enumerate(spec.get("derivations", [])):
        where = f"derivations[{di}]"
        if not deriv.get("sql"):
            raise SpecError(f"{where}: missing 'sql'.")
        name = deriv.get("name", f"derivation_{di}")
        if name in derivation_names:
            raise SpecError(f"{where}: duplicate derivation name '{name}'.")
        derivation_names.add(name)

    machine_tables = {str(m.get("table")) for m in spec.get("state_machines", [])}
    for t in tables:
        if t.source == "state_machine":
            referenced = any(str(m.get("history_table")) == t.key for m in spec.get("state_machines", []))
            if not referenced and t.key not in machine_tables:
                raise SpecError(f"{t.where} ({t.key}): source='state_machine' but no state machine references it.")
    # Construct machines so their errors surface at validation/--plan time, not mid-build.
    for mi, raw in enumerate(spec.get("state_machines", [])):
        StateMachine(raw, mi, by_key)
    return tables


def estimate_rows(spec: dict[str, Any], tables: list[TableSpec], seed: int,
                  multiplier: float) -> dict[str, int]:
    """Volume forecast: estimated rows per generator table before building."""
    estimates: dict[str, int] = {}
    for tbl in generation_order(tables):
        parent = per_parent_ref(tbl.rows_cfg)
        if parent:
            dist = tbl.rows_cfg.get("distribution", {"distribution": "lognormal", "median": 3, "sigma": 0.8})
            rng = substream(seed, "__plan__", tbl.key)
            draws = [sample_number(rng, dist, f"plan:{tbl.key}") for _ in range(500)]
            lo = int(tbl.rows_cfg.get("min", 0))
            hi = int(tbl.rows_cfg.get("max", 10 ** 9))
            mean = sum(max(lo, min(int(round(d)), hi)) for d in draws) / len(draws)
            estimates[tbl.key] = int(round(estimates.get(parent, 0) * mean))
        else:
            estimates[tbl.key] = resolve_row_count(tbl.rows_cfg, multiplier, tbl.scale_exempt,
                                                   f"{tbl.where}.rows")
    for machine in spec.get("state_machines", []):
        hkey = machine.get("history_table")
        tkey = str(machine.get("table"))
        if hkey and tkey in estimates:
            # rough multiplier: entities x ~half the state count
            estimates[str(hkey)] = int(estimates[tkey] * max(2, len(machine.get("states", [])) // 2))
    return estimates


def build(spec_path: Path, out_dir: Path, db_path: Path | None, seed_override: int | None,
          multiplier_override: float | None, force: bool, schema_only: bool,
          quiet: bool) -> dict[str, Any]:
    t0 = time.time()
    if sqlite3.sqlite_version_info < (3, 31, 0):
        raise SpecError(f"SQLite {sqlite3.sqlite_version} is too old; the engine requires >= 3.31 "
                        "(window functions and modern SQL used by derivations).")
    spec = load_spec(spec_path)
    seed = int(seed_override if seed_override is not None else spec.get("seed", 42))
    scale_cfg = spec.get("scale", {}) if isinstance(spec.get("scale"), dict) else {}
    multiplier = float(multiplier_override if multiplier_override is not None
                       else scale_cfg.get("multiplier", 1.0))

    def log(msg: str) -> None:
        if not quiet:
            print(msg)

    log(f"Loading spec {spec_path} (seed={seed}, multiplier={multiplier})")
    tables = preflight(spec)
    by_key = {t.key: t for t in tables}
    name_map = {t.key: t.physical for t in tables}
    calendar = BusinessCalendar(spec)
    ctx = GenerationContext(spec, seed, calendar)

    out_dir.mkdir(parents=True, exist_ok=True)
    sql_dir = out_dir / "sqlite"
    sql_dir.mkdir(exist_ok=True)
    org_name = spec.get("organization", {}).get("name", "ecosystem")
    db_file = db_path or (out_dir / (physical_name(org_name) + ".db"))
    if db_file.exists() and not force:
        raise SpecError(f"Database {db_file} already exists. Pass --force to overwrite "
                        "(rebuilds are deterministic; there is no resume).")
    tmp_file = db_file.with_name(db_file.name + ".building")
    if tmp_file.exists():
        tmp_file.unlink()

    # --- DDL artifacts (derivation SQL rewritten to physical names) ---
    schema_sql = "pragma foreign_keys = off;\n\n" + "\n\n".join(
        render_table_ddl(t, by_key) for t in tables) + "\n" + META_DDL
    index_sql = "\n".join(stmt for t in tables for stmt in render_indexes(t)) + "\n"
    derivations: list[tuple[str, str, bool]] = []  # (name, sql, is_view) in spec order
    for di, deriv in enumerate(spec.get("derivations", [])):
        raw_sql = deriv["sql"]
        if isinstance(raw_sql, list):
            raw_sql = "\n".join(str(part) for part in raw_sql)
        sql = rewrite_logical_names(str(raw_sql).strip(), name_map)
        is_view = bool(re.match(r"(?is)^\s*create\s+(temp\s+)?view", sql))
        derivations.append((deriv.get("name", f"derivation_{di}"), sql, is_view))

    def fmt_block(items: list[tuple[str, str]]) -> str:
        parts = []
        for n, s in items:
            parts.append(f"-- {n}\n{s if s.rstrip().endswith(';') else s + ';'}")
        return "\n\n".join(parts) + "\n"

    write_kwargs = {"encoding": "utf-8", "newline": "\n"}
    with (sql_dir / "01_schema.sql").open("w", **write_kwargs) as fh:
        fh.write(schema_sql)
    with (sql_dir / "02_indexes.sql").open("w", **write_kwargs) as fh:
        fh.write(index_sql)
    with (sql_dir / "03_derivations.sql").open("w", **write_kwargs) as fh:
        fh.write(fmt_block([(n, s) for n, s, v in derivations if not v]))
    with (sql_dir / "04_views.sql").open("w", **write_kwargs) as fh:
        fh.write(fmt_block([(n, s) for n, s, v in derivations if v]))
    log(f"DDL artifacts written to {sql_dir}")

    conn = sqlite3.connect(str(tmp_file))
    try:
        conn.execute("pragma foreign_keys = off")
        conn.execute("pragma journal_mode = memory")
        conn.execute("pragma synchronous = off")
        conn.execute("pragma temp_store = memory")
        conn.execute("pragma cache_size = -64000")
        conn.executescript(schema_sql)
        stats: dict[str, dict[str, Any]] = {}
        pre_count = post_count = 0

        if not schema_only:
            # --- phase 1: topo-ordered generation (no indexes yet) ---
            needed_cache = ctx.needed_cache_columns(tables)
            referenced_as_parent = {per_parent_ref(t.rows_cfg) for t in tables if per_parent_ref(t.rows_cfg)}
            referenced_as_fk = {ref for t in tables for _, ref in t.fk_refs()}

            for tbl in generation_order(tables):
                gen = TableGenerator(tbl, ctx)
                col_names = tbl.column_names
                insert_sql = (f'insert into "{tbl.physical}" (' +
                              ", ".join(f'"{c}"' for c in col_names) +
                              ") values (" + ", ".join("?" for _ in col_names) + ")")
                needs_cache = (tbl.key in referenced_as_fk or tbl.key in referenced_as_parent
                               or tbl.key in needed_cache)
                cache_cols = sorted(needed_cache.get(tbl.key, set()))
                pk_col = tbl.primary_key[0] if tbl.primary_key else None
                pks: list[Any] = []
                cached_rows: dict[Any, dict[str, Any]] = {}

                is_scd2 = str((tbl.history or {}).get("strategy", "")).lower() == "scd2"
                if is_scd2:
                    rows_iter: Any = expand_scd2(tbl, list(gen.rows(multiplier)), ctx)
                else:
                    # Stream: no full-table materialization for large fact tables.
                    rows_iter = gen.rows(multiplier)

                row_count = 0
                batch: list[tuple] = []
                for row in rows_iter:
                    row_count += 1
                    if needs_cache and pk_col is not None:
                        # SCD2 history versions must NOT enter FK/parent pools:
                        # children would reference non-current rows with synthetic keys.
                        if not (is_scd2 and row.get("current_flag") == 0):
                            pks.append(row[pk_col])
                            if cache_cols:
                                cached_rows[row[pk_col]] = {c: iso(row.get(c)) for c in cache_cols}
                    batch.append(tuple(iso(row.get(c)) for c in col_names))
                    if len(batch) >= 20000:
                        conn.executemany(insert_sql, batch)
                        batch = []
                if batch:
                    conn.executemany(insert_sql, batch)
                if needs_cache:
                    ctx.cache[tbl.key] = {"pks": pks, "rows": cached_rows}
                stats[tbl.key] = {"rows": row_count, "by": "generator"}
                log(f"  generated {tbl.key}: {row_count} rows")

            # --- phase 2: state machines ---
            history_counts = apply_state_machines(conn, spec, by_key, ctx, log)
            for hkey, n in history_counts.items():
                stats[hkey] = {"rows": n, "by": "state_machine"}

            # --- phase 3: pre-derivation imperfections ---
            pre_count = apply_imperfections(conn, spec, by_key, ctx, "pre_derivation", log)

            # --- phase 4: indexes (before derivations so insert-selects can join fast) ---
            conn.executescript(index_sql)

            # --- phase 5: derivations, one statement at a time, sandboxed ---
            conn.commit()
            derivation_stats: list[tuple[str, int, str, int]] = []
            conn.set_authorizer(derivation_authorizer)
            try:
                for dname, dsql, is_view in derivations:
                    affected_total = 0
                    statements = split_statements(dsql)
                    for si, statement in enumerate(statements):
                        kind = statement.split(None, 2)[0].lower() if statement.split() else ""
                        try:
                            cur = conn.execute(statement)
                        except sqlite3.Error as exc:
                            raise SpecError(
                                f"derivation '{dname}' statement {si + 1}/{len(statements)} failed: {exc}\n"
                                f"Statement: {statement[:500]}")
                        rows_affected = max(cur.rowcount, 0)
                        affected_total += rows_affected
                        derivation_stats.append((dname, si, kind, rows_affected))
                    log(f"  derivation {dname}: " +
                        ("view created" if is_view else f"{affected_total} rows affected"))
            finally:
                clear_derivation_authorizer(conn)
            conn.executemany(
                "insert or replace into meta_derivation_stats "
                "(derivation_name, statement_index, statement_kind, rows_affected) "
                "values (?, ?, ?, ?)", derivation_stats)

            for t in tables:
                if t.source == "derivation":
                    n = conn.execute(f'select count(*) from "{t.physical}"').fetchone()[0]
                    stats[t.key] = {"rows": n, "by": "derivation"}

            # --- phase 6: post-derivation imperfections ---
            post_count = apply_imperfections(conn, spec, by_key, ctx, "post_derivation", log)

            # --- phase 7: meta tables ---
            conn.executemany(
                "insert into meta_table_stats (table_name, layer, row_count, generated_by) values (?, ?, ?, ?)",
                [(by_key[k].physical, by_key[k].layer, v["rows"], v["by"]) for k, v in stats.items()])
            build_info = {
                "engine_version": ENGINE_VERSION,
                "python_version": sys.version.split()[0],
                "sqlite_version": sqlite3.sqlite_version,
                "spec_path": str(spec_path),
                "spec_sha256": hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest(),
                "seed": str(seed),
                "scale_multiplier": str(multiplier),
                "organization": org_name,
                "time_start": calendar.start.isoformat(),
                "time_end": calendar.end.isoformat(),
                "as_of_date": calendar.as_of.isoformat(),
                "built_at_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                "imperfections_logged": str(pre_count + post_count),
            }
            conn.executemany("insert into meta_build_info (key, value) values (?, ?)",
                             sorted(build_info.items()))
        else:
            conn.executescript(index_sql)

        conn.execute("pragma optimize")
        conn.commit()
        check = conn.execute("pragma integrity_check").fetchone()
        if check is None or check[0] != "ok":
            raise SpecError(f"integrity_check failed on freshly built database: {check}")
    finally:
        conn.close()

    try:
        os.replace(str(tmp_file), str(db_file))
    except PermissionError:
        raise SpecError(f"Cannot replace {db_file}: the file is locked by another process "
                        "(close DB browsers/validators, or beware OneDrive sync locks).")

    total_rows = sum(v["rows"] for v in stats.values()) if not schema_only else 0
    elapsed = time.time() - t0
    summary = {
        "db_path": str(db_file),
        "tables": {k: v["rows"] for k, v in sorted(stats.items())},
        "total_rows": total_rows,
        "seed": seed,
        "multiplier": multiplier,
        "imperfections_logged": pre_count + post_count,
        "elapsed_seconds": round(elapsed, 2),
    }
    with (out_dir / "build_summary.json").open("w", encoding="utf-8", newline="\n") as fh:
        json.dump(summary, fh, indent=2)
    log(f"Build complete: {total_rows} rows across {len(stats)} populated tables "
        f"in {elapsed:.1f}s -> {db_file}")
    return summary


def main(argv: list[str] | None = None) -> int:
    if sys.version_info < (3, 9):
        print(f"error: Python {sys.version.split()[0]} is too old; the engine requires >= 3.9.",
              file=sys.stderr)
        return 2
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("spec", type=Path, help="Path to ecosystem spec JSON")
    parser.add_argument("--out", type=Path, default=Path("build"), help="Output directory (default ./build)")
    parser.add_argument("--db", type=Path, help="Database file path (default <out>/<org>.db)")
    parser.add_argument("--seed", type=int, help="Override spec seed")
    parser.add_argument("--scale-multiplier", type=float, dest="multiplier", help="Override scale.multiplier")
    parser.add_argument("--force", action="store_true", help="Overwrite an existing database file")
    parser.add_argument("--schema-only", action="store_true", help="Create schema and DDL artifacts without data")
    parser.add_argument("--plan", action="store_true", help="Print a volume forecast and exit without building")
    parser.add_argument("--quiet", action="store_true", help="Suppress progress output")
    args = parser.parse_args(argv)

    if not args.spec.exists():
        print(f"error: spec file not found: {args.spec}", file=sys.stderr)
        return 2
    try:
        if args.plan:
            spec = load_spec(args.spec)
            tables = preflight(spec)
            seed = int(args.seed if args.seed is not None else spec.get("seed", 42))
            scale_cfg = spec.get("scale", {}) if isinstance(spec.get("scale"), dict) else {}
            multiplier = float(args.multiplier if args.multiplier is not None
                               else scale_cfg.get("multiplier", 1.0))
            estimates = estimate_rows(spec, tables, seed, multiplier)
            print(f"Volume forecast (seed={seed}, multiplier={multiplier}):")
            for key, count in estimates.items():
                print(f"  {key}: ~{count:,}")
            print(f"  TOTAL (generated): ~{sum(estimates.values()):,}")
            print("Derivation-populated tables are not included in the forecast.")
            return 0
        build(args.spec, args.out, args.db, args.seed, args.multiplier,
              args.force, args.schema_only, args.quiet)
        return 0
    except SpecError as exc:
        print(f"SPEC ERROR: {exc}", file=sys.stderr)
        return 1
    except sqlite3.Error as exc:
        print(f"DATABASE ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
