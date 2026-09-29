"""
CRM › Import — businesses from a file, without any language model.

Reads CSV, TXT, Markdown and PDF (decided with the user: no LLM). Two ways a
file carries businesses, both handled:

    A table      CSV (« , » « ; » or tab), a Markdown table, or tab/semicolon
                 separated lines inside a TXT or PDF. Columns are recognised
                 by their header, in French or English (SYNONYMS).
    Free text    one business per block (blank line, Markdown heading or list
                 item between them). In each block: « Clé : valeur » lines,
                 then patterns — e-mail, French phone, SIRET, postal code +
                 city, website, Instagram/Facebook links, and a sector read
                 from known words. The first line that is none of these is
                 the business's name.

parse(filename, data) → [row] with the fields below; nothing is written. The
CRM decides what each row becomes (features/crm.py).
"""
from __future__ import annotations

import csv
import io
import re
import unicodedata
from typing import Dict, List, Optional

FIELDS = ("name", "sector", "city", "postal_code", "address", "contact_name", "contact_role", "phone",
          "email", "website", "instagram", "facebook", "siret", "status", "source", "notes")

SYNONYMS = {
    "name": ["nom du commerce", "commerce", "nom commercial", "entreprise", "societe", "raison sociale", "etablissement",
             "enseigne", "business", "company", "shop", "store", "nom", "name"],
    "sector": ["secteur", "activite", "categorie", "type", "sector", "industry", "category"],
    "city": ["ville", "commune", "city", "localite"],
    "postal_code": ["code postal", "cp", "postal code", "zip", "postcode"],
    "address": ["adresse", "rue", "address", "street"],
    "contact_name": ["contact", "gerant", "nom du contact", "interlocuteur", "responsable", "proprietaire",
                     "contact name", "owner", "prenom nom"],
    "contact_role": ["fonction", "poste", "role", "title"],
    "phone": ["telephone", "tel", "portable", "mobile", "phone", "numero"],
    "email": ["email", "e-mail", "mail", "courriel"],
    "website": ["site", "site web", "website", "url", "web"],
    "instagram": ["instagram", "insta"],
    "facebook": ["facebook", "fb"],
    "siret": ["siret", "siren"],
    "status": ["statut", "status", "etape", "stage"],
    "source": ["source", "origine", "provenance"],
    "notes": ["notes", "note", "commentaire", "commentaires", "remarques", "comments"],
}

SECTOR_WORDS = [
    ("Restauration / Fast-food", ["fast-food", "fast food", "restaurant", "restauration", "burger", "kebab", "tacos", "sushi",
                                  "pizzeria", "pizza", "brasserie", "snack", "traiteur", "bistrot", "creperie"]),
    ("Café / Salon de thé", ["cafe", "salon de the", "coffee", "coffee shop", "torrefacteur"]),
    ("Barbershop", ["barber", "barbershop", "barbier"]),
    ("Coiffure / Beauté", ["coiffure", "coiffeur", "beaute", "esthetique", "onglerie", "institut", "salon de beaute"]),
    ("Boulangerie", ["boulangerie", "patisserie", "viennoiserie", "boulanger"]),
    ("Bien-être", ["spa", "massage", "bien-etre", "bien etre", "yoga", "sauna"]),
    ("Mode", ["mode", "pret-a-porter", "vetements", "boutique", "chaussures", "fashion"]),
    ("Salle de sport", ["salle de sport", "fitness", "gym", "crossfit", "musculation"]),
    ("Optique", ["optique", "opticien", "lunettes"]),
    ("Bar", ["bar", "pub", "cave a vin", "bar a vin"]),
    ("Épicerie / Commerce de proximité", ["epicerie", "superette", "primeur", "fromagerie", "boucherie", "caviste", "tabac"]),
]

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?:(?:\+|00)33[\s.\-]?|0)[1-9](?:[\s.\-]?\d{2}){4}")
SIRET_RE = re.compile(r"\b\d{3}\s?\d{3}\s?\d{3}(?:\s?\d{5})?\b")
CP_CITY_RE = re.compile(r"\b(\d{5})\s+([A-Za-zÀ-ÿ'’\- ]{2,40}?)(?=$|,|\n|\s{2}|\s-\s|\s\()")
URL_RE = re.compile(r"(?:https?://|www\.)[^\s,;)]+", re.I)
KV_RE = re.compile(r"^\s*[-*•]?\s*\**([A-Za-zÀ-ÿ .'’/-]{2,30}?)\**\s*[:=]\s*(.+)$")


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFD", (s or "").lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn").strip()


def field_for(header: str) -> Optional[str]:
    h = re.sub(r"[_*#()\[\]]", " ", _fold(header))
    h = re.sub(r"\s+", " ", h).strip()
    if not h:
        return None
    for field, words in SYNONYMS.items():
        if h in words:
            return field
    for field, words in SYNONYMS.items():
        if any(len(w) > 3 and w in h for w in words):
            return field
    return None


def sector_of(text: str) -> str:
    t = f" {_fold(text)} "
    for label, words in SECTOR_WORDS:
        if any(re.search(rf"(?<![a-z]){re.escape(w)}(?![a-z])", t) for w in words):
            return label
    return ""


def _clean_phone(p: str) -> str:
    d = re.sub(r"[^\d+]", "", p or "")
    if d.startswith("0033"):
        d = "+33" + d[4:]
    if d.startswith("+33") and len(d) == 12:
        d = "0" + d[3:]
    if len(d) == 10 and d.startswith("0"):
        return " ".join(d[i:i + 2] for i in range(0, 10, 2))
    return (p or "").strip()


def _finish(row: Dict[str, str]) -> Dict[str, str]:
    out = {k: (row.get(k) or "").strip() for k in FIELDS}
    if out["email"]:
        m = EMAIL_RE.search(out["email"])
        out["email"] = m.group(0).lower() if m else ""
    out["phone"] = _clean_phone(out["phone"])
    out["siret"] = re.sub(r"\D", "", out["siret"])
    if out["postal_code"]:
        m = re.search(r"\d{5}", out["postal_code"])
        out["postal_code"] = m.group(0) if m else ""
    if not out["postal_code"] or not out["city"]:
        m = CP_CITY_RE.search(f"{out['address']} {out['city']}")
        if m:
            out["postal_code"] = out["postal_code"] or m.group(1)
            out["city"] = out["city"] or m.group(2).strip().title()
    if not out["sector"]:
        out["sector"] = sector_of(f"{out['name']} {out['notes']}")
    for k in ("instagram", "facebook", "website"):
        if out[k] and not out[k].startswith("http") and "." in out[k]:
            out[k] = "https://" + out[k].lstrip("/")
    return out


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------
def _table(lines: List[str], delim: str) -> Optional[List[Dict[str, str]]]:
    reader = list(csv.reader(lines, delimiter=delim))
    reader = [r for r in reader if any(c.strip() for c in r)]
    if len(reader) < 2:
        return None
    header = [field_for(c) for c in reader[0]]
    if "name" not in header and not ({"email", "phone"} & set(header)):
        return None
    rows = []
    for r in reader[1:]:
        if all(re.fullmatch(r"\s*:?-{2,}:?\s*", c or "") for c in r if c.strip()):
            continue                                    # Markdown separator row
        row: Dict[str, str] = {}
        for i, f in enumerate(header):
            if f and i < len(r) and r[i].strip():
                row[f] = (row.get(f, "") + " " + r[i].strip()).strip() if f == "notes" else r[i].strip()
        if row.get("name") or row.get("email") or row.get("phone"):
            rows.append(_finish(row))
    return rows


def _sniff(text: str) -> Optional[List[Dict[str, str]]]:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return []
    md = [ln.strip().strip("|") for ln in lines if ln.strip().startswith("|") and ln.count("|") >= 3]
    if len(md) >= 2:
        got = _table([re.sub(r"\s*\|\s*", "|", ln) for ln in md], "|")
        if got is not None:
            return got
    head = lines[0]
    for delim in (";", "\t", ",", "|"):
        if head.count(delim) >= 2:
            got = _table(lines, delim)
            if got is not None:
                return got
    return None


# ---------------------------------------------------------------------------
# Free text
# ---------------------------------------------------------------------------
def _blocks(text: str) -> List[str]:
    """One block per business. With Markdown headings, each heading opens a
    business and everything under it belongs to it. Otherwise blank lines
    separate businesses — and a list whose every line is a whole business
    (« - Café X, Tours, 06 … ») is split line by line."""
    text = text.replace("\r", "")
    if re.search(r"^#{2,6}\s", text, re.M) or len(re.findall(r"^#\s", text, re.M)) > 1:
        parts = re.split(r"\n(?=#{1,6}\s)", "\n" + text)
    else:
        parts = re.split(r"\n\s*\n", text)
    out: List[str] = []
    for p in parts:
        lines = [ln for ln in p.strip().splitlines() if ln.strip()]
        items = [ln for ln in lines if re.match(r"\s*(?:\d+[.)]|[-*•])\s+", ln)]
        if len(items) >= 2 and len(items) == len(lines) and \
                all(EMAIL_RE.search(ln) or PHONE_RE.search(ln) for ln in items):
            out.extend(items)
        elif lines:
            out.append("\n".join(lines))
    return out


def _from_block(block: str) -> Optional[Dict[str, str]]:
    row: Dict[str, str] = {}
    leftovers: List[str] = []
    for raw in block.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = KV_RE.match(line)
        f = field_for(m.group(1)) if m else None
        if m and f:
            row.setdefault(f, m.group(2).strip().strip("*"))
            continue
        leftovers.append(line)
    rest = "\n".join(leftovers)
    if "email" not in row and (m := EMAIL_RE.search(rest)):
        row["email"] = m.group(0)
    if "phone" not in row and (m := PHONE_RE.search(rest)):
        row["phone"] = m.group(0)
    for u in URL_RE.findall(rest):
        u = u.rstrip(".")
        key = "instagram" if "instagram." in u else "facebook" if "facebook." in u else "website"
        row.setdefault(key, u)
    if "siret" not in row and (m := re.search(r"siret\D{0,5}(\d[\d ]{12,16}\d)", rest, re.I)):
        row["siret"] = m.group(1)
    if "postal_code" not in row and (m := CP_CITY_RE.search(rest)):
        row["postal_code"] = m.group(1)
        row.setdefault("city", m.group(2).strip().title())
    if "name" not in row:
        for line in leftovers:
            cand = re.sub(r"^(?:#{1,6}\s*|\d+[.)]\s*|[-*•]\s*)", "", line).strip().strip("*_").strip()
            # The name is what comes before the first comma or dash —
            # « Kebab Istanbul, restauration rapide, 07 88 … ».
            head = re.split(r"\s[—–-]\s|,", cand)[0].strip()
            if not head or EMAIL_RE.search(head) or PHONE_RE.search(head) or URL_RE.search(head) \
                    or re.fullmatch(r"[\d\s,.-]+", head):
                continue
            row["name"] = head[:100]
            if head != cand and not row.get("contact_name"):
                # « Optique Vision — Camille B., 06 … »: a person's name after the dash.
                m = re.search(r"[—–-]\s*([A-ZÀ-Ý][a-zà-ÿ]+(?:\s[A-ZÀ-Ý][a-zà-ÿ]*\.?)+)", cand)
                if m:
                    row["contact_name"] = m.group(1)
            break
    if "address" not in row:
        for line in leftovers:
            if re.search(r"\b\d{1,4}\s*(?:bis|ter)?,?\s+(?:rue|avenue|av\.|boulevard|bd|place|quai|allée|chemin|route|impasse)\b", line, re.I):
                row["address"] = line.strip("-*• ")
                break
    if not row.get("sector"):
        row["sector"] = sector_of(block)
    if not (row.get("name") and (row.get("email") or row.get("phone") or row.get("city") or row.get("address"))):
        return None
    return _finish(row)


def parse_text(text: str) -> List[Dict[str, str]]:
    table = _sniff(text)
    if table is not None:
        return table
    return [r for r in (_from_block(b) for b in _blocks(text)) if r]


def pdf_text(data: bytes) -> str:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    return "\n\n".join((p.extract_text() or "") for p in reader.pages)


def parse(filename: str, data: bytes) -> List[Dict[str, str]]:
    name = (filename or "").lower()
    if name.endswith(".pdf") or data[:4] == b"%PDF":
        return parse_text(pdf_text(data))
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = data.decode("utf-8", errors="ignore")
    return parse_text(text)
