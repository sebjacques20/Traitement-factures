"""
Traitement de facture v2.0
c 2026 Sedentaire.co
"""
import customtkinter as ctk
from tkinter import filedialog, messagebox
import anthropic, base64, json, os, re, io, threading, webbrowser, datetime, sys, ctypes, tempfile
import ctypes.util  # noqa: doit être au niveau module sinon l'import dans load_fonts()
                    # fait de ctypes une variable locale (UnboundLocalError sur Windows)
import urllib.request, subprocess
from pathlib import Path

# Répertoire des ressources — chemin absolu, robuste peu importe d'où on le lance
if getattr(sys, "frozen", False):
    # PyInstaller: _MEIPASS pointe vers le dossier temporaire d'extraction
    # Sur Mac .app, les datas sont dans Contents/Resources (pas Contents/MacOS)
    _meipass = Path(sys._MEIPASS)
    if sys.platform == "darwin" and (_meipass.parent / "Resources").exists():
        BASE_DIR = _meipass.parent / "Resources"
    else:
        BASE_DIR = _meipass
else:
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
APP_VERSION = "2.8"
BRAND       = "sedentaire.co"
CONTACT_URL = "mailto:info@sedentaire.co"
CONSOLE_URL = "https://console.anthropic.com/settings/keys"
UPDATE_URL  = "https://github.com/sebjacques20/Traitement-factures/releases/latest/download/version.json"
KEYRING_SVC = "TraitementFacture"
KEYRING_USR = "anthropic_api_key"
CONFIG_FILE = Path.home() / ".traitement_facture_v2.json"
# Modèle IA : sonnet 4.6 = dernier Sonnet stable, support long terme,
# même prix que sonnet 4.5, supporte la vision.
AI_MODEL = "claude-sonnet-4-6"

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
   PRIORITE 2 : cherche dans les champs imprimes: "Bon de commande", "PO", "PO #", "N commande", "Order #", "Order number", "No projet", "Projet", "Project", "Job #", "Chantier", "BC", "BC#".

   FORMATS RENCONTRES (retourne la valeur EXACTE et LITTERALE telle qu'ecrite, avec lettres/tirets/espaces) :
   - Pure-numerique : "1090", "2547", "890"
   - Avec prefixe alphabetique : "BL1090", "MR1113", "BC1090", "P1475"
   - Avec tiret : "1107-P1475", "11-13"
   - Avec espace : "KG 11-13", "BC 1090"

   REGLES :
   - Garde TOUS les caracteres (lettres, chiffres, tirets, espaces) tels qu'ecrits. Le post-traitement extraira les chiffres.
   - EXCEPTION : si une PARTIE du numero est encerclee, soulignee ou corrigee a la main
     (ex: cercle au stylo autour de "1194" dans "PO 1194-P1524"), retourne UNIQUEMENT cette partie.
     L'annotation manuscrite designe le numero de projet du client.
   - Si le numero commence par "0" et fait 3 caracteres (ex: "090"), ajoute un "1" devant -> "1090".
   - Ne confonds PAS avec le numero de facture du fournisseur.
   - null si vraiment absent (mais cherche bien dans les annotations manuscrites avant d'abandonner).

4. numero_facture: numero de facture du FOURNISSEUR. Cherche dans: "Facture #", "Facture no", "N facture", "Invoice #", "Invoice no", numero en haut a droite du document.
5. date: date de la facture au format AAAA-MM-JJ, null si absent.
   ATTENTION aux annees a 2 chiffres : au Quebec le format est JJ/MM/AA ou JJ-MM-AA (jour en premier, annee en DERNIER).
   Ex: "23/06/26" -> "2026-06-23" ; "22-06-26" -> "2026-06-22".
   Ne retourne JAMAIS une annee avant 2020, sauf si elle est imprimee en 4 chiffres sur le document.

JSON strict: {"type_page":"facture","fournisseur":"Nom","numero_commande":"BL1090","numero_facture":"AR26-0715","date":"2026-02-28"}"""


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
    """Normalise un numéro de PO/projet vers ses chiffres canoniques.

    L'IA peut retourner des formats variés observés sur le terrain :
        "1090"        -> "1090"
        "BL1090"      -> "1090"   (préfixe fournisseur "BL" stripé)
        "MR1113"      -> "1113"
        "KG 11-13"    -> "1113"   (espaces/tirets retirés)
        "1107-P1475"  -> "11071475"
        "BC# 1090"    -> "1090"

    Permet ainsi de regrouper toutes les factures du projet "1113" peu importe
    le préfixe fournisseur (MR, KG, BC, BL, etc.) sous une même valeur canonique.

    Retourne None si l'entrée ne ressemble pas à un PO (vide, sans chiffre,
    trop long = bruit OCR, ou pure-digits hors plage 3-8).
    """
    if not po:
        return None
    po = str(po).strip()
    if not po or len(po) > 25:
        return None
    # Correction OCR seulement si l'input contient déjà au moins un chiffre.
    # Évite de convertir du texte pur (« Lorem ipsum ») en faux PO via o→0 / l→1.
    if not any(c.isdigit() for c in po):
        return None
    # Retirer les préfixes/suffixes purement alphabétiques (BL, MR, LS, KG, BC#…)
    # AVANT la correction OCR : sinon "LS1194" devient "L51194" (S→5) et le
    # préfixe fournisseur se retrouve fusionné aux chiffres du projet.
    core = re.sub(r'^[A-Za-z]+[\s#:.\-]*', '', po)
    core = re.sub(r'[\s#:.\-]*[A-Za-z]+$', '', core)
    if not any(c.isdigit() for c in core):
        core = po  # garde-fou : le strip a tout mangé (ex: "o90" pur OCR)
    po_oc = core.translate(str.maketrans("OolIS", "00115"))
    # Extraire tous les chiffres dans l'ordre, en jetant lettres/tirets/espaces
    digits = re.sub(r'\D', '', po_oc)
    if not digits:
        return None
    # Garde-fou de longueur — différencie pure-numérique (3-8, format classique)
    # et alphanumérique structuré (jusqu'à 12, ex: "1107-P1475" → "11071475").
    # Rejette ainsi les numéros de téléphone (10 chiffres purs) sans bloquer
    # les vrais POs alphanumériques de longueur similaire.
    is_pure_digit = po_oc.isdigit()
    if is_pure_digit and (len(digits) < 3 or len(digits) > 8):
        return None
    if not is_pure_digit and (len(digits) < 3 or len(digits) > 12):
        return None
    return digits

def analyze(client, b64):
    """Analyse une page via l'API Claude. Lève l'exception originale en cas
    d'échec — le caller (`_run`) décide quoi en faire (retry, abort, fallback).

    Ne pas avaler les exceptions ici : le client doit voir clairement les
    problèmes (crédit épuisé, clé invalide, réseau bloqué) plutôt que se
    retrouver avec 25 pages "INCONNU" sans explication.
    """
    r = client.messages.create(
        model=AI_MODEL, max_tokens=300,
        messages=[{"role":"user","content":[
            {"type":"image","source":{"type":"base64","media_type":"image/jpeg","data":b64}},
            {"type":"text","text":PROMPT}]}])
    raw = r.content[0].text.strip()
    m = re.search(r'\{[^{}]+\}', raw, re.DOTALL)
    if m: raw = m.group(0)
    d = json.loads(raw.strip())
    if d.get("type_page") not in ("facture","feuille_route"): d["type_page"]="feuille_route"
    return d

# Fallback "page inconnue" — utilisé quand un appel ponctuel échoue après
# 1 ou 2 essais (mais avant le seuil d'abandon à 3 échecs consécutifs).
def _empty_page_result():
    return {"type_page":"feuille_route","fournisseur":None,"numero_commande":None,
            "numero_facture":None,"date":None}

def build_groups(pages):
    """Regroupe les pages en factures.
    - Démarre un nouveau groupe quand l'IA classe la page comme "facture".
    - Filet de sécurité : démarre aussi un nouveau groupe si le fournisseur OU le
      n° de facture change franchement entre deux pages (les deux côtés doivent
      être non-null et différents — évite de sur-scinder sur des champs manquants).
    """
    def _new(d):
        return {"pages":[d["page_idx"]],"fournisseur":d.get("fournisseur"),
                "numero_commande":d.get("numero_commande"),"numero_facture":d.get("numero_facture"),
                "date":d.get("date"),
                "_po":[d["numero_commande"]] if d.get("numero_commande") else [],
                "_fr":[d["fournisseur"]] if d.get("fournisseur") else []}

    groups, cur = [], None
    for d in pages:
        start_new = False
        if d["type_page"] == "facture":
            start_new = True
        elif cur is not None:
            d_fr, d_fac = d.get("fournisseur"), d.get("numero_facture")
            c_fr, c_fac = cur.get("fournisseur"), cur.get("numero_facture")
            if d_fr and c_fr and d_fr != c_fr:
                start_new = True
            elif d_fac and c_fac and d_fac != c_fac:
                start_new = True

        if start_new or cur is None:
            if cur: groups.append(cur)
            cur = _new(d)
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
                if not g["numero_commande"]:
                    g["numero_commande"] = dp
                elif g["numero_commande"] != dp and dp in g["numero_commande"]:
                    # PO parasite contenant le PO dominant du lot : ex "11941524"
                    # lu sur "PO 1194-P1524" quand le projet est 1194. On rabat
                    # sur le dominant pour ne pas fragmenter le regroupement.
                    g["_po_snap"] = g["numero_commande"]
                    g["numero_commande"] = dp
    return groups

def mk_fname(g, opts):
    p = []
    if opts.get("f"): p.append(clean(g.get("fournisseur")))
    if opts.get("p"): p.append(clean(g.get("numero_commande")))
    if opts.get("n"): p.append(clean(g.get("numero_facture")))
    if opts.get("d") and g.get("date"): p.append(clean(g["date"]))
    return " - ".join(p)+".pdf" if p else "INCONNU.pdf"

def _dup_key(g):
    """Clé d'identité d'une facture pour la détection de doublons.

    Fournisseur + n° de facture normalisés (casse et ponctuation ignorées).
    On exige les deux champs : matcher sur le fournisseur seul ou la date seule
    générerait trop de faux positifs (un fournisseur émet plusieurs factures).
    """
    fr = (g.get("fournisseur") or "").strip().casefold()
    nf = re.sub(r'[^a-z0-9]', '', str(g.get("numero_facture") or "").casefold())
    if not fr or not nf:
        return None
    return (fr, nf)

def mark_duplicates(groups):
    """Marque g["_dup"]=True sur toutes les factures partageant la même clé
    (fournisseur + n° facture). Retourne le nombre de factures impliquées."""
    for g in groups:
        g["_dup"] = False
    seen = {}
    for g in groups:
        k = _dup_key(g)
        if k is None:
            continue
        if k in seen:
            g["_dup"] = True
            seen[k]["_dup"] = True
        else:
            seen[k] = g
    return sum(1 for g in groups if g["_dup"])

def sort_invoices(groups):
    """Classe les factures par fournisseur (alpha), puis date de facturation,
    puis n° de facture. Les champs manquants passent en dernier — le format
    date AAAA-MM-JJ se trie correctement en tant que chaîne."""
    def key(g):
        fr = (g.get("fournisseur") or "").strip().casefold() or "￿"
        dt = g.get("date") or "9999-99-99"
        nf = str(g.get("numero_facture") or "")
        return (fr, dt, nf)
    return sorted(groups, key=key)

def poppler_path():
    if getattr(sys, "frozen", False):
        _meipass = Path(sys._MEIPASS)
        # Check multiple locations (PyInstaller may put binaries in different places)
        for candidate in [
            _meipass / "poppler" / "bin",
            _meipass.parent / "Frameworks" / "poppler" / "bin",  # Mac .app
        ]:
            if candidate.exists():
                return str(candidate)
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

        self._app = parent
        self._page_url = info.get("download_url", "https://github.com/sebjacques20/Traitement-factures/releases/latest")
        # URL directe de l'installeur pour la plateforme courante (présente dans
        # version.json depuis v2.8). Absente sur un version.json plus vieux ->
        # fallback : ouvrir la page de la release dans le navigateur.
        self._plat_url = info.get("download_url_win" if sys.platform == "win32" else "download_url_mac")

        self._btns = ctk.CTkFrame(inner, fg_color="transparent")
        self._btns.pack(side="right", padx=(10, 0))
        if self._plat_url:
            main_txt, main_cmd = "Mettre à jour", self._start_update
        else:
            main_txt, main_cmd = "Télécharger", lambda: webbrowser.open(self._page_url)
        ctk.CTkButton(self._btns, text=main_txt,
            fg_color="#00A878", hover_color="#007A58", text_color="#FFFFFF",
            height=30, corner_radius=8, font=ctk.CTkFont(size=12, weight="bold"),
            command=main_cmd).pack(side="left", padx=(0, 6))
        ctk.CTkButton(self._btns, text="Plus tard",
            fg_color="transparent", hover_color="#C8EDE3", text_color="#00705A",
            height=30, corner_radius=8, font=ctk.CTkFont(size=12),
            command=self.pack_forget).pack(side="left")
        self._pg = None
        self._pg_lbl = None

        ctk.CTkFrame(self, fg_color="#B2E4D6", height=1, corner_radius=0).pack(fill="x", side="bottom")

    def _blink(self, visible):
        self._dot.configure(text_color="#00A878" if visible else "#C8EDE3")
        self.after(800, lambda: self._blink(not visible))

    # ── Téléchargement intégré (v2.8+) ───────────────────────────────────
    def _start_update(self):
        """Remplace les boutons par une barre de progression et télécharge
        l'installeur de la plateforme directement dans l'app."""
        for w in self._btns.winfo_children():
            w.destroy()
        self._pg_lbl = ctk.CTkLabel(self._btns, text="Téléchargement…  0 %",
            font=ctk.CTkFont(size=11), text_color="#00534A", wraplength=300, justify="right")
        self._pg_lbl.pack(anchor="e")
        self._pg = ctk.CTkProgressBar(self._btns, width=180, height=6,
            fg_color="#C8EDE3", progress_color="#00A878")
        self._pg.set(0)
        self._pg.pack(anchor="e", pady=(4, 0))
        threading.Thread(target=self._download, daemon=True).start()

    def _download(self):
        try:
            fname = self._plat_url.rsplit("/", 1)[-1] or "installeur.bin"
            dest = Path(tempfile.gettempdir()) / fname
            req = urllib.request.Request(self._plat_url,
                headers={"User-Agent": f"{APP_NAME}/{APP_VERSION}"})
            with urllib.request.urlopen(req, timeout=30) as r, open(dest, "wb") as fh:
                total = int(r.headers.get("Content-Length") or 0)
                done = 0
                while True:
                    chunk = r.read(1 << 16)
                    if not chunk:
                        break
                    fh.write(chunk)
                    done += len(chunk)
                    if total:
                        self.after(0, self._set_progress, done / total)
            if total and done < total:
                raise IOError(f"téléchargement incomplet ({done}/{total} octets)")
            self.after(0, self._launch_installer, dest)
        except Exception as e:
            self.after(0, self._dl_failed, f"{type(e).__name__}: {e}")

    def _set_progress(self, p):
        if self._pg is not None:
            self._pg.set(p)
            self._pg_lbl.configure(text=f"Téléchargement…  {int(p * 100)} %")

    def _launch_installer(self, dest):
        if sys.platform == "win32":
            # L'app doit se fermer pour que l'installeur puisse remplacer ses fichiers
            self._pg_lbl.configure(text="Lancement de l'installeur…")
            os.startfile(str(dest))
            self.after(800, self._app.destroy)
        else:
            # Mac : Gatekeeper interdit de remplacer l'app automatiquement sans
            # signature Apple — on ouvre le DMG, l'utilisateur glisse l'app.
            subprocess.Popen(["open", str(dest)])
            self._pg.pack_forget()
            self._pg_lbl.configure(
                text="DMG ouvert — glissez l'app dans Applications, puis relancez-la.")

    def _dl_failed(self, err):
        for w in self._btns.winfo_children():
            w.destroy()
        self._pg = None
        ctk.CTkLabel(self._btns, text="Échec du téléchargement",
            font=ctk.CTkFont(size=11, weight="bold"), text_color=RED_C).pack(anchor="e")
        ctk.CTkButton(self._btns, text="Ouvrir la page de téléchargement",
            fg_color="#00A878", hover_color="#007A58", text_color="#FFFFFF",
            height=26, corner_radius=8, font=ctk.CTkFont(size=11),
            command=lambda: webbrowser.open(self._page_url)).pack(anchor="e", pady=(4, 0))

# ─────────────────────────────────────────────────────────────────────────────


class ReviewDialog(ctk.CTkToplevel):
    """Fenêtre de révision : permet de modifier les noms et de scinder des groupes avant la sauvegarde."""

    def __init__(self, parent, groups, opts):
        super().__init__(parent)
        self.title("Révision avant sauvegarde")
        self.geometry("820x580")
        self.resizable(True, True)
        self.minsize(720, 420)
        self.configure(fg_color=BG)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self._groups = list(groups)  # copie modifiable (split la mute)
        self._opts = opts
        self._result = None
        self._entries = []

        # Header
        hdr = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=0, height=54)
        hdr.pack(fill="x"); hdr.pack_propagate(False)
        ctk.CTkLabel(hdr, text="Vérifiez, scindez et modifiez les noms de fichiers",
            font=ctk.CTkFont(size=14, weight="bold"), text_color=T1).pack(side="left", padx=18)
        self._hdr_badge = ctk.CTkLabel(hdr, text="",
            font=ctk.CTkFont(size=11, weight="bold"), text_color="#FFFFFF",
            fg_color=RED_C, corner_radius=12, width=90, height=24)
        ctk.CTkFrame(self, fg_color=ACCENT, height=2, corner_radius=0).pack(fill="x")

        # Footer (packé avant le body pour rester en bas)
        ctk.CTkFrame(self, fg_color=BORDER, height=1, corner_radius=0).pack(fill="x", side="bottom")
        footer = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=0)
        footer.pack(fill="x", side="bottom", pady=0)
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

        # Body conteneur (le scrollable est recréé lors d'un split)
        self._body_holder = ctk.CTkFrame(self, fg_color=BG)
        self._body_holder.pack(fill="both", expand=True, padx=12, pady=(10, 0))
        self._body = None
        self._rebuild_body()

    def _rebuild_body(self):
        """(Re)construit la zone scrollable des lignes de groupes."""
        if self._body is not None:
            self._body.destroy()
        self._entries = []
        self._body = ctk.CTkScrollableFrame(self._body_holder, fg_color=BG,
            scrollbar_button_color=BORDER)
        self._body.pack(fill="both", expand=True)
        for i, g in enumerate(self._groups):
            self._build_row(i, g)
        self._update_hdr_badge()

    def _update_hdr_badge(self):
        n_inc = sum(1 for g in self._groups if not g.get("fournisseur") or not g.get("numero_commande"))
        if n_inc:
            self._hdr_badge.configure(text=f"{n_inc} INCONNU")
            self._hdr_badge.pack(side="right", padx=18)
        else:
            self._hdr_badge.pack_forget()

    def _build_row(self, i, g):
        row_fg = CARD if i % 2 == 0 else BG
        has_inconnu = not g.get("fournisseur") or not g.get("numero_commande")
        is_dup = bool(g.get("_dup"))
        border_c = RED_C if has_inconnu else (AMBER_C if is_dup else BORDER)

        card = ctk.CTkFrame(self._body, fg_color=row_fg, corner_radius=8,
            border_width=1, border_color=border_c)
        card.pack(fill="x", padx=4, pady=3)

        # Ligne 1 : # + Fourn + PO + Fact + Date + Scinder + Pages
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

        # Bouton Scinder (uniquement si 2 pages ou plus)
        if len(g["pages"]) >= 2:
            ctk.CTkButton(row1, text="Scinder",
                fg_color=YELLOW, hover_color=YELLOW2, text_color=T1,
                font=ctk.CTkFont(size=11, weight="bold"),
                height=32, width=70, corner_radius=6,
                command=lambda idx=i: self._open_split_picker(idx)).pack(side="left", padx=(2, 4))

        pages_txt = f"p.{','.join(str(p+1) for p in g['pages'])}"
        ctk.CTkLabel(row1, text=pages_txt, font=ctk.CTkFont(size=10),
            text_color=T3).pack(side="right", padx=(4, 4))

        if is_dup:
            ctk.CTkLabel(row1, text="DOUBLON ?",
                font=ctk.CTkFont(size=10, weight="bold"), text_color=T1,
                fg_color=AMBER_C, corner_radius=10, width=76, height=20).pack(side="right", padx=(4, 2))

        # Ligne 2 : Lieu (sous-dossier de destination)
        row2 = ctk.CTkFrame(card, fg_color="transparent")
        row2.pack(fill="x", padx=8, pady=(2, 6))

        ctk.CTkLabel(row2, text="", width=24).pack(side="left")  # spacer
        ctk.CTkLabel(row2, text="Lieu :", font=ctk.CTkFont(size=11),
            text_color=T2).pack(side="left", padx=(6, 4))
        # Pré-remplir : conserver la valeur déjà saisie (après un split), sinon laisser vide
        # pour que le placeholder « Sous-dossier (optionnel, ex: Chantier Nord) » soit visible.
        lieu_var = ctk.StringVar(value=g.get("lieu", ""))
        ctk.CTkEntry(row2, textvariable=lieu_var, font=ctk.CTkFont(size=12),
            fg_color=INP, border_color=BORDER, border_width=1,
            text_color=T1, height=32, corner_radius=6,
            placeholder_text="Sous-dossier (optionnel, ex: Chantier Nord)").pack(side="left", fill="x", expand=True, padx=(0, 4))

        # Exclure : la facture ne sera pas sauvegardée (retrait des doublons)
        x_var = ctk.BooleanVar(value=bool(g.get("_exclude")))
        ctk.CTkCheckBox(row2, text="Exclure", variable=x_var,
            font=ctk.CTkFont(size=11), text_color=T2, width=70,
            checkbox_width=18, checkbox_height=18,
            fg_color=RED_C, hover_color="#B02038", border_color=BORDER,
            corner_radius=5).pack(side="right", padx=(4, 0))

        self._entries.append({"f": f_var, "p": p_var, "n": n_var, "d": d_var, "lieu": lieu_var, "x": x_var})

    def _sync_entries_to_groups(self):
        """Copie les valeurs des champs vers self._groups (avant un rebuild ou un confirm)."""
        for i, e in enumerate(self._entries):
            if i < len(self._groups):
                self._groups[i]["fournisseur"] = e["f"].get().strip() or None
                self._groups[i]["numero_commande"] = e["p"].get().strip() or None
                self._groups[i]["numero_facture"] = e["n"].get().strip() or None
                self._groups[i]["date"] = e["d"].get().strip() or None
                self._groups[i]["lieu"] = e["lieu"].get().strip()  # chaîne vide possible
                self._groups[i]["_exclude"] = e["x"].get()

    def _open_split_picker(self, idx):
        """Affiche un popup pour choisir le point de scission du groupe idx."""
        self._sync_entries_to_groups()
        g = self._groups[idx]
        if len(g["pages"]) < 2:
            return

        popup = ctk.CTkToplevel(self)
        popup.title("Scinder le groupe")
        popup.geometry("420x360")
        popup.transient(self)
        popup.grab_set()
        popup.configure(fg_color=BG)
        popup.resizable(False, True)

        ctk.CTkLabel(popup, text=f"Scinder le groupe #{idx+1} en deux",
            font=ctk.CTkFont(size=14, weight="bold"), text_color=T1).pack(pady=(14, 4), padx=16)
        ctk.CTkLabel(popup,
            text=f"Pages du groupe : {', '.join('p.'+str(p+1) for p in g['pages'])}",
            font=ctk.CTkFont(size=11), text_color=T3, wraplength=380).pack(pady=(0, 10), padx=16)

        scroll = ctk.CTkScrollableFrame(popup, fg_color=BG, scrollbar_button_color=BORDER)
        scroll.pack(fill="both", expand=True, padx=16, pady=(0, 4))

        for k in range(len(g["pages"]) - 1):
            left_p = g["pages"][k] + 1
            right_p = g["pages"][k + 1] + 1
            ctk.CTkButton(scroll,
                text=f"Couper après p.{left_p}  →  nouveau groupe à partir de p.{right_p}",
                fg_color=INP, hover_color=ACCENT_DIM, text_color=T1,
                border_color=BORDER, border_width=1,
                font=ctk.CTkFont(size=12),
                height=36, corner_radius=R_BTN, anchor="w",
                command=lambda after=k: self._do_split(idx, after, popup)).pack(fill="x", pady=2)

        ctk.CTkButton(popup, text="Annuler",
            fg_color=INP, hover_color=BORDER, text_color=T2,
            border_color=BORDER, border_width=1,
            height=36, corner_radius=R_BTN, command=popup.destroy).pack(pady=(6, 12), padx=16, fill="x")

    def _do_split(self, idx, after_local_i, popup):
        """Scinde self._groups[idx] en deux après la position after_local_i (index local dans pages)."""
        g = self._groups[idx]
        pages = g["pages"]
        left = dict(g); left["pages"] = list(pages[:after_local_i + 1])
        right = dict(g); right["pages"] = list(pages[after_local_i + 1:])
        # Copies indépendantes des listes auxiliaires pour éviter des références partagées
        for key in ("_po", "_fr"):
            if key in g:
                left[key] = list(g[key])
                right[key] = list(g[key])
        self._groups[idx:idx + 1] = [left, right]
        popup.destroy()
        self._rebuild_body()

    def _confirm(self):
        self._sync_entries_to_groups()
        # Normaliser lieu vide -> None pour le code de sauvegarde existant
        for g in self._groups:
            if g.get("lieu") == "":
                g["lieu"] = None
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

        # \u2014 Mode de fusion par PO \u2014
        # Quand activ\u00e9 : toutes les factures avec le m\u00eame PO sont fusionn\u00e9es
        # dans un seul PDF nomm\u00e9 "<PO>.pdf" (les options de nommage ci-dessus
        # sont alors ignor\u00e9es, seul le PO compte).
        self.merge_po = ctk.BooleanVar(value=self.cfg.get("merge_po", False))
        ctk.CTkCheckBox(oi,
            text="Fusionner toutes les factures du m\u00eame PO en un seul PDF",
            variable=self.merge_po,
            font=ctk.CTkFont(size=13), text_color=T1,
            fg_color=ACCENT, hover_color=ACCENT2, border_color=BORDER,
            corner_radius=6, command=self._save_opts).pack(anchor="w", pady=(10, 0))

        # — Tri en mode fusion —
        # Demande client (v2.7) : pouvoir « repasser » un PDF déjà fusionné pour
        # que les factures s'y placent par fournisseur puis par date de
        # facturation, plutôt que par date de numérisation.
        self.sort_merge = ctk.BooleanVar(value=self.cfg.get("sort_merge", True))
        ctk.CTkCheckBox(oi,
            text="En mode fusion : classer les factures par fournisseur, puis par date",
            variable=self.sort_merge,
            font=ctk.CTkFont(size=13), text_color=T1,
            fg_color=ACCENT, hover_color=ACCENT2, border_color=BORDER,
            corner_radius=6, command=self._save_opts).pack(anchor="w", padx=(26, 0), pady=(6, 0))

        self.prev_lbl = ctk.CTkLabel(oi, text="",
            font=ctk.CTkFont("Courier New", 11), text_color=ACCENT2)
        self.prev_lbl.pack(anchor="w", pady=(12, 0))
        self._upd_prev()
        for v in [self.of, self.op, self.on_, self.od, self.merge_po, self.sort_merge]:
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
        self.cfg.update({"of":self.of.get(),"op":self.op.get(),"on":self.on_.get(),"od":self.od.get(),
                         "merge_po":self.merge_po.get(),"sort_merge":self.sort_merge.get()})
        save_config(self.cfg)

    def _upd_prev(self):
        if self.merge_po.get():
            ordre = "classées fournisseur → date" if self.sort_merge.get() else "dans l'ordre du scan"
            self.prev_lbl.configure(text=f"Aperçu : <PO>.pdf   (un seul fichier par PO, factures {ordre})")
            return
        p = []
        if self.of.get(): p.append("Fournisseur")
        if self.op.get(): p.append("PO")
        if self.on_.get(): p.append("Facture")
        if self.od.get(): p.append("Date")
        fname = " - ".join(p)+".pdf" if p else "INCONNU.pdf"
        # Indique aussi le sous-dossier auto par PO (avec lieu manuel possible en override)
        self.prev_lbl.configure(text=f"Aperçu : <PO>/{fname}   (Lieu manuel remplace le PO si saisi)")

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
        opts = {"f":self.of.get(),"p":self.op.get(),"n":self.on_.get(),"d":self.od.get(),
                "merge_po":self.merge_po.get(),"sort_merge":self.sort_merge.get()}
        self.processing = True; self._cancel = False; self.logs = []
        self.res_frame.pack_forget()
        self.btn_go.configure(state="disabled", fg_color=INP, text_color=T2)
        self.btn_stop.configure(state="normal")
        threading.Thread(target=self._run, args=(key,outd,opts), daemon=True).start()

    def _run(self, key, outd, opts):
        created = []; total_pages = 0
        all_pdf_data = []  # [(pdf_path, groups)]
        status = "OK"
        consecutive_failures = 0  # compteur d'échecs API consécutifs (cross-PDF)
        FAIL_THRESHOLD = 3        # au-delà : on arrête et on affiche l'erreur
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
                    try:
                        res = analyze(client, b64)
                        consecutive_failures = 0
                        raw_po = res.get("numero_commande")  # capture avant normalisation
                        norm = norm_po(raw_po)
                        # Log : on montre la valeur brute IA + la valeur normalisée si elle diffère.
                        # Ça permet de diagnostiquer si l'IA lit mal ou si norm_po sur-strippe.
                        po_log = f"{norm}" if norm == raw_po or not norm else f"{norm} (texte: {raw_po})"
                        self._log(f"  p{i+1}: {res['type_page']}|{res.get('fournisseur','?')}|PO:{po_log}|F:{res.get('numero_facture','?')}")
                        res["numero_commande_raw"] = raw_po
                        res["numero_commande"] = norm
                    except anthropic.AuthenticationError:
                        # Clé invalide → inutile de réessayer, on remonte direct
                        self._log(f"  p{i+1}: ERREUR clé API")
                        raise
                    except Exception as e:
                        consecutive_failures += 1
                        err = f"{type(e).__name__}: {e}"
                        self._log(f"  p{i+1}: ERREUR API ({consecutive_failures}/{FAIL_THRESHOLD}) -> {err}")
                        if consecutive_failures >= FAIL_THRESHOLD:
                            raise RuntimeError(
                                f"L'API Claude a échoué {consecutive_failures} fois de suite.\n\n"
                                f"Causes les plus probables :\n"
                                f"  • Crédit épuisé sur le compte Anthropic\n"
                                f"    (vérifier sur console.anthropic.com/settings/billing)\n"
                                f"  • Clé API invalide ou révoquée\n"
                                f"    (regénérer dans l'onglet Paramètres)\n"
                                f"  • Connexion bloquée vers api.anthropic.com\n"
                                f"    (firewall corporatif, VPN, etc.)\n\n"
                                f"Dernière erreur : {err}"
                            )
                        # Échec ponctuel : on continue avec une page "inconnue"
                        res = _empty_page_result()
                    res["page_idx"] = i; pd_.append(res)
                if self._cancel: break
                groups = build_groups(pd_)
                all_pdf_data.append((pdf, groups))
                self._log(f"  -> {len(groups)} groupe(s) détecté(s)")
                for g in groups:
                    if g.get("_po_snap"):
                        self._log(f"  ~ PO {g['_po_snap']} rabattu sur le PO dominant {g['numero_commande']}")

            if self._cancel:
                status = "Annulé"
                self._st("Traitement annule.", AMBER_C)
                return

            # Phase 2 : Revue manuelle (sur le thread principal)
            self._pg(1.0)
            self._st("En attente de révision…")
            all_groups = []
            for pdf_idx, (_, groups) in enumerate(all_pdf_data):
                for g in groups:
                    g["_pdf_idx"] = pdf_idx  # tag pour retrouver le PDF source après un split
                    all_groups.append(g)

            # Détection de doublons (même fournisseur + même n° de facture),
            # cross-PDF : une facture scannée deux fois dans deux lots se voit.
            n_dup = mark_duplicates(all_groups)
            if n_dup:
                self._log(f"\n!! {n_dup} facture(s) en doublon potentiel (même fournisseur + même n° de facture)")
                for g in all_groups:
                    if g.get("_dup"):
                        self._log(f"   - {g.get('fournisseur','?')} / facture {g.get('numero_facture','?')}"
                                  f" (p.{','.join(str(p+1) for p in g['pages'])})")

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
                status = "Annulé par l'utilisateur (révision)"
                self._st("Traitement annulé par l'utilisateur.", AMBER_C)
                return

            # Phase 3 : Sauvegarde avec les noms corrigés (itère sur la version révisée
            # pour respecter les scissions éventuelles)
            self._st("Sauvegarde des fichiers…")
            self._log(f"\n=== Sauvegarde ({len(reviewed[0])} groupe(s)) ===")
            n_excl = sum(1 for g in reviewed[0] if g.get("_exclude"))
            if n_excl:
                self._log(f"  ({n_excl} facture(s) exclue(s) à la révision)")
            readers = {i: PdfReader(pdf) for i, (pdf, _) in enumerate(all_pdf_data)}

            if opts.get("merge_po"):
                # MODE FUSION : un seul PDF par PO contenant toutes les pages des factures
                # de ce projet (peu importe le fournisseur). Les factures sans PO restent
                # séparées dans SANS_PO/ (pas de logique de fusion qui ait du sens là).
                from collections import OrderedDict
                po_buckets = OrderedDict()  # PO canonique -> liste de groupes
                no_po = []
                for reviewed_g in reviewed[0]:
                    if not reviewed_g.get("pages") or reviewed_g.get("_exclude"):
                        continue
                    po = reviewed_g.get("numero_commande")
                    if po:
                        po_buckets.setdefault(po, []).append(reviewed_g)
                    else:
                        no_po.append(reviewed_g)

                # Un PDF fusionné par PO
                for po, groups_in_po in po_buckets.items():
                    # Tri demandé par les clients (v2.7) : factures classées par
                    # fournisseur puis date de facturation, au lieu de l'ordre du scan
                    if opts.get("sort_merge"):
                        groups_in_po = sort_invoices(groups_in_po)
                    fname = f"{clean(po)}.pdf"
                    dest = Path(outd) / fname
                    c2 = 2
                    while dest.exists():
                        dest = Path(outd) / f"{clean(po)} ({c2}).pdf"; c2 += 1
                    Path(outd).mkdir(parents=True, exist_ok=True)
                    w = PdfWriter()
                    pages_count = 0
                    for g in groups_in_po:
                        reader = readers.get(g.get("_pdf_idx", 0)) or readers[0]
                        for pidx in g.get("pages", []):
                            w.add_page(reader.pages[pidx])
                            pages_count += 1
                    with open(dest, "wb") as fh:
                        w.write(fh)
                    created.append(dest.name)
                    self._log(f"  OK {dest.name}  ({len(groups_in_po)} facture(s), {pages_count} page(s))")

                # Factures sans PO : sauvegardées séparément dans SANS_PO/
                if no_po:
                    target_dir = Path(outd) / "SANS_PO"
                    target_dir.mkdir(parents=True, exist_ok=True)
                    if opts.get("sort_merge"):
                        no_po = sort_invoices(no_po)
                    for g in no_po:
                        reader = readers.get(g.get("_pdf_idx", 0)) or readers[0]
                        fname = mk_fname(g, opts); dest = target_dir / fname
                        c2 = 2
                        while dest.exists():
                            dest = target_dir / f"{fname.rsplit('.',1)[0]} ({c2}).pdf"; c2 += 1
                        w = PdfWriter()
                        for pidx in g.get("pages", []): w.add_page(reader.pages[pidx])
                        with open(dest, "wb") as fh: w.write(fh)
                        rel_name = f"SANS_PO/{dest.name}"
                        created.append(rel_name); self._log(f"  OK {rel_name}")
            else:
                # MODE CLASSIQUE : un PDF par facture, regroupé en sous-dossier par PO
                for reviewed_g in reviewed[0]:
                    pdf_idx = reviewed_g.get("_pdf_idx", 0)
                    reader = readers.get(pdf_idx) or readers[0]
                    pages_to_write = reviewed_g.get("pages", [])
                    if not pages_to_write or reviewed_g.get("_exclude"):
                        continue
                    # Logique de sous-dossier (priorité descendante) :
                    #   1. Lieu manuel (override explicite saisi par l'utilisateur)
                    #   2. PO canonique (regroupement automatique : toutes les 1090 ensemble)
                    #   3. "SANS_PO" pour les factures sans PO détecté
                    lieu = reviewed_g.get("lieu")
                    po = reviewed_g.get("numero_commande")
                    if lieu:
                        subfolder = clean(lieu)
                    elif po:
                        subfolder = clean(po)
                    else:
                        subfolder = "SANS_PO"
                    target_dir = Path(outd) / subfolder
                    target_dir.mkdir(parents=True, exist_ok=True)
                    fname = mk_fname(reviewed_g, opts); dest = target_dir / fname
                    c2 = 2
                    while dest.exists(): dest = target_dir / f"{fname.rsplit('.',1)[0]} ({c2}).pdf"; c2+=1
                    w = PdfWriter()
                    for pidx in pages_to_write: w.add_page(reader.pages[pidx])
                    with open(dest,"wb") as fh: w.write(fh)
                    rel_name = f"{subfolder}/{dest.name}"
                    created.append(rel_name); self._log(f"  OK {rel_name}")

            self._show(created, total_pages, outd)
        except anthropic.AuthenticationError:
            status = "Clé API invalide"
            self._st("Clé API invalide — vérifiez dans Paramètres.", RED_C)
            self._log("ERREUR: Clé API invalide")
            self.after(0, lambda: messagebox.showerror(
                "Clé API invalide",
                "Votre clé API Anthropic n'est pas valide ou a été révoquée.\n\n"
                "1. Ouvrez l'onglet Paramètres\n"
                "2. Vérifiez que la clé commence par « sk-ant- »\n"
                "3. Sinon, regénérez-en une sur console.anthropic.com/settings/keys"))
        except Exception as e:
            status = f"Erreur : {e}"
            self._st("Erreur — voir détails", RED_C)
            self._log(f"ERREUR: {e}")
            self.after(0, lambda m=str(e): messagebox.showerror("Erreur de traitement", m))
        finally:
            self._save_log_to_dir(outd, status, total_pages, len(created))
            self.processing = False
            self.after(0, lambda: self.btn_go.configure(state="normal", fg_color=ACCENT, text_color="#FFFFFF"))
            self.after(0, lambda: self.btn_stop.configure(state="disabled"))

    def _save_log_to_dir(self, outd, status, total_pages=0, n_created=0):
        """Sauvegarde automatique du log dans le dossier de sortie (filet de sécurité pour debug)."""
        if not outd:
            return
        try:
            outp = Path(outd)
            outp.mkdir(parents=True, exist_ok=True)
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            log_file = outp / f"_log_traitement_{ts}.txt"
            with open(log_file, "w", encoding="utf-8") as fh:
                fh.write(f"{APP_NAME} v{APP_VERSION}\n")
                fh.write(f"Date          : {datetime.datetime.now().isoformat(timespec='seconds')}\n")
                fh.write(f"Plateforme    : {sys.platform}\n")
                fh.write(f"Statut        : {status}\n")
                fh.write(f"PDF traités   : {len(self.pdfs)}\n")
                for p in self.pdfs:
                    fh.write(f"  - {p}\n")
                fh.write(f"Pages totales : {total_pages}\n")
                fh.write(f"Fichiers créés: {n_created}\n")
                fh.write("=" * 60 + "\n")
                fh.write("\n".join(self.logs))
                fh.write("\n")
        except Exception:
            pass  # ne jamais faire planter le _run pour un échec de log

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
