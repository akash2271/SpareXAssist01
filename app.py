"""
SpareX Assist – Flask Web Application
======================================
A web-based AI chat assistant for spare parts lookup.
Reuses the SpareEngine logic from the original Tkinter app.
"""

import os
import re
import math
import traceback
import pandas as pd
import numpy as np
from flask import Flask, render_template, request, jsonify

# ---------------------------------------------------------------------------
# Flask App
# ---------------------------------------------------------------------------
app = Flask(__name__)

# ---------------------------------------------------------------------------
# Keyword aliases
# ---------------------------------------------------------------------------
KEYWORD_ALIASES = {
    "motor": ["ret motor"],
    "ret": ["ret motor"],
    "adapter": ["adapter", "power adapter", "psu adapter", "sma adapter",
                "pa adapter", "pwr adapter", "interface"],
    "pin": ["pin", "pin block", "probe"],
    "probe": ["probe", "rf probe", "probe hss", "probe ascf"],
    "connector": ["connector", "rf connector", "power connector",
                  "trx rf connector"],
    "fuse": ["fuse", "smd fuse"],
    "cable": ["cable", "fibre cable", "rf cable"],
    "sfp": ["sfp", "sfp module"],
    "card": ["card", "fpga card"],
    "fan": ["fan", "cooling fan"],
    "relay": ["relay"],
    "cover": ["cover"],
    "plug": ["plug"],
    "screw": ["screw"],
    "washer": ["washer"],
    "tape": ["tape"],
    "switch": ["switch"],
    "coupler": ["coupler"],
    "splitter": ["splitter", "power splitter"],
    "ic": ["ic"],
    "receptacle": ["recepticle", "receptacle", "trx receptacle"],
    "attenuator": ["attenuator", "sma attenuator"],
    "bushing": ["bushing"],
    "usb": ["usb hub", "usb"],
    "controller": ["controller"],
    "shunt": ["shunt"],
    "spring": ["gas spring", "spring"],
    "pad": ["pad", "pads"],
    "unit": ["unit"],
    "block": ["dc block", "pin block"],
    "power": ["power adapter", "power splitter", "power connector",
              "pwr adapter", "power supply"],
    "rf": ["rf probe", "rf connector", "rf cable", "rf adapter"],
    "sma": ["sma adapter", "sma connector", "sma attenuator"],
    "bearing": ["bearing"],
}

# ---------------------------------------------------------------------------
# Intent patterns
# ---------------------------------------------------------------------------
INTENT_PATTERNS = [
    (re.compile(r"^(?:where\s+is|where\s+are|where\s+can\s+i\s+find|"
                r"location\s+of|find\s+location|kahan\s+hai|kaha\s+hai|"
                r"locate)\s+(.+)$", re.I), "location"),
    (re.compile(r"^(?:how\s+many|stock\s+of|quantity\s+of|count\s+of|"
                r"kitne|kitna|available\s+stock|closing\s+stock\s+of|"
                r"stock\s+check|check\s+stock)\s+(.+)$", re.I), "stock"),
    (re.compile(r"^(?:vendor\s+of|supplier\s+of|who\s+supplies|"
                r"who\s+is\s+the\s+vendor|manufacturer\s+of|"
                r"vendor\s+for|supplier\s+for)\s+(.+)$", re.I), "vendor"),
    (re.compile(r"^(?:which\s+project\s+(?:has|uses|for)|project\s+of|"
                r"project\s+for|kis\s+project)\s+(.+)$", re.I), "project"),
    (re.compile(r"^(?:test\s+bench\s+(?:for|of)|which\s+bench|"
                r"bench\s+for|used\s+(?:on|in|at)\s+which\s+bench)\s+(.+)$", re.I), "bench"),
    (re.compile(r"^(?:what\s+is\s+in|show\s+(?:all\s+in|items\s+in)|"
                r"list\s+(?:all\s+in|items\s+in)|parts\s+in)\s+(m\d+)$", re.I), "almira_list"),
    (re.compile(r"^(?:what\s+is\s+in|show\s+(?:all\s+in|items\s+in)|"
                r"list\s+(?:all\s+in|items\s+in)|parts\s+in)\s+"
                r"(?:zone\s+)?(00[a-dA-D])$", re.I), "zone_list"),
    (re.compile(r"^(?:show\s+all|list\s+all|all)\s+(.+?)(?:\s+type)?$", re.I), "type_filter"),
    (re.compile(r"^(?:part\s+code\s+(?:of|for)|code\s+(?:of|for)|"
                r"what\s+is\s+the\s+(?:part\s+)?code\s+(?:of|for))\s+(.+)$", re.I), "partcode"),
    (re.compile(r"^(?:tell\s+me\s+about|details\s+of|info\s+(?:of|about|on)|"
                r"full\s+info|show\s+details)\s+(.+)$", re.I), "full_info"),
]


# ---------------------------------------------------------------------------
# SpareEngine – search & Q&A logic (reused from original)
# ---------------------------------------------------------------------------
class SpareEngine:
    """Handles loading spare data and intelligent Q&A searching."""

    def __init__(self):
        self.df = None
        self.file_path = None
        self.columns = []

    def load_file(self, path: str) -> str:
        try:
            ext = os.path.splitext(path)[1].lower()
            if ext in (".xlsx", ".xls"):
                self.df = pd.read_excel(path, engine="openpyxl")
            elif ext == ".csv":
                self.df = pd.read_csv(path)
            else:
                return f"Unsupported file type: {ext}"
            self.df.columns = [str(c).strip() for c in self.df.columns]
            self.columns = list(self.df.columns)
            self.file_path = path
            return f"Loaded {os.path.basename(path)} — {len(self.df)} records."
        except Exception as e:
            return f"Error loading file: {e}"

    def _normalize(self, text: str) -> str:
        return re.sub(r"\s+", " ", str(text).lower().strip())

    def _fuzzy_match(self, query: str, text: str) -> bool:
        q_words = self._normalize(query).split()
        t = self._normalize(text)
        return all(w in t for w in q_words)

    def _safe_str(self, val) -> str:
        if val is None:
            return "—"
        try:
            if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
                return "—"
            if pd.isna(val):
                return "—"
        except (TypeError, ValueError):
            pass
        s = str(val).strip()
        return s if s else "—"

    def _get_column(self, name: str) -> str:
        for c in self.columns:
            if self._normalize(c) == self._normalize(name):
                return c
        return name

    def _find_parts(self, search_term: str, max_results: int = 20):
        if self.df is None:
            return []
        search_lower = self._normalize(search_term)
        results = []
        seen = set()

        expanded = [search_term]
        for alias_key, alias_values in KEYWORD_ALIASES.items():
            if search_lower == alias_key or search_lower in [self._normalize(v) for v in alias_values]:
                for av in alias_values:
                    if self._normalize(av) != search_lower:
                        expanded.append(av)
                if alias_key != search_lower:
                    expanded.append(alias_key)

        desc_col = self._get_column("DESCRIPTION")
        code_col = self._get_column("PART CODE")

        for idx, row in self.df.iterrows():
            if idx in seen:
                continue
            desc_val = self._normalize(str(row.get(desc_col, "")))
            code_val = self._normalize(str(row.get(code_col, "")))
            combined = desc_val + " " + code_val
            for term in expanded:
                if self._fuzzy_match(term, combined):
                    results.append(row.to_dict())
                    seen.add(idx)
                    break
            if len(results) >= max_results:
                break

        if not results:
            for idx, row in self.df.iterrows():
                if idx in seen:
                    continue
                combined = " ".join(str(v) for v in row.values)
                for term in expanded:
                    if self._fuzzy_match(term, combined):
                        results.append(row.to_dict())
                        seen.add(idx)
                        break
                if len(results) >= max_results:
                    break
        return results

    def _detect_intent(self, query: str):
        q = query.strip()
        for pattern, intent in INTENT_PATTERNS:
            m = pattern.match(q)
            if m:
                return intent, m.group(1).strip()
        return None, q

    # ------------------------------------------------------------------
    # Smart Q&A — returns JSON-friendly dict instead of formatted text
    # ------------------------------------------------------------------
    def smart_query(self, query: str) -> dict:
        if self.df is None:
            return {"answer": "⚠️ Data file not loaded!", "cards": []}

        intent, search_term = self._detect_intent(query)

        if intent == "almira_list":
            return self._answer_almira_list(search_term)
        if intent == "zone_list":
            return self._answer_zone_list(search_term)
        if intent == "type_filter":
            return self._answer_type_filter(search_term)

        parts = self._find_parts(search_term)
        if not parts:
            return {
                "answer": f'😕 No results found for "{search_term}".\nTry different keywords or check spelling.',
                "cards": []
            }

        if intent == "location":
            return self._answer_location(search_term, parts)
        if intent == "stock":
            return self._answer_stock(search_term, parts)
        if intent == "vendor":
            return self._answer_vendor(search_term, parts)
        if intent == "project":
            return self._answer_project(search_term, parts)
        if intent == "bench":
            return self._answer_bench(search_term, parts)
        if intent == "partcode":
            return self._answer_partcode(search_term, parts)
        if intent == "full_info":
            return self._answer_full_info(search_term, parts)
        return self._answer_general(search_term, parts)

    # --- helpers to sanitize card dicts (NaN → "—") ---
    def _clean_card(self, d: dict) -> dict:
        """Sanitise a row dict so every value is a plain JSON-safe string."""
        out = {}
        for k, v in d.items():
            if str(k).startswith("Unnamed"):
                continue
            out[str(k)] = self._safe_str(v)
        return out

    # --- Answer formatters ---
    def _answer_location(self, term, parts):
        lines = []
        for p in parts[:5]:
            desc = self._safe_str(p.get(self._get_column("DESCRIPTION")))
            almira = self._safe_str(p.get(self._get_column("ALMIRA NO")))
            zone = self._safe_str(p.get(self._get_column("ZONE")))
            bin_val = self._safe_str(p.get(self._get_column("BIN")))
            location = self._safe_str(p.get(self._get_column("LOCATION")))
            lines.append(
                f'📍 <strong>{desc}</strong> is located at:\n'
                f'   🗄️ Almira: <strong>{almira}</strong> | Zone: <strong>{zone}</strong> | Bin: <strong>{bin_val}</strong>\n'
                f'   📦 Location Code: <strong>{location}</strong>'
            )
        answer = f'🔍 Location for "{term}":\n\n' + "\n\n".join(lines)
        if len(parts) > 5:
            answer += f"\n\n... and {len(parts) - 5} more result(s)."
        return {"answer": answer, "cards": []}

    def _answer_stock(self, term, parts):
        lines = []
        for p in parts[:5]:
            desc = self._safe_str(p.get(self._get_column("DESCRIPTION")))
            opening = self._safe_str(p.get(self._get_column("OPENING STOCK")))
            issued = self._safe_str(p.get(self._get_column("ISSUED")))
            recd = self._safe_str(p.get(self._get_column("RECD.")))
            closing = self._safe_str(p.get(self._get_column("CLOSING STOCK")))
            lines.append(
                f'📊 <strong>{desc}</strong>:\n'
                f'   Opening: {opening} | Issued: {issued} | '
                f'Received: {recd} | Closing: <strong>{closing}</strong>'
            )
        answer = f'📦 Stock info for "{term}":\n\n' + "\n\n".join(lines)
        if len(parts) > 5:
            answer += f"\n\n... and {len(parts) - 5} more result(s)."
        return {"answer": answer, "cards": []}

    def _answer_vendor(self, term, parts):
        lines = []
        for p in parts[:5]:
            desc = self._safe_str(p.get(self._get_column("DESCRIPTION")))
            vendor = self._safe_str(p.get(self._get_column("VENDOR")))
            address = self._safe_str(p.get(self._get_column("VENDOR ADDRESS")))
            lines.append(
                f'🏭 <strong>{desc}</strong>:\n'
                f'   Vendor: <strong>{vendor}</strong> ({address})'
            )
        answer = f'🏢 Vendor info for "{term}":\n\n' + "\n\n".join(lines)
        if len(parts) > 5:
            answer += f"\n\n... and {len(parts) - 5} more result(s)."
        return {"answer": answer, "cards": []}

    def _answer_project(self, term, parts):
        projects = set()
        desc_name = "—"
        for p in parts:
            proj = self._safe_str(p.get(self._get_column("PROJECT")))
            if proj != "—":
                projects.add(proj)
            d = self._safe_str(p.get(self._get_column("DESCRIPTION")))
            if d != "—":
                desc_name = d
        if projects:
            proj_list = ", ".join(sorted(projects))
            answer = f'📌 <strong>{desc_name}</strong> is found in project(s):\n\n   🏗️ {proj_list}'
        else:
            answer = f'😕 No project information found for "{term}".'
        return {"answer": answer, "cards": []}

    def _answer_bench(self, term, parts):
        benches = set()
        desc_name = "—"
        for p in parts:
            bench = self._safe_str(p.get(self._get_column("TEST BENCH")))
            if bench != "—":
                benches.add(bench)
            d = self._safe_str(p.get(self._get_column("DESCRIPTION")))
            if d != "—":
                desc_name = d
        if benches:
            bench_list = ", ".join(sorted(benches))
            answer = f'🔬 <strong>{desc_name}</strong> is used on:\n\n   🧪 {bench_list}'
        else:
            answer = f'😕 No test bench information found for "{term}".'
        return {"answer": answer, "cards": []}

    def _answer_partcode(self, term, parts):
        lines = []
        for p in parts[:5]:
            desc = self._safe_str(p.get(self._get_column("DESCRIPTION")))
            code = self._safe_str(p.get(self._get_column("PART CODE")))
            lines.append(f'🔖 <strong>{desc}</strong> → Part Code: <strong>{code}</strong>')
        answer = f'🏷️ Part code for "{term}":\n\n' + "\n".join(lines)
        return {"answer": answer, "cards": []}

    def _answer_full_info(self, term, parts):
        count = min(len(parts), 5)
        answer = f'🔍 Found <strong>{len(parts)}</strong> result(s) for "{term}":'
        cards = [self._clean_card(p) for p in parts[:count]]
        return {"answer": answer, "cards": cards}

    def _answer_almira_list(self, almira_code):
        if self.df is None:
            return {"answer": "⚠️ Data file not loaded!", "cards": []}
        almira_col = self._get_column("ALMIRA NO")
        code_upper = almira_code.upper()
        matches = self.df[self.df[almira_col].astype(str).str.strip().str.upper() == code_upper]
        if matches.empty:
            return {"answer": f'😕 No items found in Almira <strong>{code_upper}</strong>.', "cards": []}
        desc_col = self._get_column("DESCRIPTION")
        zone_col = self._get_column("ZONE")
        bin_col = self._get_column("BIN")
        lines = []
        for _, row in matches.head(15).iterrows():
            desc = self._safe_str(row.get(desc_col))
            zone = self._safe_str(row.get(zone_col))
            bin_val = self._safe_str(row.get(bin_col))
            lines.append(f"  • {desc}  (Zone: {zone}, {bin_val})")
        answer = f'🗄️ Items in Almira <strong>{code_upper}</strong> ({len(matches)} total):\n\n' + "\n".join(lines)
        if len(matches) > 15:
            answer += f"\n\n... and {len(matches) - 15} more."
        return {"answer": answer, "cards": []}

    def _answer_zone_list(self, zone_code):
        if self.df is None:
            return {"answer": "⚠️ Data file not loaded!", "cards": []}
        zone_col = self._get_column("ZONE")
        code_upper = zone_code.upper()
        matches = self.df[self.df[zone_col].astype(str).str.strip().str.upper() == code_upper]
        if matches.empty:
            return {"answer": f'😕 No items found in Zone <strong>{code_upper}</strong>.', "cards": []}
        desc_col = self._get_column("DESCRIPTION")
        almira_col = self._get_column("ALMIRA NO")
        bin_col = self._get_column("BIN")
        lines = []
        for _, row in matches.head(15).iterrows():
            desc = self._safe_str(row.get(desc_col))
            almira = self._safe_str(row.get(almira_col))
            bin_val = self._safe_str(row.get(bin_col))
            lines.append(f"  • {desc}  (Almira: {almira}, {bin_val})")
        answer = f'🏷️ Items in Zone <strong>{code_upper}</strong> ({len(matches)} total):\n\n' + "\n".join(lines)
        if len(matches) > 15:
            answer += f"\n\n... and {len(matches) - 15} more."
        return {"answer": answer, "cards": []}

    def _answer_type_filter(self, type_term):
        if self.df is None:
            return {"answer": "⚠️ Data file not loaded!", "cards": []}
        type_col = self._get_column("TYPE")
        term_lower = self._normalize(type_term)
        matches = self.df[self.df[type_col].astype(str).apply(self._normalize) == term_lower]
        if matches.empty:
            mask = self.df[type_col].astype(str).apply(lambda x: self._fuzzy_match(type_term, x))
            matches = self.df[mask]
        if matches.empty:
            return {"answer": f'😕 No items found with type "{type_term}".', "cards": []}
        desc_col = self._get_column("DESCRIPTION")
        loc_col = self._get_column("LOCATION")
        lines = []
        for _, row in matches.head(15).iterrows():
            desc = self._safe_str(row.get(desc_col))
            loc = self._safe_str(row.get(loc_col))
            lines.append(f"  • {desc}  (Location: {loc})")
        answer = (
            f'📋 All <strong>{type_term.upper()}</strong> type items ({len(matches)} total):\n\n'
            + "\n".join(lines)
        )
        if len(matches) > 15:
            answer += f"\n\n... and {len(matches) - 15} more."
        return {"answer": answer, "cards": []}

    def _answer_general(self, term, parts):
        first = parts[0]
        desc = self._safe_str(first.get(self._get_column("DESCRIPTION")))
        almira = self._safe_str(first.get(self._get_column("ALMIRA NO")))
        zone = self._safe_str(first.get(self._get_column("ZONE")))
        bin_val = self._safe_str(first.get(self._get_column("BIN")))
        location = self._safe_str(first.get(self._get_column("LOCATION")))
        closing = self._safe_str(first.get(self._get_column("CLOSING STOCK")))
        project = self._safe_str(first.get(self._get_column("PROJECT")))
        vendor = self._safe_str(first.get(self._get_column("VENDOR")))
        part_code = self._safe_str(first.get(self._get_column("PART CODE")))
        bench = self._safe_str(first.get(self._get_column("TEST BENCH")))

        answer = (
            f'🔍 Found <strong>{len(parts)}</strong> result(s) for "{term}":\n\n'
            f'📌 <strong>{desc}</strong>\n'
            f'   📍 Location: Almira <strong>{almira}</strong> | Zone <strong>{zone}</strong> | <strong>{bin_val}</strong>\n'
            f'   📦 Location Code: <strong>{location}</strong>\n'
            f'   📊 Closing Stock: <strong>{closing}</strong>\n'
            f'   🏗️ Project: {project}\n'
            f'   🏷️ Part Code: {part_code}\n'
            f'   🏭 Vendor: {vendor}'
        )
        if bench != "—":
            answer += f"\n   🧪 Test Bench: {bench}"

        cards = [self._clean_card(p) for p in parts[1:6]] if len(parts) > 1 else []
        if len(parts) > 1:
            answer += "\n\n── More results ──"
        return {"answer": answer, "cards": cards}

    def get_stats(self) -> str:
        if self.df is None:
            return "No file loaded."
        return (
            f"📁 File: {os.path.basename(self.file_path)}\n"
            f"📊 Total Records: {len(self.df)}\n"
            f"📋 Columns ({len(self.columns)}): {', '.join(self.columns)}"
        )


# ---------------------------------------------------------------------------
# Initialise engine & load data
# ---------------------------------------------------------------------------
engine = SpareEngine()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = "spares_data.csv"
data_path = os.path.join(BASE_DIR, DATA_FILE)

try:
    if os.path.exists(data_path):
        print(engine.load_file(data_path))
    else:
        print(f"⚠️  Data file not found: {data_path}")
        print(f"   Current directory contents: {os.listdir(BASE_DIR)}")
        print("   Place the Excel file in the same folder as app.py")
except Exception as e:
    print(f"⚠️  Error during startup data load: {e}")
    traceback.print_exc()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.errorhandler(500)
def handle_500(e):
    return jsonify({"error": str(e), "traceback": traceback.format_exc()}), 500


@app.route("/")
def index():
    try:
        loaded = engine.df is not None
        record_count = len(engine.df) if loaded else 0
        return render_template("index.html", loaded=loaded, record_count=record_count)
    except Exception as e:
        return f"<h1>SpareX Assist</h1><p>Error: {e}</p><pre>{traceback.format_exc()}</pre>", 500


@app.route("/api/chat", methods=["POST"])
def chat():
    try:
        data = request.get_json(silent=True) or {}
        query = data.get("query", "").strip()

        if not query:
            return jsonify({"answer": "⚠️ Please enter a query.", "cards": []})

        q_lower = query.lower()

        # Built-in commands
        if q_lower in ("help", "commands", "?"):
            return jsonify({"answer": _help_text(), "cards": []})
        if q_lower in ("stats", "info", "status"):
            return jsonify({"answer": engine.get_stats(), "cards": []})

        result = engine.smart_query(query)
        return jsonify(result)
    except Exception as e:
        return jsonify({"answer": f"❌ Server error: {e}", "cards": []})


@app.route("/api/stats")
def stats():
    return jsonify({
        "loaded": engine.df is not None,
        "records": len(engine.df) if engine.df is not None else 0,
        "file": os.path.basename(engine.file_path) if engine.file_path else None,
    })


@app.route("/debug")
def debug_info():
    """Debug route to check file status on Render."""
    files = os.listdir(BASE_DIR)
    return jsonify({
        "base_dir": BASE_DIR,
        "data_file_exists": os.path.exists(data_path),
        "data_loaded": engine.df is not None,
        "records": len(engine.df) if engine.df is not None else 0,
        "files_in_dir": files,
    })


def _help_text():
    return (
        "📖 <strong>SpareX Assist – Q&A Commands:</strong>\n\n"
        "📍 <strong>Location:</strong>\n"
        '   "where is RET MOTOR"\n'
        '   "find location motor"\n\n'
        "📊 <strong>Stock Check:</strong>\n"
        '   "how many RF PROBE"\n'
        '   "stock of PIN"\n\n'
        "🏭 <strong>Vendor Info:</strong>\n"
        '   "vendor of PROBE HSS"\n'
        '   "who supplies RET MOTOR"\n\n'
        "🏗️ <strong>Project Info:</strong>\n"
        '   "which project has PIN"\n\n'
        "🧪 <strong>Test Bench:</strong>\n"
        '   "test bench for RF PROBE"\n\n'
        "🗄️ <strong>Almira Listing:</strong>\n"
        '   "what is in M03"\n\n'
        "📋 <strong>Type Filter:</strong>\n"
        '   "show all ADAPTER"\n'
        '   "all PIN"\n\n'
        "🔍 <strong>General Search:</strong>\n"
        "   Just type any keyword: motor, bearing, 12345\n\n"
        "⚙️ <strong>Other Commands:</strong>\n"
        "   stats  → Show file info & columns\n"
        "   help   → Show this help message"
    )


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
