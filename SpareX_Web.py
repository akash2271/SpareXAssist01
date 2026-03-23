"""
SpareX Web – Flask Web App for Spare Finder
=============================================
Access from any device on the same Wi-Fi at http://<PC-IP>:5000

Reuses the same intelligent Q&A engine from SpareX Assist.
"""

import os
import sys
import re
import socket

# ---------------------------------------------------------------------------
# Dependency check
# ---------------------------------------------------------------------------
try:
    import pandas as pd
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pandas", "openpyxl"])
    import pandas as pd

try:
    from flask import Flask, request, jsonify, render_template
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "flask"])
    from flask import Flask, request, jsonify, render_template

try:
    import openpyxl
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "openpyxl"])
    import openpyxl


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
                r"locate)\s+(.+)$", re.I),
     "location"),

    (re.compile(r"^(?:how\s+many|stock\s+of|quantity\s+of|count\s+of|"
                r"kitne|kitna|available\s+stock|closing\s+stock\s+of|"
                r"stock\s+check|check\s+stock)\s+(.+)$", re.I),
     "stock"),

    (re.compile(r"^(?:vendor\s+of|supplier\s+of|who\s+supplies|"
                r"who\s+is\s+the\s+vendor|manufacturer\s+of|"
                r"vendor\s+for|supplier\s+for)\s+(.+)$", re.I),
     "vendor"),

    (re.compile(r"^(?:which\s+project\s+(?:has|uses|for)|project\s+of|"
                r"project\s+for|kis\s+project)\s+(.+)$", re.I),
     "project"),

    (re.compile(r"^(?:test\s+bench\s+(?:for|of)|which\s+bench|"
                r"bench\s+for|used\s+(?:on|in|at)\s+which\s+bench)\s+(.+)$", re.I),
     "bench"),

    (re.compile(r"^(?:what\s+is\s+in|show\s+(?:all\s+in|items\s+in)|"
                r"list\s+(?:all\s+in|items\s+in)|parts\s+in)\s+(m\d+)$", re.I),
     "almira_list"),

    (re.compile(r"^(?:what\s+is\s+in|show\s+(?:all\s+in|items\s+in)|"
                r"list\s+(?:all\s+in|items\s+in)|parts\s+in)\s+"
                r"(?:zone\s+)?(00[a-dA-D])$", re.I),
     "zone_list"),

    (re.compile(r"^(?:show\s+all|list\s+all|all)\s+(.+?)(?:\s+type)?$", re.I),
     "type_filter"),

    (re.compile(r"^(?:part\s+code\s+(?:of|for)|code\s+(?:of|for)|"
                r"what\s+is\s+the\s+(?:part\s+)?code\s+(?:of|for))\s+(.+)$", re.I),
     "partcode"),

    (re.compile(r"^(?:tell\s+me\s+about|details\s+of|info\s+(?:of|about|on)|"
                r"full\s+info|show\s+details)\s+(.+)$", re.I),
     "full_info"),
]


# ---------------------------------------------------------------------------
# SpareEngine – Q&A Engine (same as desktop version)
# ---------------------------------------------------------------------------
class SpareEngine:
    """Loads spare data and performs intelligent Q&A."""

    def __init__(self):
        self.df = None
        self.file_path = None
        self.columns = []

    def load_file(self, path):
        try:
            ext = os.path.splitext(path)[1].lower()
            if ext in (".xlsx", ".xls"):
                self.df = pd.read_excel(path, engine="openpyxl")
            elif ext == ".csv":
                self.df = pd.read_csv(path)
            else:
                return False, f"Unsupported file type: {ext}"
            self.df.columns = [str(c).strip() for c in self.df.columns]
            self.columns = list(self.df.columns)
            self.file_path = path
            return True, f"Loaded {len(self.df)} spare records from {os.path.basename(path)}"
        except Exception as e:
            return False, f"Error loading file: {e}"

    def _normalize(self, text):
        return re.sub(r"\s+", " ", str(text).lower().strip())

    def _fuzzy_match(self, query, text):
        q_words = self._normalize(query).split()
        t = self._normalize(text)
        return all(w in t for w in q_words)

    def _safe_str(self, val):
        if val is None:
            return "—"
        try:
            if pd.isna(val):
                return "—"
        except (TypeError, ValueError):
            pass
        s = str(val).strip()
        return s if s else "—"

    def _get_column(self, name):
        for c in self.columns:
            if self._normalize(c) == self._normalize(name):
                return c
        return name

    def _find_parts(self, search_term, max_results=20):
        if self.df is None:
            return []
        search_lower = self._normalize(search_term)
        results = []
        seen = set()

        expanded_terms = [search_term]
        for alias_key, alias_values in KEYWORD_ALIASES.items():
            if search_lower == alias_key or search_lower in [self._normalize(v) for v in alias_values]:
                for av in alias_values:
                    if self._normalize(av) != search_lower:
                        expanded_terms.append(av)
                if alias_key != search_lower:
                    expanded_terms.append(alias_key)

        desc_col = self._get_column("DESCRIPTION")
        code_col = self._get_column("PART CODE")

        for idx, row in self.df.iterrows():
            if idx in seen:
                continue
            desc_val = self._normalize(str(row.get(desc_col, "")))
            code_val = self._normalize(str(row.get(code_col, "")))
            combined_target = desc_val + " " + code_val
            for term in expanded_terms:
                if self._fuzzy_match(term, combined_target):
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
                for term in expanded_terms:
                    if self._fuzzy_match(term, combined):
                        results.append(row.to_dict())
                        seen.add(idx)
                        break
                if len(results) >= max_results:
                    break

        return results

    def _detect_intent(self, query):
        q = query.strip()
        for pattern, intent in INTENT_PATTERNS:
            m = pattern.match(q)
            if m:
                return intent, m.group(1).strip()
        return None, q

    def smart_query(self, query):
        """Returns (answer_text, cards_list)."""
        if self.df is None:
            return "⚠️ Data file not loaded!", []

        intent, search_term = self._detect_intent(query)

        if intent == "almira_list":
            return self._answer_almira_list(search_term)
        if intent == "zone_list":
            return self._answer_zone_list(search_term)
        if intent == "type_filter":
            return self._answer_type_filter(search_term)

        parts = self._find_parts(search_term)
        if not parts:
            return f'😕 No results found for "{search_term}". Try different keywords.', []

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

    # ---------- Answer formatters ----------

    def _answer_location(self, term, parts):
        lines = []
        for p in parts[:5]:
            desc = self._safe_str(p.get(self._get_column("DESCRIPTION")))
            almira = self._safe_str(p.get(self._get_column("ALMIRA NO")))
            zone = self._safe_str(p.get(self._get_column("ZONE")))
            bin_val = self._safe_str(p.get(self._get_column("BIN")))
            location = self._safe_str(p.get(self._get_column("LOCATION")))
            lines.append(
                f"📍 <b>{desc}</b> is located at:\n"
                f"   🗄️ Almira: <b>{almira}</b> | Zone: <b>{zone}</b> | Bin: <b>{bin_val}</b>\n"
                f"   📦 Location Code: <b>{location}</b>"
            )
        answer = f'🔍 Location for "{term}":\n\n' + "\n\n".join(lines)
        if len(parts) > 5:
            answer += f"\n\n... and {len(parts) - 5} more result(s)."
        return answer, []

    def _answer_stock(self, term, parts):
        lines = []
        for p in parts[:5]:
            desc = self._safe_str(p.get(self._get_column("DESCRIPTION")))
            opening = self._safe_str(p.get(self._get_column("OPENING STOCK")))
            issued = self._safe_str(p.get(self._get_column("ISSUED")))
            recd = self._safe_str(p.get(self._get_column("RECD.")))
            closing = self._safe_str(p.get(self._get_column("CLOSING STOCK")))
            lines.append(
                f"📊 <b>{desc}</b>:\n"
                f"   Opening: {opening} | Issued: {issued} | "
                f"Received: {recd} | Closing: <b>{closing}</b>"
            )
        answer = f'📦 Stock info for "{term}":\n\n' + "\n\n".join(lines)
        if len(parts) > 5:
            answer += f"\n\n... and {len(parts) - 5} more result(s)."
        return answer, []

    def _answer_vendor(self, term, parts):
        lines = []
        for p in parts[:5]:
            desc = self._safe_str(p.get(self._get_column("DESCRIPTION")))
            vendor = self._safe_str(p.get(self._get_column("VENDOR")))
            address = self._safe_str(p.get(self._get_column("VENDOR ADDRESS")))
            lines.append(f"🏭 <b>{desc}</b>:\n   Vendor: <b>{vendor}</b> ({address})")
        answer = f'🏢 Vendor info for "{term}":\n\n' + "\n\n".join(lines)
        if len(parts) > 5:
            answer += f"\n\n... and {len(parts) - 5} more result(s)."
        return answer, []

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
            answer = f"📌 <b>{desc_name}</b> is found in:\n\n   🏗️ {proj_list}"
        else:
            answer = f'😕 No project information found for "{term}".'
        return answer, []

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
            answer = f"🔬 <b>{desc_name}</b> is used on:\n\n   🧪 {bench_list}"
        else:
            answer = f'😕 No test bench information found for "{term}".'
        return answer, []

    def _answer_partcode(self, term, parts):
        lines = []
        for p in parts[:5]:
            desc = self._safe_str(p.get(self._get_column("DESCRIPTION")))
            code = self._safe_str(p.get(self._get_column("PART CODE")))
            lines.append(f"🔖 <b>{desc}</b> → Part Code: <b>{code}</b>")
        answer = f'🏷️ Part code for "{term}":\n\n' + "\n".join(lines)
        return answer, []

    def _answer_full_info(self, term, parts):
        count = min(len(parts), 5)
        answer = f'🔍 Found <b>{len(parts)}</b> result(s) for "{term}":'
        cards = []
        for p in parts[:count]:
            card = {}
            for key in ["DESCRIPTION", "PART CODE", "PROJECT", "ALMIRA NO",
                         "ZONE", "BIN", "LOCATION", "CLOSING STOCK",
                         "TEST BENCH", "VENDOR", "VENDOR ADDRESS", "TYPE"]:
                col = self._get_column(key)
                val = self._safe_str(p.get(col))
                if val != "—":
                    card[key] = val
            cards.append(card)
        return answer, cards

    def _answer_almira_list(self, almira_code):
        if self.df is None:
            return "⚠️ Data file not loaded!", []
        almira_col = self._get_column("ALMIRA NO")
        code_upper = almira_code.upper()
        matches = self.df[self.df[almira_col].astype(str).str.strip().str.upper() == code_upper]
        if matches.empty:
            return f'😕 No items found in Almira <b>{code_upper}</b>.', []
        desc_col = self._get_column("DESCRIPTION")
        zone_col = self._get_column("ZONE")
        bin_col = self._get_column("BIN")
        lines = []
        for _, row in matches.head(15).iterrows():
            desc = self._safe_str(row.get(desc_col))
            zone = self._safe_str(row.get(zone_col))
            bin_val = self._safe_str(row.get(bin_col))
            lines.append(f"  • {desc}  (Zone: {zone}, {bin_val})")
        answer = f"🗄️ Items in Almira <b>{code_upper}</b> ({len(matches)} total):\n\n" + "\n".join(lines)
        if len(matches) > 15:
            answer += f"\n\n... and {len(matches) - 15} more."
        return answer, []

    def _answer_zone_list(self, zone_code):
        if self.df is None:
            return "⚠️ Data file not loaded!", []
        zone_col = self._get_column("ZONE")
        code_upper = zone_code.upper()
        matches = self.df[self.df[zone_col].astype(str).str.strip().str.upper() == code_upper]
        if matches.empty:
            return f'😕 No items found in Zone <b>{code_upper}</b>.', []
        desc_col = self._get_column("DESCRIPTION")
        almira_col = self._get_column("ALMIRA NO")
        bin_col = self._get_column("BIN")
        lines = []
        for _, row in matches.head(15).iterrows():
            desc = self._safe_str(row.get(desc_col))
            almira = self._safe_str(row.get(almira_col))
            bin_val = self._safe_str(row.get(bin_col))
            lines.append(f"  • {desc}  (Almira: {almira}, {bin_val})")
        answer = f"🏷️ Items in Zone <b>{code_upper}</b> ({len(matches)} total):\n\n" + "\n".join(lines)
        if len(matches) > 15:
            answer += f"\n\n... and {len(matches) - 15} more."
        return answer, []

    def _answer_type_filter(self, type_term):
        if self.df is None:
            return "⚠️ Data file not loaded!", []
        type_col = self._get_column("TYPE")
        term_lower = self._normalize(type_term)
        matches = self.df[self.df[type_col].astype(str).apply(self._normalize) == term_lower]
        if matches.empty:
            mask = self.df[type_col].astype(str).apply(lambda x: self._fuzzy_match(type_term, x))
            matches = self.df[mask]
        if matches.empty:
            return f'😕 No items found with type "{type_term}".', []
        desc_col = self._get_column("DESCRIPTION")
        loc_col = self._get_column("LOCATION")
        lines = []
        for _, row in matches.head(15).iterrows():
            desc = self._safe_str(row.get(desc_col))
            loc = self._safe_str(row.get(loc_col))
            lines.append(f"  • {desc}  (Location: {loc})")
        answer = (
            f'📋 All <b>{type_term.upper()}</b> type items ({len(matches)} total):\n\n'
            + "\n".join(lines)
        )
        if len(matches) > 15:
            answer += f"\n\n... and {len(matches) - 15} more."
        return answer, []

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
            f'🔍 Found <b>{len(parts)}</b> result(s) for "{term}":\n\n'
            f"📌 <b>{desc}</b>\n"
            f"   📍 Location: Almira <b>{almira}</b> | Zone <b>{zone}</b> | <b>{bin_val}</b>\n"
            f"   📦 Location Code: <b>{location}</b>\n"
            f"   📊 Closing Stock: <b>{closing}</b>\n"
            f"   🏗️ Project: {project}\n"
            f"   🏷️ Part Code: {part_code}\n"
            f"   🏭 Vendor: {vendor}"
        )
        if bench != "—":
            answer += f"\n   🧪 Test Bench: {bench}"

        cards = []
        if len(parts) > 1:
            answer += "\n\n--- More results ---"
            for p in parts[1:6]:
                card = {}
                for key in ["DESCRIPTION", "PART CODE", "PROJECT", "ALMIRA NO",
                             "ZONE", "BIN", "LOCATION", "CLOSING STOCK",
                             "TEST BENCH", "VENDOR", "TYPE"]:
                    col = self._get_column(key)
                    val = self._safe_str(p.get(col))
                    if val != "—":
                        card[key] = val
                cards.append(card)
        return answer, cards


# ---------------------------------------------------------------------------
# Flask App
# ---------------------------------------------------------------------------
def get_local_ip():
    """Get the local IP address for LAN access."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


# Determine base directory
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static"),
)

engine = SpareEngine()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/query", methods=["POST"])
def api_query():
    data = request.get_json()
    query = data.get("query", "").strip()

    if not query:
        return jsonify({"answer": "⚠️ Please enter a question.", "cards": []})

    q_lower = query.lower().strip()

    if q_lower in ("help", "commands", "?"):
        help_text = (
            "📖 <b>SpareX Assist – Q&A Commands:</b>\n\n"
            '📍 <b>Location:</b>  "where is RET MOTOR"\n'
            '📊 <b>Stock:</b>  "how many RF PROBE"\n'
            '🏭 <b>Vendor:</b>  "vendor of PROBE HSS"\n'
            '🏗️ <b>Project:</b>  "which project has PIN"\n'
            '🧪 <b>Test Bench:</b>  "test bench for RF PROBE"\n'
            '🗄️ <b>Almira List:</b>  "what is in M03"\n'
            '📋 <b>Type Filter:</b>  "show all ADAPTER"\n'
            '🔍 <b>General:</b>  just type any keyword like "motor"\n\n'
            "⚙️ <b>Other:</b>  stats, preview, help"
        )
        return jsonify({"answer": help_text, "cards": []})

    if q_lower in ("stats", "info", "status"):
        if engine.df is None:
            return jsonify({"answer": "No file loaded.", "cards": []})
        stats = (
            f"📁 File: {os.path.basename(engine.file_path)}\n"
            f"📊 Total Records: {len(engine.df)}\n"
            f"📋 Columns ({len(engine.columns)}): {', '.join(engine.columns)}"
        )
        return jsonify({"answer": stats, "cards": []})

    if q_lower in ("preview", "show data", "sample"):
        if engine.df is None:
            return jsonify({"answer": "No file loaded.", "cards": []})
        preview = engine.df.head(5).to_string(index=False)
        return jsonify({"answer": f"📄 First 5 rows preview:\n{preview}", "cards": []})

    answer, cards = engine.smart_query(query)
    return jsonify({"answer": answer, "cards": cards})


@app.route("/api/status")
def api_status():
    if engine.df is not None:
        return jsonify({
            "loaded": True,
            "records": len(engine.df),
            "file": os.path.basename(engine.file_path),
        })
    return jsonify({"loaded": False})


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Auto-load Excel
    filename = "Tester Spares Master File 2025-2026 1.xlsx"
    filepath = os.path.join(BASE_DIR, filename)

    if os.path.exists(filepath):
        ok, msg = engine.load_file(filepath)
        print("[OK] " + msg)
    else:
        print("[ERROR] Excel file not found: " + filepath)
        print("   Please place '{}' in: {}".format(filename, BASE_DIR))

    local_ip = get_local_ip()
    print("")
    print("=" * 55)
    print("  SpareX Web is running!")
    print("  PC:    http://localhost:5000")
    print("  Phone: http://{}:5000".format(local_ip))
    # Ngrok Public URL
    try:
        from pyngrok import ngrok, conf
        
        # Set auth token
        user_token = "39rw2rj7FbowoIgVpGjCPLT0r3f_AuewXp3sfBKMDzBboQna"
        conf.get_default().auth_token = user_token

        # Open a tunnel on port 5000
        public_url = ngrok.connect(5000).public_url
        print("  [Public] " + public_url)
    except Exception as e:
        print("  [Note] Public URL failed: " + str(e))

    print("=" * 55)
    print("")

    app.run(host="0.0.0.0", port=5000, debug=False)
