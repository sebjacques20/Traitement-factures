"""
Traitement de facture v2.0
c 2026 Sedentaire.co
"""
import customtkinter as ctk
from tkinter import filedialog, messagebox
import anthropic, base64, json, os, re, io, threading, webbrowser, datetime, sys, ctypes
import urllib.request, subprocess
from pathlib import Path

# Répertoire du script — chemin absolu, robuste peu importe d'où on le lance
BASE_DIR = Path(__file__).parent

def load_fonts():
    """Charge les polices Coolvetica (Windows: GDI, macOS: CoreText)."""
    font_names = [
        "Coolvetica Rg.otf",
        "Coolvetica Rg Lt.otf",
        "Coolvetica Rg Cond.otf",
        "Coolvetica Rg Cram.otf",
        "Coolvetica Hv Comp.otf",
    ]
    if sys.platform == "win32":
        FR_PRIVATE = 0x10
        for fname in font_names:
            p = BASE_DIR / fname
            if p.exists():
                ctypes.windll.gdi32.AddFontResourceExW(str(p), FR_PRIVATE, 0)
    elif sys.platform == "darwin":
        try:
            import ctypes.util
            ct = ctypes.cdll.LoadLibrary(ctypes.util.find_library("CoreText"))
            cf = ctypes.cdll.LoadLibrary(ctypes.util.find_library("CoreFoundation"))
            # CFStringCreateWithCString
            cf.CFStringCreateWithCString.restype = ctypes.c_void_p
            cf.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
            # CFURLCreateWithFileSystemPath
            cf.CFURLCreateWithFileSystemPath.restype = ctypes.c_void_p
            cf.CFURLCreateWithFileSystemPath.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int32, ctypes.c_bool]
            # CTFontManagerRegisterFontsForURL
            ct.CTFontManagerRegisterFontsForURL.restype = ctypes.c_bool
            ct.CTFontManagerRegisterFontsForURL.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p]
            kCFStringEncodingUTF8 = 0x08000100
            kCFURLPOSIXPathStyle = 0
            kCTFontManagerScopeProcess = 1
            for fname in font_names:
                p = BASE_DIR / fname
                if p.exists():
                    path_str = str(p).encode("utf-8")
                    cf_str = cf.CFStringCreateWithCString(None, path_str, kCFStringEncodingUTF8)
                    cf_url = cf.CFURLCreateWithFileSystemPath(None, cf_str, kCFURLPOSIXPathStyle, False)
                    ct.CTFontManagerRegisterFontsForURL(cf_url, kCTFontManagerScopeProcess, None)
        except Exception:
            pass  # Polices non chargées — fallback sur les polices système

from collections import Counter
from pypdf import PdfReader, PdfWriter
from pdf2image import convert_from_path

try:
    import keyring
    KEYRING_OK = True
except ImportError:
    KEYRING_OK = False

APP_NAME    = "Traitement de facture"
APP_VERSION = "2.0"
BRAND       = "sedentaire.co"
CONTACT_URL = "mailto:info@sedentaire.co"
CONSOLE_URL = "https://console.anthropic.com/settings/keys"
UPDATE_URL  = "https://sedentaire.co/apps/traitement-facture/version.json"
KEYRING_SVC = "TraitementFacture"
KEYRING_USR = "anthropic_api_key"
CONFIG_FILE = Path.home() / ".traitement_facture_v2.json"

BG         = "#FFFFFF"   # fond blanc
SURFACE    = "#F5F5F5"   # header / footer
CARD       = "#FAFAFA"   # cartes
INP        = "#F0F0F0"   # champs de saisie
BORDER     = "#E0E0E0"   # bordures
ACCENT     = "#ED307E"   # rose Sédentaire — CTA primaire
ACCENT2    = "#C42068"   # rose foncé — hover
ACCENT_DIM = "#FDEAF3"   # rose très pâle — badges, fonds teintés
YELLOW     = "#FFEE00"   # jaune Sédentaire — secondaire
YELLOW2    = "#FDC000"   # jaune doré — hover secondaire
YELLOW_DIM = "#FFFCE0"   # jaune très pâle
TEAL       = "#00A878"   # succès (vert sobre, lisible sur blanc)
RED_C      = "#E8304A"
AMBER_C    = "#FDC000"
T1         = "#000000"   # texte principal — noir pur
T2         = "#444444"   # texte secondaire
T3         = "#888888"   # texte muet
R_CARD     = 16
R_BTN      = 12
R_INP      = 12

DPI    = 150
JPEG_Q = 82

PROMPT = """Analyse cette page d'un scan de facture de construction. Reponds UNIQUEMENT en JSON.

1. type_page: "facture" (page avec entete fournisseur, TPS/TVQ, total) ou "feuille_route" (feuille de travail, bon de livraison, annexe)
2. fournisseur: nom commercial court du fournisseur, sans numeros corporatifs ni adresse. Ex: "Rona", "BMR", "Plomberie ABC"
3. numero_commande: le numero de PROJET ou BON DE COMMANDE du CLIENT (pas le numero interne du fournisseur).
   PRIORITE 1 : regarde EN PREMIER les annotations manuscrites, tampons, ecritures au stylo, cases cochees a la main.
   Le numero de projet est SOUVENT ecrit a la main sur la facture par le client. C'est la source la plus fiable.
   PRIORITE 2 : cherche dans les champs imprimes: "Bon de commande", "PO", "PO #", "N commande", "Order #", "Order number", "No projet", "Projet", "Project", "Job #", "Chantier".
   Typiquement 3-6 chiffres (ex: "1090", "2547", "890"). Si le numero commence par "0" (ex: "090"), ajoute un "1" devant → "1090".
   IMPORTANT: ce n'est PAS le numero de facture du fournisseur. null si absent.
4. numero_facture: numero de facture du FOURNISSEUR. Cherche dans: "Facture #", "Facture no", "N facture", "Invoice #", "Invoice no", numero en haut a droite du document.
5. date: date de la facture au format AAAA-MM-JJ, null si absent

JSON strict: {"type_page":"facture","fournisseur":"Nom","numero_commande":"1090","numero_facture":"AR26-0715","date":"2026-02-28"}"""


def load_config():
    if CONFIG_FILE.exists():
        try: return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception: return {}
    return {}

def save_config(c):
    try: CONFIG_FILE.write_text(json.dumps(c), encoding="utf-8")
    except Exception: pass

def get_api_key():
    if KEYRING_OK:
        try:
            k = keyring.get_password(KEYRING_SVC, KEYRING_USR)
            if k: return k
        except Exception: pass
    return load_config().get("api_key_fallback", "")

def set_api_key(key):
    if KEYRING_OK:
        try: keyring.set_password(KEYRING_SVC, KEYRING_USR, key); return
        except Exception: pass
    c = load_config(); c["api_key_fallback"] = key; save_config(c)

def img_b64(img):
    buf = io.BytesIO(); img.save(buf, format="JPEG", quality=JPEG_Q)
    return base64.b64encode(buf.getvalue()).decode("utf-8")

def clean(name):
    if not name: return "INCONNU"
    n = re.sub(r'[<>:"/\\|?*\n\r\t]', "", str(name)).strip(". ")
    return n if n else "INCONNU"

def norm_po(po):
    if not po: return None
    po = str(po).strip()
    po2 = po.replace("O","0").replace("o","0").replace("l","1").replace("I","1").replace("S","5")
    if re.match(r'^[0-9]{3,8}$', po2) and po2 != po: po = po2
    L = re.findall(r'[A-Za-z]', po); D = re.findall(r'[0-9]', po)
    if len(L) > len(D): return None
    if len(po) > 8 and L: return None
    if re.match(r'^[0-9]+$', po) and (len(po)<3 or len(po)>8): return None
    return po

def analyze(client, b64):
    try:
        r = client.messages.create(
            model="claude-sonnet-4-20250514", max_tokens=300,
            messages=[{"role":"user","content":[
                {"type":"image","source":{"type":"base64","media_type":"image/jpeg","data":b64}},
                {"type":"text","text":PROMPT}]}])
        raw = r.content[0].text.strip()
        m = re.search(r'\{[^{}]+\}', raw, re.DOTALL)
        if m: raw = m.group(0)
        d = json.loads(raw.strip())
        if d.get("type_page") not in ("facture","feuille_route"): d["type_page"]="feuille_route"
        return d
    except Exception:
        return {"type_page":"feuille_route","fournisseur":None,"numero_commande":None,"numero_facture":None,"date":None}

def build_groups(pages):
    groups, cur = [], None
    for d in pages:
        if d["type_page"] == "facture":
            if cur: groups.append(cur)
            cur = {"pages":[d["page_idx"]],"fournisseur":d.get("fournisseur"),
                   "numero_commande":d.get("numero_commande"),"numero_facture":d.get("numero_facture"),
                   "date":d.get("date"),
                   "_po":[d["numero_commande"]] if d.get("numero_commande") else [],
                   "_fr":[d["fournisseur"]] if d.get("fournisseur") else []}
        else:
            if not cur:
                cur = {"pages":[d["page_idx"]],"fournisseur":d.get("fournisseur"),
                       "numero_commande":d.get("numero_commande"),"numero_facture":d.get("numero_facture"),
                       "date":d.get("date"),
                       "_po":[d["numero_commande"]] if d.get("numero_commande") else [],
                       "_fr":[d["fournisseur"]] if d.get("fournisseur") else []}
            else:
                cur["pages"].append(d["page_idx"])
                if d.get("numero_commande"): cur["_po"].append(d["numero_commande"])
                if d.get("fournisseur"): cur["_fr"].append(d["fournisseur"])
                if not cur.get("date") and d.get("date"): cur["date"] = d["date"]
    if cur: groups.append(cur)
    for g in groups:
        if not g["numero_commande"] and g["_po"]:
            g["numero_commande"] = Counter(g["_po"]).most_common(1)[0][0]
        if not g["fournisseur"] and g["_fr"]:
            g["fournisseur"] = Counter(g["_fr"]).most_common(1)[0][0]
    all_pos = [g["numero_commande"] for g in groups if g["numero_commande"]]
    if all_pos:
        dp, dc = Counter(all_pos).most_common(1)[0]
        if dc/len(groups) >= 0.5:
            for g in groups:
                if not g["numero_commande"]: g["numero_commande"] = dp
    return groups

def mk_fname(g, opts):
    p = []
    if opts.get("f"): p.append(clean(g.get("fournisseur")))
    if opts.get("p"): p.append(clean(g.get("numero_commande")))
    if opts.get("n"): p.append(clean(g.get("numero_facture")))
    if opts.get("d") and g.get("date"): p.append(clean(g["date"]))
    return " - ".join(p)+".pdf" if p else "INCONNU.pdf"

def poppler_path():
    if getattr(sys, "frozen", False):
        b = Path(sys._MEIPASS) / "poppler" / "bin"
        if b.exists():
            # Sur Mac, les dylibs sont dans poppler/lib — ajouter au DYLD path
            if sys.platform == "darwin":
                lib_dir = Path(sys._MEIPASS) / "poppler" / "lib"
                if lib_dir.exists():
                    existing = os.environ.get("DYLD_LIBRARY_PATH", "")
                    os.environ["DYLD_LIBRARY_PATH"] = str(lib_dir) + (":" + existing if existing else "")
            return str(b)
    if sys.platform == "win32":
        for c in [r"C:\poppler\poppler-25.12.0\Library\bin", r"C:\poppler\Library\bin"]:
            if os.path.exists(c):
                return c
    elif sys.platform == "darwin":
        # Homebrew Intel ou Apple Silicon
        for c in ["/opt/homebrew/bin", "/usr/local/bin"]:
            if os.path.exists(os.path.join(c, "pdftoppm")):
                return c
    return None



# ── Auto-updater ─────────────────────────────────────────────────────────────

def fetch_update_info():
    """Interroge version.json. Retourne le dict si une nouvelle version existe, sinon None.
    Note : en mode frozen (PyInstaller), la mise à jour automatique n'est pas supportée —
    on notifie simplement l'utilisateur avec un lien de téléchargement."""
    try:
        req = urllib.request.Request(UPDATE_URL, headers={"User-Agent": f"{APP_NAME}/{APP_VERSION}"})
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.loads(r.read().decode("utf-8"))
        remote = data.get("version", "0")
        if tuple(int(x) for x in remote.split(".")) > tuple(int(x) for x in APP_VERSION.split(".")):
            return data
    except Exception:
        pass
    return None


class UpdateBanner(ctk.CTkFrame):
    """Bannière verte sous le header quand une mise à jour est disponible."""
    def __init__(self, parent, info):
        super().__init__(parent, fg_color="#E6F7F2", corner_radius=0, border_width=0)
        self._info = info

        inner = ctk.CTkFrame(self, fg_color="transparent")
        inner.pack(fill="x", padx=16, pady=8)

        self._dot = ctk.CTkLabel(inner, text="●", font=ctk.CTkFont(size=10),
                                 text_color="#00A878", width=14)
        self._dot.pack(side="left", padx=(0, 8))
        self._blink(True)

        txt_frame = ctk.CTkFrame(inner, fg_color="transparent")
        txt_frame.pack(side="left", fill="x", expand=True)
        v = info.get("version", "?")
        ctk.CTkLabel(txt_frame,
            text=f"Mise à jour disponible — v{v}",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#00534A", anchor="w").pack(anchor="w")
        short = (info.get("changelog") or [""])
        ctk.CTkLabel(txt_frame,
            text=short[0] if short else "",
            font=ctk.CTkFont(size=11), text_color="#00705A", anchor="w").pack(anchor="w")

        btns = ctk.CTkFrame(inner, fg_color="transparent")
        btns.pack(side="right", padx=(10, 0))
        dl_url = info.get("download_url", "https://github.com/sebjacques20/Traitement-factures/releases/latest")
        ctk.CTkButton(btns, text="Télécharger",
            fg_color="#00A878", hover_color="#007A58", text_color="#FFFFFF",
            height=30, corner_radius=8, font=ctk.CTkFont(size=12, weight="bold"),
            command=lambda: webbrowser.open(dl_url)).pack(side="left", padx=(0, 6))
        ctk.CTkButton(btns, text="Plus tard",
            fg_color="transparent", hover_color="#C8EDE3", text_color="#00705A",
            height=30, corner_radius=8, font=ctk.CTkFont(size=12),
            command=self.pack_forget).pack(side="left")

        ctk.CTkFrame(self, fg_color="#B2E4D6", height=1, corner_radius=0).pack(fill="x", side="bottom")

    def _blink(self, visible):
        self._dot.configure(text_color="#00A878" if visible else "#C8EDE3")
        self.after(800, lambda: self._blink(not visible))

# ─────────────────────────────────────────────────────────────────────────────


class ReviewDialog(ctk.CTkToplevel):
    """Fenêtre de révision : permet de modifier les noms avant la sauvegarde."""

    def __init__(self, parent, groups, opts):
        super().__init__(parent)
        self.title("Révision avant sauvegarde")
        self.geometry("780x560")
        self.resizable(True, True)
        self.minsize(680, 420)
        self.configure(fg_color=BG)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self._groups = groups
        self._opts = opts
        self._result = None  # None = annulé, list = groupes modifiés
        self._entries = []   # liste de dicts {fournisseur, commande, facture, date}

        # Header
        hdr = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=0, height=54)
        hdr.pack(fill="x"); hdr.pack_propagate(False)
        ctk.CTkLabel(hdr, text="Vérifiez et modifiez les noms de fichiers",
            font=ctk.CTkFont(size=14, weight="bold"), text_color=T1).pack(side="left", padx=18)
        n_inconnu = sum(1 for g in groups if not g.get("fournisseur") or not g.get("numero_commande"))
        if n_inconnu:
            ctk.CTkLabel(hdr, text=f"{n_inconnu} INCONNU",
                font=ctk.CTkFont(size=11, weight="bold"), text_color="#FFFFFF",
                fg_color=RED_C, corner_radius=12, width=90, height=24).pack(side="right", padx=18)
        ctk.CTkFrame(self, fg_color=ACCENT, height=2, corner_radius=0).pack(fill="x")

        # Scrollable body
        body = ctk.CTkScrollableFrame(self, fg_color=BG, scrollbar_button_color=BORDER)
        body.pack(fill="both", expand=True, padx=12, pady=(10, 0))

        for i, g in enumerate(groups):
            row_fg = CARD if i % 2 == 0 else BG
            has_inconnu = not g.get("fournisseur") or not g.get("numero_commande")
            border_c = RED_C if has_inconnu else BORDER

            card = ctk.CTkFrame(body, fg_color=row_fg, corner_radius=8,
                border_width=1, border_color=border_c)
            card.pack(fill="x", padx=4, pady=3)

            # Ligne 1 : # + Fournisseur + Commande + Facture + Date + Pages
            row1 = ctk.CTkFrame(card, fg_color="transparent")
            row1.pack(fill="x", padx=8, pady=(6, 0))

            ctk.CTkLabel(row1, text=str(i + 1), font=ctk.CTkFont(size=12, weight="bold"),
                text_color=T2, width=24).pack(side="left")

            ctk.CTkLabel(row1, text="Fourn.", font=ctk.CTkFont(size=10), text_color=T3).pack(side="left", padx=(6, 2))
            f_var = ctk.StringVar(value=g.get("fournisseur") or "")
            ctk.CTkEntry(row1, textvariable=f_var, font=ctk.CTkFont(size=12),
                fg_color=INP, border_color=RED_C if not g.get("fournisseur") else BORDER,
                border_width=1, text_color=T1, height=32, width=130, corner_radius=6,
                placeholder_text="INCONNU").pack(side="left", padx=(0, 2))

            ctk.CTkLabel(row1, text="PO", font=ctk.CTkFont(size=10), text_color=T3).pack(side="left", padx=(4, 2))
            p_var = ctk.StringVar(value=g.get("numero_commande") or "")
            ctk.CTkEntry(row1, textvariable=p_var, font=ctk.CTkFont(size=12),
                fg_color=INP, border_color=RED_C if not g.get("numero_commande") else BORDER,
                border_width=1, text_color=T1, height=32, width=90, corner_radius=6,
                placeholder_text="—").pack(side="left", padx=(0, 2))

            ctk.CTkLabel(row1, text="Fact.", font=ctk.CTkFont(size=10), text_color=T3).pack(side="left", padx=(4, 2))
            n_var = ctk.StringVar(value=g.get("numero_facture") or "")
            ctk.CTkEntry(row1, textvariable=n_var, font=ctk.CTkFont(size=12),
                fg_color=INP, border_color=BORDER, border_width=1,
                text_color=T1, height=32, width=100, corner_radius=6,
                placeholder_text="—").pack(side="left", padx=(0, 2))

            ctk.CTkLabel(row1, text="Date", font=ctk.CTkFont(size=10), text_color=T3).pack(side="left", padx=(4, 2))
            d_var = ctk.StringVar(value=g.get("date") or "")
            ctk.CTkEntry(row1, textvariable=d_var, font=ctk.CTkFont(size=12),
                fg_color=INP, border_color=BORDER, border_width=1,
                text_color=T1, height=32, width=90, corner_radius=6,
                placeholder_text="—").pack(side="left", padx=(0, 4))

            pages_txt = f"p.{','.join(str(p+1) for p in g['pages'])}"
            ctk.CTkLabel(row1, text=pages_txt, font=ctk.CTkFont(size=10),
                text_color=T3).pack(side="right", padx=(4, 4))

            # Ligne 2 : Lieu (sous-dossier de destination)
            row2 = ctk.CTkFrame(card, fg_color="transparent")
            row2.pack(fill="x", padx=8, pady=(2, 6))

            ctk.CTkLabel(row2, text="", width=24).pack(side="left")  # spacer
            ctk.CTkLabel(row2, text="Lieu :", font=ctk.CTkFont(size=11),
                text_color=T2).pack(side="left", padx=(6, 4))
            lieu_var = ctk.StringVar(value="")
            ctk.CTkEntry(row2, textvariable=lieu_var, font=ctk.CTkFont(size=12),
                fg_color=INP, border_color=BORDER, border_width=1,
                text_color=T1, height=32, corner_radius=6,
                placeholder_text="Sous-dossier (optionnel, ex: Chantier Nord)").pack(side="left", fill="x", expand=True, padx=(0, 4))

            self._entries.append({"f": f_var, "p": p_var, "n": n_var, "d": d_var, "lieu": lieu_var})

        # Footer buttons
        footer = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=0)
        footer.pack(fill="x", side="bottom", pady=0)
        ctk.CTkFrame(self, fg_color=BORDER, height=1, corner_radius=0).pack(fill="x", side="bottom")
        btn_row = ctk.CTkFrame(footer, fg_color="transparent")
        btn_row.pack(fill="x", padx=16, pady=12)
        ctk.CTkButton(btn_row, text="Annuler",
            fg_color=INP, hover_color=BORDER, text_color=T2,
            border_color=BORDER, border_width=1,
            height=42, width=120, corner_radius=R_BTN, command=self._cancel).pack(side="left")
        ctk.CTkButton(btn_row, text="Sauvegarder les fichiers",
            fg_color=ACCENT, hover_color=ACCENT2, text_color="#FFFFFF",
            font=ctk.CTkFont(size=13, weight="bold"),
            height=42, corner_radius=R_BTN, command=self._confirm).pack(side="right")

    def _confirm(self):
        for i, e in enumerate(self._entries):
            self._groups[i]["fournisseur"] = e["f"].get().strip() or None
            self._groups[i]["numero_commande"] = e["p"].get().strip() or None
            self._groups[i]["numero_facture"] = e["n"].get().strip() or None
            self._groups[i]["date"] = e["d"].get().strip() or None
            self._groups[i]["lieu"] = e["lieu"].get().strip() or None
        self._result = self._groups
        self.destroy()

    def _cancel(self):
        self._result = None
        self.destroy()


class DisclaimerDlg(ctk.CTkToplevel):
    """Fenêtre modale : conditions d'utilisation (première ouverture)."""

    def __init__(self, parent, on_ok, on_no):
        super().__init__(parent)
        self.on_ok = on_ok; self.on_no = on_no
        self.title("Conditions d'utilisation")
        self.geometry("560x560"); self.resizable(False,False)
        self.configure(fg_color=SURFACE); self.grab_set()
        self.protocol("WM_DELETE_WINDOW", on_no)

        # Header
        hdr = ctk.CTkFrame(self, fg_color=CARD, corner_radius=0, height=60)
        hdr.pack(fill="x"); hdr.pack_propagate(False)
        ctk.CTkLabel(hdr, text=APP_NAME, font=ctk.CTkFont("Coolvetica",15,"bold"), text_color=T1).pack(side="left",padx=20)
        badge = ctk.CTkLabel(hdr, text="Première utilisation",
            font=ctk.CTkFont(size=11), text_color=T1,
            fg_color=YELLOW, corner_radius=20, width=130, height=24)
        badge.pack(side="right", padx=20)
        ctk.CTkFrame(self, fg_color=ACCENT, height=2, corner_radius=0).pack(fill="x")

        txt = ctk.CTkTextbox(self, fg_color=INP, text_color=T2, font=ctk.CTkFont("Courier New",12),
            border_color=BORDER, border_width=1, corner_radius=0)
        txt.pack(fill="both", expand=True, padx=0, pady=0)
        txt.insert("end",
f"""{APP_NAME.upper()} v{APP_VERSION}
(c) 2026 Sedentaire.co. Tous droits reserves.

PROPRIETE INTELLECTUELLE
Cette application est la propriete exclusive de Sedentaire.co.
Toute reproduction sans autorisation ecrite est interdite.

DONNEES ET CONFIDENTIALITE
- Vos PDF sont traites LOCALEMENT sur votre ordinateur.
- Les pages sont envoyees a l'API Anthropic pour analyse IA.
- Sedentaire.co n'a AUCUN acces a vos fichiers.
- Votre cle API est stockee de facon securisee sur votre ordinateur.
- Aucune donnee n'est envoyee a Sedentaire.co.

ANTHROPIC
Les appels API ne sont PAS utilises pour entrainer les modeles.
Politique: anthropic.com/privacy

RESPONSABILITE
Fournie "telle quelle". Sedentaire.co n'est pas responsable
des erreurs de reconnaissance ou dommages eventuels.
""")
        txt.configure(state="disabled")

        btm = ctk.CTkFrame(self, fg_color=SURFACE)
        btm.pack(fill="x", padx=20, pady=(12,18))
        self.chk_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(btm, text="J'ai lu et j'accepte les conditions d'utilisation",
            variable=self.chk_var, font=ctk.CTkFont(size=13), text_color=T1,
            fg_color=ACCENT, hover_color=ACCENT2, border_color=BORDER,
            corner_radius=6, command=self._toggle).pack(anchor="w", pady=(0,12))
        r = ctk.CTkFrame(btm, fg_color="transparent"); r.pack(fill="x")
        ctk.CTkButton(r, text="Refuser et quitter", fg_color=INP, hover_color=BORDER,
            text_color=T2, border_color=BORDER, border_width=1,
            height=42, corner_radius=R_BTN, command=on_no).pack(side="left")
        self.btn = ctk.CTkButton(r, text="Accepter et continuer",
            fg_color=BORDER, text_color=T3, height=42, corner_radius=R_BTN,
            state="disabled", command=self._ok)
        self.btn.pack(side="right")

    def _toggle(self):
        if self.chk_var.get(): self.btn.configure(state="normal", fg_color=ACCENT, text_color="#FFFFFF")
        else: self.btn.configure(state="disabled", fg_color=BORDER, text_color=T3)

    def _ok(self):
        self.destroy(); self.on_ok()


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("light")
        ctk.set_default_color_theme("dark-blue")
        self.title(APP_NAME); self.geometry("740x800"); self.minsize(640,680)
        self.configure(fg_color=BG)
        self.cfg = load_config(); self.pdfs = []; self.processing = False
        self._cancel = False; self.logs = []
        self._update_info = None   # rempli par le thread de vérification

        if not self.cfg.get("disclaimer_accepted"):
            self.withdraw()
            self.after(200, lambda: DisclaimerDlg(self, self._accept, self.destroy))
        else:
            self._ui()
        # Vérification de mise à jour en arrière-plan (silencieux)
        threading.Thread(target=self._check_update, daemon=True).start()

    def _accept(self):
        self.cfg["disclaimer_accepted"] = True; save_config(self.cfg)
        self.deiconify(); self._ui()

    def _check_update(self):
        """Thread background : vérifie silencieusement la disponibilité d'une mise à jour."""
        info = fetch_update_info()
        if info:
            self._update_info = info
            self.after(0, self._show_update_banner)

    def _show_update_banner(self):
        """Insère la bannière de mise à jour juste sous le header, si l'UI est prête."""
        if not self._update_info:
            return
        # Cherche le frame header (1er widget packed) pour insérer après
        try:
            banner = UpdateBanner(self, self._update_info)
            # On insère la bannière après la ligne orange du header
            banner.pack(fill="x", before=self.tabs)
        except Exception:
            pass

    def _ui(self):
        # ── Header ──────────────────────────────────────────────
        bar = ctk.CTkFrame(self, fg_color=SURFACE, height=62, corner_radius=0)
        bar.pack(fill="x"); bar.pack_propagate(False)

        ctk.CTkLabel(bar, text=APP_NAME,
            font=ctk.CTkFont("Coolvetica", 16, "bold"), text_color=T1).pack(side="left", padx=(18, 0))

        # Badge version
        ctk.CTkLabel(bar, text=f"v{APP_VERSION}",
            font=ctk.CTkFont(size=10, weight="bold"), text_color=T1,
            fg_color=YELLOW, corner_radius=20, width=38, height=22).pack(side="left", padx=8)

        # Brand à droite
        ctk.CTkLabel(bar, text=BRAND,
            font=ctk.CTkFont(size=11), text_color=T3).pack(side="right", padx=20)

        # Ligne orange sous le header
        ctk.CTkFrame(self, fg_color=ACCENT, height=2, corner_radius=0).pack(fill="x")

        # ── Onglets ──────────────────────────────────────────────
        self.tabs = ctk.CTkTabview(self, fg_color=BG,
            segmented_button_fg_color=SURFACE,
            segmented_button_selected_color=ACCENT,
            segmented_button_selected_hover_color=ACCENT2,
            segmented_button_unselected_color=SURFACE,
            segmented_button_unselected_hover_color=CARD,
            text_color=T2, text_color_disabled=T3)
        self.tabs.pack(fill="both", expand=True, padx=16, pady=(10, 0))
        for n in ["  Traitement  ", "  Paramètres  ", "  Aide  "]:
            self.tabs.add(n)
        self._tab_t(self.tabs.tab("  Traitement  "))
        self._tab_p(self.tabs.tab("  Paramètres  "))
        self._tab_a(self.tabs.tab("  Aide  "))

        # ── Footer ───────────────────────────────────────────────
        f = ctk.CTkFrame(self, fg_color=SURFACE, height=30, corner_radius=0)
        f.pack(fill="x", side="bottom"); f.pack_propagate(False)
        ctk.CTkLabel(f, text=f"© 2026 {BRAND}  ·  Tous droits réservés  ·  {APP_NAME} v{APP_VERSION}",
            font=ctk.CTkFont(size=10), text_color=T3).pack(expand=True)

    def _sec(self, t, p):
        f = ctk.CTkFrame(p, fg_color="transparent")
        f.pack(fill="x", padx=20, pady=(20, 8))
        ctk.CTkLabel(f, text=t.upper(),
            font=ctk.CTkFont(size=10, weight="bold"), text_color=T1,
            fg_color=YELLOW, corner_radius=20, padx=10, pady=3).pack(side="left")
        ctk.CTkFrame(f, fg_color=BORDER, height=1).pack(side="left", fill="x", expand=True, padx=(10, 0))

    # ---- TRAITEMENT ----
    def _tab_t(self, p):
        s = ctk.CTkScrollableFrame(p, fg_color=BG, scrollbar_button_color=BORDER,
            scrollbar_button_hover_color=T3)
        s.pack(fill="both", expand=True)

        # — Fichier PDF —
        self._sec("Fichier PDF", s)
        pdf_card = ctk.CTkFrame(s, fg_color=CARD, corner_radius=R_CARD,
            border_width=1, border_color=BORDER)
        pdf_card.pack(fill="x", padx=20, pady=(0, 4))
        self.pdf_lbl = ctk.CTkLabel(pdf_card,
            text="Aucun fichier sélectionné",
            font=ctk.CTkFont(size=13), text_color=T3)
        self.pdf_lbl.pack(pady=(18, 10))
        r = ctk.CTkFrame(pdf_card, fg_color="transparent"); r.pack(pady=(0, 16))
        ctk.CTkButton(r, text="  Choisir un PDF",
            fg_color=ACCENT, hover_color=ACCENT2, text_color="#FFFFFF",
            font=ctk.CTkFont(size=13, weight="bold"),
            height=42, corner_radius=R_BTN, command=self._pick).pack(side="left", padx=6)
        ctk.CTkButton(r, text="Effacer",
            fg_color=INP, hover_color=BORDER, text_color=T3,
            border_color=BORDER, border_width=1,
            height=42, corner_radius=R_BTN, command=self._clear).pack(side="left", padx=6)

        # — Dossier de sortie —
        self._sec("Dossier de sortie", s)
        fc = ctk.CTkFrame(s, fg_color=CARD, corner_radius=R_CARD,
            border_width=1, border_color=BORDER)
        fc.pack(fill="x", padx=20, pady=(0, 4))
        fr = ctk.CTkFrame(fc, fg_color="transparent"); fr.pack(fill="x", padx=16, pady=16)
        self.dir_var = ctk.StringVar(value=self.cfg.get("output_dir", str(Path.home() / "Factures triees")))
        ctk.CTkEntry(fr, textvariable=self.dir_var, font=ctk.CTkFont(size=13),
            fg_color=INP, border_color=BORDER, border_width=1,
            text_color=T1, height=42, corner_radius=R_INP).pack(side="left", fill="x", expand=True, padx=(0, 10))
        ctk.CTkButton(fr, text="Parcourir",
            fg_color=INP, hover_color=BORDER, text_color=T1,
            border_color=BORDER, border_width=1,
            height=42, width=110, corner_radius=R_BTN, command=self._dir).pack(side="right")
        self.dir_var.trace_add("write", lambda *_: self._save_dir())

        # — Options de renommage —
        self._sec("Options de renommage", s)
        oc = ctk.CTkFrame(s, fg_color=CARD, corner_radius=R_CARD,
            border_width=1, border_color=BORDER)
        oc.pack(fill="x", padx=20, pady=(0, 4))
        oi = ctk.CTkFrame(oc, fg_color="transparent"); oi.pack(fill="x", padx=16, pady=16)
        ctk.CTkLabel(oi, text="Champs inclus dans le nom du fichier :",
            font=ctk.CTkFont(size=12), text_color=T2).pack(anchor="w", pady=(0, 12))
        self.of  = ctk.BooleanVar(value=self.cfg.get("of", True))
        self.op  = ctk.BooleanVar(value=self.cfg.get("op", True))
        self.on_ = ctk.BooleanVar(value=self.cfg.get("on", True))
        self.od  = ctk.BooleanVar(value=self.cfg.get("od", False))
        or_ = ctk.CTkFrame(oi, fg_color="transparent"); or_.pack(fill="x")
        for lbl, var in [("Fournisseur", self.of), ("PO / Commande", self.op),
                         ("N\u00b0 Facture", self.on_), ("Date", self.od)]:
            ctk.CTkCheckBox(or_, text=lbl, variable=var,
                font=ctk.CTkFont(size=13), text_color=T1,
                fg_color=ACCENT, hover_color=ACCENT2, border_color=BORDER,
                corner_radius=6, command=self._save_opts).pack(side="left", padx=(0, 18))
        self.prev_lbl = ctk.CTkLabel(oi, text="",
            font=ctk.CTkFont("Courier New", 11), text_color=ACCENT2)
        self.prev_lbl.pack(anchor="w", pady=(12, 0))
        self._upd_prev()
        for v in [self.of, self.op, self.on_, self.od]:
            v.trace_add("write", lambda *_: self._upd_prev())

        # — Lancer —
        self._sec("Lancer le traitement", s)
        pc = ctk.CTkFrame(s, fg_color="transparent"); pc.pack(fill="x", padx=20, pady=(0, 4))
        pr = ctk.CTkFrame(pc, fg_color="transparent"); pr.pack(fill="x")
        self.btn_go = ctk.CTkButton(pr, text="\u25b6  Traiter le PDF",
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color=ACCENT, hover_color=ACCENT2,
            text_color="#FFFFFF", height=52, corner_radius=R_BTN, command=self._start)
        self.btn_go.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.btn_stop = ctk.CTkButton(pr, text="Annuler",
            fg_color=INP, hover_color=BORDER, text_color=T2,
            border_color=BORDER, border_width=1,
            height=52, width=120, corner_radius=R_BTN, state="disabled", command=self._do_cancel)
        self.btn_stop.pack(side="right")
        self.pgbar = ctk.CTkProgressBar(pc, fg_color=CARD, progress_color=ACCENT,
            height=5, corner_radius=4)
        self.pgbar.pack(fill="x", pady=(12, 0)); self.pgbar.set(0)
        self.stat_lbl = ctk.CTkLabel(pc, text="",
            font=ctk.CTkFont(size=12), text_color=T2)
        self.stat_lbl.pack(pady=(8, 0))

        # — Résultats —
        self._sec("R\u00e9sultats", s)
        self.res_frame = ctk.CTkFrame(s, fg_color=CARD, corner_radius=R_CARD,
            border_width=1, border_color=BORDER)
        self.res_ttl = ctk.CTkLabel(self.res_frame, text="",
            font=ctk.CTkFont(size=13, weight="bold"), text_color=TEAL)
        self.res_ttl.pack(anchor="w", padx=16, pady=(16, 8))
        self.res_box = ctk.CTkTextbox(self.res_frame, fg_color=INP, text_color=T2,
            font=ctk.CTkFont("Courier New", 12), height=180,
            border_color=BORDER, border_width=1, corner_radius=R_INP)
        self.res_box.pack(fill="x", padx=16); self.res_box.configure(state="disabled")
        rr = ctk.CTkFrame(self.res_frame, fg_color="transparent"); rr.pack(fill="x", padx=16, pady=14)
        ctk.CTkButton(rr, text="\U0001f4c2  Ouvrir le dossier",
            fg_color=INP, hover_color=BORDER, text_color=T1,
            border_color=BORDER, border_width=1,
            height=40, corner_radius=R_BTN, command=self._open_dir).pack(side="left")
        ctk.CTkButton(rr, text="Exporter le log",
            fg_color="transparent", hover_color=SURFACE, text_color=T3,
            height=40, corner_radius=R_BTN, command=self._export).pack(side="right")

    # ---- PARAMETRES ----
    def _tab_p(self, p):
        s = ctk.CTkScrollableFrame(p, fg_color=BG, scrollbar_button_color=BORDER,
            scrollbar_button_hover_color=T3)
        s.pack(fill="both", expand=True)

        # — Clé API —
        self._sec("Cl\u00e9 API Anthropic", s)
        c = ctk.CTkFrame(s, fg_color=CARD, corner_radius=R_CARD,
            border_width=1, border_color=BORDER)
        c.pack(fill="x", padx=20, pady=(0, 4))
        r = ctk.CTkFrame(c, fg_color="transparent"); r.pack(fill="x", padx=16, pady=(16, 6))
        self.api_var = ctk.StringVar(value=get_api_key())
        self.api_ent = ctk.CTkEntry(r, textvariable=self.api_var, show="*",
            placeholder_text="sk-ant-...", font=ctk.CTkFont(size=13),
            fg_color=INP, border_color=BORDER, border_width=1,
            text_color=T1, placeholder_text_color=T3,
            height=42, corner_radius=R_INP)
        self.api_ent.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.show_btn = ctk.CTkButton(r, text="Afficher",
            fg_color=INP, hover_color=BORDER, text_color=T2,
            border_color=BORDER, border_width=1,
            height=42, width=100, corner_radius=R_BTN, command=self._tog_api)
        self.show_btn.pack(side="left", padx=(0, 8))
        ctk.CTkButton(r, text="Sauvegarder",
            fg_color=ACCENT, hover_color=ACCENT2, text_color="#FFFFFF",
            font=ctk.CTkFont(weight="bold"),
            height=42, width=130, corner_radius=R_BTN,
            command=self._save_api).pack(side="left")
        self.api_stat = ctk.CTkLabel(c, text="", font=ctk.CTkFont(size=11), text_color=T3)
        self.api_stat.pack(anchor="w", padx=16, pady=(0, 4))
        sc = ctk.CTkFrame(c, fg_color=INP, corner_radius=R_INP); sc.pack(fill="x", padx=16, pady=(0, 16))
        _km = "Trousseau macOS" if sys.platform == "darwin" else "Windows Credential Manager"
        ctk.CTkLabel(sc,
            text=f"  \U0001f512  Stockée dans {_km}. Jamais transmise à Sédentaire.co.",
            font=ctk.CTkFont(size=11), text_color=T2, anchor="w").pack(anchor="w", padx=12, pady=10)

        # — Guide API —
        self._sec("Comment obtenir votre cl\u00e9 API", s)
        gc = ctk.CTkFrame(s, fg_color=CARD, corner_radius=R_CARD,
            border_width=1, border_color=BORDER)
        gc.pack(fill="x", padx=20, pady=(0, 4))
        for num, title, desc in [
            ("1", "Créer un compte Anthropic", "Allez sur console.anthropic.com et créez votre compte."),
            ("2", "Ajouter du crédit", "Settings › Billing › ajoutez 5 $ USD minimum.\nCoût : ~0,05 $ par PDF de 70 pages."),
            ("3", "Générer une clé API", "Settings › API Keys › Create Key.\nCopiez la clé (sk-ant-...) et collez-la ci-dessus."),
        ]:
            rr = ctk.CTkFrame(gc, fg_color="transparent"); rr.pack(fill="x", padx=16, pady=(12, 4))
            ctk.CTkLabel(rr, text=num, font=ctk.CTkFont(size=12, weight="bold"),
                text_color="#FFFFFF", fg_color=ACCENT,
                corner_radius=20, width=30, height=30).pack(side="left", padx=(0, 14))
            col = ctk.CTkFrame(rr, fg_color="transparent"); col.pack(side="left", fill="x", expand=True)
            ctk.CTkLabel(col, text=title, font=ctk.CTkFont(size=13, weight="bold"),
                text_color=T1, anchor="w").pack(anchor="w")
            ctk.CTkLabel(col, text=desc, font=ctk.CTkFont(size=12),
                text_color=T2, anchor="w", justify="left").pack(anchor="w")
        ctk.CTkButton(gc, text="  Ouvrir console.anthropic.com  →",
            fg_color=ACCENT_DIM, hover_color=BORDER, text_color=ACCENT,
            border_color=ACCENT, border_width=1,
            height=42, corner_radius=R_BTN,
            command=lambda: webbrowser.open(CONSOLE_URL)).pack(padx=16, pady=(12, 16), anchor="w")

    # ---- AIDE ----
    def _tab_a(self, p):
        s = ctk.CTkScrollableFrame(p, fg_color=BG, scrollbar_button_color=BORDER,
            scrollbar_button_hover_color=T3)
        s.pack(fill="both", expand=True)

        # — À propos —
        self._sec("\u00c0 propos", s)
        ab = ctk.CTkFrame(s, fg_color=CARD, corner_radius=R_CARD,
            border_width=1, border_color=BORDER)
        ab.pack(fill="x", padx=20, pady=(0, 4))
        ctk.CTkLabel(ab, text=APP_NAME,
            font=ctk.CTkFont("Coolvetica", 20, "bold"), text_color=T1).pack(anchor="w", padx=16, pady=(18, 2))
        ctk.CTkLabel(ab, text=f"Version {APP_VERSION}  ·  Développé par {BRAND}",
            font=ctk.CTkFont(size=12), text_color=T2).pack(anchor="w", padx=16)
        ctk.CTkLabel(ab, text="Traitement automatique de factures PDF par IA.",
            font=ctk.CTkFont(size=12), text_color=T3).pack(anchor="w", padx=16, pady=(4, 18))

        # — Confidentialité —
        self._sec("Confidentialit\u00e9 & donn\u00e9es", s)
        pr = ctk.CTkFrame(s, fg_color=CARD, corner_radius=R_CARD,
            border_width=1, border_color=BORDER)
        pr.pack(fill="x", padx=20, pady=(0, 4))
        ctk.CTkLabel(pr, justify="left", text_color=T2, font=ctk.CTkFont(size=12),
            text="Vos PDF sont traités localement sur votre machine.\n\n"
                 "Les pages sont envoyées à l'API Anthropic pour analyse.\n"
                 "Aucune donnée n'est transmise à Sédentaire.co.\n\n"
                 "Les appels API ne sont pas utilisés pour entraîner les modèles.\n"
                 "Politique complète : anthropic.com/privacy"
            ).pack(anchor="w", padx=16, pady=16)

        # — Support —
        self._sec("Besoin d'aide ?", s)
        su = ctk.CTkFrame(s, fg_color=CARD, corner_radius=R_CARD,
            border_width=1, border_color=BORDER)
        su.pack(fill="x", padx=20, pady=(0, 4))
        ctk.CTkLabel(su, text="Une question ? Un bug ? Notre équipe est disponible.",
            font=ctk.CTkFont(size=13), text_color=T1).pack(anchor="w", padx=16, pady=(16, 4))
        ctk.CTkButton(su, text="  Nous contacter — info@sédentaire.co  →",
            fg_color=ACCENT_DIM, hover_color=BORDER, text_color=ACCENT,
            border_color=ACCENT, border_width=1,
            height=42, corner_radius=R_BTN,
            command=lambda: webbrowser.open(CONTACT_URL)).pack(padx=16, pady=(8, 16), anchor="w")

        # — Log —
        self._sec("Log d'erreurs", s)
        lg = ctk.CTkFrame(s, fg_color=CARD, corner_radius=R_CARD,
            border_width=1, border_color=BORDER)
        lg.pack(fill="x", padx=20, pady=(0, 20))
        ctk.CTkLabel(lg, text="Exportez le log pour l'envoyer au support si nécessaire.",
            font=ctk.CTkFont(size=12), text_color=T2).pack(anchor="w", padx=16, pady=(14, 8))
        ctk.CTkButton(lg, text="Exporter le log d'erreurs",
            fg_color=INP, hover_color=BORDER, text_color=T1,
            border_color=BORDER, border_width=1,
            height=40, corner_radius=R_BTN, command=self._export).pack(padx=16, pady=(0, 16), anchor="w")

    # ---- ACTIONS ----
    def _pick(self):
        ps = filedialog.askopenfilenames(title="Choisir des PDF", filetypes=[("PDF","*.pdf")])
        if ps:
            self.pdfs = list(ps)
            if len(ps)==1:
                self.pdf_lbl.configure(text=f"OK  {Path(ps[0]).name}  ({Path(ps[0]).stat().st_size//1024} Ko)", text_color=TEAL)
            else:
                total = sum(Path(x).stat().st_size for x in ps)//1024
                self.pdf_lbl.configure(text=f"OK  {len(ps)} fichiers  ({total} Ko)", text_color=TEAL)

    def _clear(self):
        self.pdfs = []
        self.pdf_lbl.configure(text="Aucun fichier sélectionné", text_color=T3)

    def _dir(self):
        d = filedialog.askdirectory(title="Dossier de sortie")
        if d: self.dir_var.set(d)

    def _save_dir(self):
        self.cfg["output_dir"] = self.dir_var.get(); save_config(self.cfg)

    def _save_opts(self):
        self.cfg.update({"of":self.of.get(),"op":self.op.get(),"on":self.on_.get(),"od":self.od.get()})
        save_config(self.cfg)

    def _upd_prev(self):
        p = []
        if self.of.get(): p.append("Fournisseur")
        if self.op.get(): p.append("PO")
        if self.on_.get(): p.append("Facture")
        if self.od.get(): p.append("Date")
        self.prev_lbl.configure(text="Apercu : "+(" - ".join(p)+".pdf" if p else "INCONNU.pdf"))

    def _tog_api(self):
        if self.api_ent.cget("show") == "*":
            self.api_ent.configure(show=""); self.show_btn.configure(text="Masquer")
        else:
            self.api_ent.configure(show="*"); self.show_btn.configure(text="Afficher")

    def _save_api(self):
        k = self.api_var.get().strip()
        if not k: self.api_stat.configure(text="Cle vide", text_color=AMBER_C); return
        if not k.startswith("sk-ant-"):
            self.api_stat.configure(text="Format invalide (doit commencer par sk-ant-)", text_color=AMBER_C); return
        set_api_key(k)
        self.api_stat.configure(text="OK  Sauvegardée de façon sécurisée", text_color=TEAL)
        self.after(3000, lambda: self.api_stat.configure(text=""))

    def _do_cancel(self):
        self._cancel = True; self.btn_stop.configure(state="disabled")
        self._st("Annulation en cours...", AMBER_C)

    def _start(self):
        if self.processing: return
        key = get_api_key(); outd = self.dir_var.get().strip()
        if not key:
            messagebox.showerror("Cle manquante","Entrez votre cle API dans l'onglet Paramètres.")
            self.tabs.set("  Paramètres  "); return
        if not self.pdfs: messagebox.showerror("PDF manquant","Selectionnez un fichier PDF."); return
        if not outd: messagebox.showerror("Dossier manquant","Choisissez un dossier de sortie."); return
        opts = {"f":self.of.get(),"p":self.op.get(),"n":self.on_.get(),"d":self.od.get()}
        self.processing = True; self._cancel = False; self.logs = []
        self.res_frame.pack_forget()
        self.btn_go.configure(state="disabled", fg_color=INP, text_color=T2)
        self.btn_stop.configure(state="normal")
        threading.Thread(target=self._run, args=(key,outd,opts), daemon=True).start()

    def _run(self, key, outd, opts):
        created = []; total_pages = 0
        all_pdf_data = []  # [(pdf_path, groups)]
        try:
            client = anthropic.Anthropic(api_key=key); pp = poppler_path()
            # Phase 1 : Analyse IA de toutes les pages
            for idx, pdf in enumerate(self.pdfs):
                if self._cancel: break
                name = Path(pdf).name
                self._st(f"PDF {idx+1}/{len(self.pdfs)} - Conversion : {name}")
                self._log(f"\n=== {name} ===")
                images = convert_from_path(pdf, dpi=DPI, poppler_path=pp)
                n = len(images); total_pages += n; pd_ = []
                for i, img in enumerate(images):
                    if self._cancel: break
                    self._st(f"PDF {idx+1}/{len(self.pdfs)} - Analyse page {i+1}/{n}")
                    self._pg((idx+(i+1)/n)/len(self.pdfs))
                    b64 = img_b64(img)
                    res = analyze(client, b64)
                    res["numero_commande"] = norm_po(res.get("numero_commande"))
                    res["page_idx"] = i; pd_.append(res)
                    self._log(f"  p{i+1}: {res['type_page']}|{res.get('fournisseur','?')}|PO:{res.get('numero_commande','?')}|F:{res.get('numero_facture','?')}")
                if self._cancel: break
                groups = build_groups(pd_)
                all_pdf_data.append((pdf, groups))

            if self._cancel:
                self._st("Traitement annule.", AMBER_C)
                return

            # Phase 2 : Revue manuelle (sur le thread principal)
            self._pg(1.0)
            self._st("En attente de révision…")
            all_groups = []
            for _, groups in all_pdf_data:
                all_groups.extend(groups)

            # Ouvrir la fenêtre de révision sur le thread principal
            reviewed = [None]
            event = threading.Event()

            def open_review():
                dlg = ReviewDialog(self, all_groups, opts)
                dlg.wait_window()
                reviewed[0] = dlg._result
                event.set()

            self.after(0, open_review)
            event.wait()

            if reviewed[0] is None:
                self._st("Traitement annulé par l'utilisateur.", AMBER_C)
                return

            # Phase 3 : Sauvegarde avec les noms corrigés
            self._st("Sauvegarde des fichiers…")
            group_idx = 0
            for pdf, groups in all_pdf_data:
                reader = PdfReader(pdf)
                for g in groups:
                    reviewed_g = reviewed[0][group_idx]; group_idx += 1
                    # Sous-dossier "lieu" si spécifié
                    lieu = reviewed_g.get("lieu")
                    if lieu:
                        target_dir = Path(outd) / clean(lieu)
                    else:
                        target_dir = Path(outd)
                    target_dir.mkdir(parents=True, exist_ok=True)
                    fname = mk_fname(reviewed_g, opts); dest = target_dir / fname
                    c2 = 2
                    while dest.exists(): dest = target_dir / f"{fname.rsplit('.',1)[0]} ({c2}).pdf"; c2+=1
                    w = PdfWriter()
                    for pidx in g["pages"]: w.add_page(reader.pages[pidx])
                    with open(dest,"wb") as fh: w.write(fh)
                    rel_name = f"{clean(lieu)}/{dest.name}" if lieu else dest.name
                    created.append(rel_name); self._log(f"  OK {rel_name}")

            self._show(created, total_pages, outd)
        except anthropic.AuthenticationError:
            self._st("Cle API invalide - verifiez dans Paramètres.", RED_C); self._log("ERREUR: Cle API invalide")
        except Exception as e:
            self._st(f"Erreur : {e}", RED_C); self._log(f"ERREUR: {e}")
        finally:
            self.processing = False
            self.after(0, lambda: self.btn_go.configure(state="normal", fg_color=ACCENT, text_color="#FFFFFF"))
            self.after(0, lambda: self.btn_stop.configure(state="disabled"))

    def _st(self, m, c=None): self.after(0, lambda: self.stat_lbl.configure(text=m, text_color=c or T2))
    def _pg(self, v): self.after(0, lambda: self.pgbar.set(v))
    def _log(self, l): self.logs.append(l)

    def _show(self, created, pages, outd):
        def upd():
            self.res_ttl.configure(text=f"OK  {len(created)} fichiers crees depuis {pages} pages")
            self.res_box.configure(state="normal"); self.res_box.delete("1.0","end")
            for n in created: self.res_box.insert("end",f"  {n}\n")
            self.res_box.configure(state="disabled")
            self.res_frame.pack(fill="x",padx=20,pady=(0,8))
            self._st(f"Fichiers deposes dans : {outd}", TEAL)
        self.after(0, upd)

    def _open_dir(self):
        d = self.dir_var.get()
        if not os.path.exists(d):
            return
        if sys.platform == "win32":
            os.startfile(d)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", d])
        else:
            subprocess.Popen(["xdg-open", d])

    def _export(self):
        if not self.logs: messagebox.showinfo("Log vide","Aucun log disponible."); return
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = filedialog.asksaveasfilename(defaultextension=".txt",
            initialfile=f"log_{ts}.txt", filetypes=[("TXT","*.txt")])
        if dest:
            with open(dest,"w",encoding="utf-8") as fh:
                fh.write(f"{APP_NAME} v{APP_VERSION} - Log {ts}\n{'='*60}\n")
                fh.write("\n".join(self.logs))
            messagebox.showinfo("Log exporte",f"Sauvegarde:\n{dest}")


if __name__ == "__main__":
    load_fonts()
    app = App()
    app.mainloop()
