"""Resolve a free-text Philippine address with the PSGC lists in data/psgc.

A municipality that exists in only one province maps to that province, or to a
Maki city when the municipality itself is that city. The same name in several
provinces stays unresolved unless the address also names the province or a
barangay that belongs to only one of those towns.
"""

import csv
import re
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data" / "psgc"

# Bare names that mean the chartered city even when a smaller town shares them.
BARE_CITY_CORES = {"cebu", "iloilo", "davao", "manila", "bacolod", "baguio"}

_NCR_CODES = {"1339", "1374", "1375", "1376"}
_MANILA_CODE = "1339"
_SKIP_ALT = {"capital", "pob", "poblacion", "city", "pob."}
_CACHE = {}


def norm_place(value):
    text = str(value or "").lower().replace("ñ", "n").replace("帽", "n")
    text = text.replace("’", "'")
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"^city of ", "", text)
    text = text.replace("quezon city", "quezoncity")
    text = re.sub(r"\bcity\b", " ", text)
    text = text.replace("quezoncity", "quezon city")
    return re.sub(r"\s+", " ", text).strip()


def _is_city_label(label):
    return label.startswith("City of") or label.endswith(" City") or label == "Pateros"


class Resolve:
    def __init__(self, label=None, ambiguous=False, core=None, blocked=False):
        self.label = label
        self.ambiguous = ambiguous
        self.core = core
        self.blocked = blocked


class _Prov:
    def __init__(self, code, label, special=None):
        self.code = code
        self.label = label
        self.special = special


class _Mun:
    def __init__(self, code, prov_code, core, is_city):
        self.code = code
        self.prov_code = prov_code
        self.core = core
        self.is_city = is_city


def _strip_paren(value):
    return re.sub(r"\s*\([^)]*\)", " ", value or "")


def _parentheticals(value):
    return re.findall(r"\(([^)]*)\)", value or "")


class PlaceIndex:
    def __init__(self, labels):
        self.by_norm = {}
        for label in labels:
            key = norm_place(label)
            self.by_norm.setdefault(key, []).append(label)
        self.provinces = {}
        self.prov_by_code = {}
        self.munis = {}
        self.mun_by_code = {}
        self.barangays = {}
        self.unique_barangay = {}
        self._load()

    def _province_label(self, desc):
        lowered = desc.lower()
        if "maguindanao" in lowered:
            return "Maguindanao del Norte", "maguindanao"
        if lowered.startswith("ncr") or "district" in lowered or lowered == "cotabato city":
            return None, None
        primary = _strip_paren(desc).strip()
        key = norm_place(primary)
        if key == "compostela valley":
            return "Davao de Oro", None
        if "city of isabela" in lowered:
            return "City of Isabela", None
        labels = self.by_norm.get(key, [])
        plain = [label for label in labels if not _is_city_label(label)]
        if len(plain) == 1:
            return plain[0], None
        if len(labels) == 1:
            return labels[0], None
        return None, None

    def _add_province_key(self, key, prov):
        if not key or len(key) < 4:
            return
        current = self.provinces.get(key)
        if current is None:
            self.provinces[key] = prov
        elif current is not prov:
            self.provinces[key] = None

    def _add_muni(self, core, mun):
        if not core or len(core) < 3:
            return
        self.munis.setdefault(core, []).append(mun)

    def _load(self):
        with (DATA_DIR / "Province.csv").open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                code = row["provCode"].strip()
                desc = row["provDesc"].strip()
                label, special = self._province_label(desc)
                prov = _Prov(code, label, special)
                self.prov_by_code[code] = prov
                if code in _NCR_CODES or (label is None and special is None):
                    continue
                primary = norm_place(_strip_paren(desc))
                if "city of isabela" in desc.lower():
                    primary = ""
                self._add_province_key(primary, prov)
                for alt in _parentheticals(desc):
                    alt_key = norm_place(alt)
                    if alt_key in _SKIP_ALT:
                        continue
                    self._add_province_key(alt_key, prov)
        self.provinces = {key: prov for key, prov in self.provinces.items() if prov is not None}

        with (DATA_DIR / "Municipalities.csv").open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                desc = row["citymunDesc"].strip()
                raw = re.sub(r"\s+", " ", _strip_paren(desc)).strip()
                upper = raw.upper()
                is_city = upper.startswith("CITY OF ") or upper.endswith(" CITY") or upper == "QUEZON CITY"
                core = norm_place(raw)
                mun = _Mun(row["citymunCode"].strip(), row["provCode"].strip(), core, is_city)
                self.mun_by_code[mun.code] = mun
                self._add_muni(core, mun)
                if re.fullmatch(r"TONDO I / II", upper):
                    self._add_muni("tondo", mun)
                for alt in _parentheticals(desc):
                    alt_key = norm_place(alt)
                    if alt_key in _SKIP_ALT or len(alt_key) < 4:
                        continue
                    self._add_muni(alt_key, mun)

        counted = {}
        with (DATA_DIR / "Barangay.csv").open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                key = norm_place(_strip_paren(row["brgyDesc"]))
                if len(key) < 6:
                    continue
                code = row["citymunCode"].strip()
                self.barangays.setdefault(code, []).append(key)
                counted.setdefault(key, set()).add(code)
        for key, codes in counted.items():
            if len(key) >= 8 and len(codes) == 1:
                self.unique_barangay[key] = next(iter(codes))

    def _city_label(self, core, is_city):
        if not is_city:
            return None
        cities = [label for label in self.by_norm.get(core, []) if _is_city_label(label)]
        if len(cities) == 1:
            return cities[0]
        return None

    def _label_for(self, mun, text):
        if mun.prov_code == _MANILA_CODE:
            return "City of Manila"
        if mun.prov_code in _NCR_CODES:
            if mun.core == "quezon city":
                return "Quezon City"
            city = self._city_label(mun.core, True)
            if city:
                return city
            return None
        city = self._city_label(mun.core, mun.is_city)
        if city:
            return city
        prov = self.prov_by_code.get(mun.prov_code)
        if prov is None:
            return None
        return self._province_text(prov, text)

    def _province_text(self, prov, text):
        if prov.special == "maguindanao":
            if re.search(r"(^| )del sur( |$)", text):
                return "Maguindanao del Sur"
            return "Maguindanao del Norte"
        return prov.label

    def _hits(self, words, index, occupied=None, ncr_only=False):
        occupied = list(occupied) if occupied is not None else [False] * len(words)
        found = []
        upper = min(8, len(words))
        for size in range(upper, 0, -1):
            for start in range(len(words) - size + 1):
                if any(occupied[start:start + size]):
                    continue
                gram = " ".join(words[start:start + size])
                if gram == "quezon" and start + size < len(words) and words[start + size] == "city":
                    continue
                if index is self.munis and start + size < len(words) and words[start + size] in {"region", "province"}:
                    continue
                item = index.get(gram)
                if item is None:
                    continue
                if ncr_only and isinstance(item, list):
                    item = [mun for mun in item if mun.prov_code in _NCR_CODES]
                    if not item:
                        continue
                for offset in range(start, start + size):
                    occupied[offset] = True
                found.append(item)
        return found, occupied

    def _narrow(self, groups, words, occupied):
        flat = [mun for group in groups for mun in group]
        if len(flat) < 2:
            return flat
        codes = {mun.code for mun in flat}
        matched = set()
        for code in codes:
            for name in self.barangays.get(code, ()):
                if len(name) < 6:
                    continue
                name_words = name.split()
                size = len(name_words)
                if size > len(words):
                    continue
                for start in range(len(words) - size + 1):
                    if any(occupied[start:start + size]):
                        continue
                    if words[start:start + size] == name_words:
                        matched.add(code)
                        break
        if len(matched) == 1:
            code = next(iter(matched))
            return [mun for mun in flat if mun.code == code]
        return flat

    def _from_munis(self, munis, text, said_city):
        if not munis:
            return None
        if len(munis) == 1:
            return Resolve(self._label_for(munis[0], text))
        if said_city:
            cities = [mun for mun in munis if mun.is_city]
            if len(cities) == 1:
                return Resolve(self._label_for(cities[0], text))
        labels = {self._label_for(mun, text) for mun in munis}
        labels.discard(None)
        if len(labels) == 1:
            return Resolve(next(iter(labels)))
        core = munis[0].core
        if core in BARE_CITY_CORES:
            cities = [mun for mun in munis if mun.is_city]
            if len(cities) == 1:
                label = self._label_for(cities[0], text)
                if label:
                    return Resolve(label)
        return Resolve(ambiguous=True, core=core)

    def resolve(self, text, said_city=False, ncr_only=False):
        if not text:
            return Resolve()
        words = text.split()
        prov_hits, prov_occupied = self._hits(words, self.provinces, ncr_only=False)
        if len(prov_hits) > 1:
            return Resolve(ambiguous=True, blocked=True)
        province = prov_hits[0] if prov_hits else None
        occupied = list(prov_occupied)
        groups, mun_occupied = self._hits(words, self.munis, occupied, ncr_only=ncr_only)
        for index, flag in enumerate(mun_occupied):
            occupied[index] = occupied[index] or flag
        if province is not None and groups:
            filtered = []
            for group in groups:
                kept = [mun for mun in group if mun.prov_code == province.code]
                if kept:
                    filtered.append(kept)
            if not filtered:
                return Resolve(ambiguous=True, core=groups[0][0].core, blocked=True)
            groups = filtered
        if len(groups) > 1:
            common = None
            for group in groups:
                codes = {mun.code for mun in group}
                common = codes if common is None else common & codes
            if common and len(common) == 1:
                code = next(iter(common))
                chosen = next(mun for group in groups for mun in group if mun.code == code)
                groups = [[chosen]]
        if groups:
            munis = self._narrow(groups, words, occupied)
            found = self._from_munis(munis, text, said_city)
            if found is not None and (found.label or found.ambiguous):
                return found
        if province is not None and not groups:
            label = self._province_text(province, text)
            if label:
                return Resolve(label)
        if not groups and province is None:
            bare_hits, _ = self._hits(words, self.unique_barangay, ncr_only=False)
            codes = set(bare_hits)
            if len(codes) == 1:
                mun = self.mun_by_code.get(next(iter(codes)))
                if mun is not None:
                    label = self._label_for(mun, text)
                    if label:
                        return Resolve(label)
        return Resolve()


def resolve_place(text, labels, said_city=False, ncr_only=False):
    key = tuple(labels)
    index = _CACHE.get(key)
    if index is None:
        index = PlaceIndex(labels)
        _CACHE[key] = index
    return index.resolve(text, said_city=said_city, ncr_only=ncr_only)
