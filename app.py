import re
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import anthropic
import json
from datetime import datetime, date, timedelta

import re

# ══════════════════════════════════════════════════════════
# PARSER OFX COMPLETO — lê TODAS as transações
# ══════════════════════════════════════════════════════════
def parse_ofx(raw: str) -> dict:
    """Parse completo de OFX/SGML (BTG, BB, Safra, CEF, C6). Lê 100% das transações."""
    ofx_start = raw.find("<OFX>")
    body = raw[ofx_start:] if ofx_start >= 0 else raw

    def tag(t, src=body):
        m = re.search(rf'<{t}>\s*(.*?)(?:\n|<)', src, re.IGNORECASE)
        return m.group(1).strip() if m else ""

    bank_id   = tag("BANKID")
    acct_id   = tag("ACCTID")
    dt_start  = tag("DTSTART")[:8]
    dt_end    = tag("DTEND")[:8]
    saldo_str = tag("BALAMT")

    def fmt8(d):
        return f"{d[6:8]}/{d[4:6]}/{d[:4]}" if len(d)>=8 else d

    trns = re.findall(r'<STMTTRN>(.*?)</STMTTRN>', body, re.DOTALL|re.IGNORECASE)
    rows = []; ent = 0.0; sai = 0.0

    for trn in trns:
        def g(t, b=trn):
            m = re.search(rf'<{t}>\s*(.*?)(?:\n|<|$)', b, re.IGNORECASE)
            return m.group(1).strip() if m else ""
        try:    val = float(g("TRNAMT").replace(",","."))
        except: continue
        dt   = g("DTPOSTED")[:8]
        memo = g("MEMO").strip()[:80]
        tipo = "entrada" if val > 0 else "saida"
        if val > 0: ent += val
        else:       sai += abs(val)
        rows.append({"data":fmt8(dt),"tipo":tipo,"valor":val,"abs_valor":abs(val),"memo":memo})

    try:    saldo_real = float(saldo_str)
    except: saldo_real = ent - sai

    # Categorias
    cats = {}
    for r in rows:
        m = r["memo"].upper()
        cat = ("PIX"          if "PIX" in m else
               "BOLETO"       if "BOLETO" in m else
               "TED"          if "TED" in m else
               "MENSALIDADE"  if any(x in m for x in ["MENSALIDADE","PLANO","EXCEDENTE"]) else
               "FOLHA"        if any(x in m for x in ["FOLHA","SALARIO","PAGAMENTO FUNC"]) else "OUTROS")
        if cat not in cats: cats[cat] = {"ent":0.0,"sai":0.0,"n":0}
        if r["valor"] > 0: cats[cat]["ent"] += r["valor"]
        else:              cats[cat]["sai"] += abs(r["valor"])
        cats[cat]["n"] += 1

    top_e = sorted([r for r in rows if r["valor"]>0], key=lambda x:-x["valor"])[:8]
    top_s = sorted([r for r in rows if r["valor"]<0], key=lambda x: x["valor"])[:8]

    return {
        "df":      pd.DataFrame(rows) if rows else pd.DataFrame(),
        "entradas":ent, "saidas":sai, "saldo":saldo_real,
        "n_trans": len(rows),
        "banco":   f"Banco {bank_id}" if bank_id else "BTG Pactual",
        "conta":   acct_id,
        "periodo": f"{fmt8(dt_start)} a {fmt8(dt_end)}",
        "top_ent": top_e, "top_sai": top_s, "cats": cats,
    }


# ══════════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════════
st.set_page_config(
    page_title="CFO IA · Grupo Jet",
    page_icon="🟠",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
#MainMenu,footer,header{visibility:hidden}
.block-container{padding-top:1rem;padding-bottom:1rem}
.jet-topbar{background:linear-gradient(90deg,#141414,#1E1E1E);border-radius:12px;
  padding:12px 20px;display:flex;align-items:center;gap:12px;
  margin-bottom:16px;border:0.5px solid #2A2A2A}
.jet-icon{width:34px;height:34px;background:#F05A22;border-radius:8px;
  display:flex;align-items:center;justify-content:center;
  font-weight:900;color:#fff;font-size:18px;flex-shrink:0}
.jet-title{color:#fff;font-size:15px;font-weight:700}
.jet-sub{color:#555;font-size:10px;margin-top:1px}
.badge-ok{background:#0D3320;color:#22A85A;border:0.5px solid #1A6640;
  border-radius:20px;padding:3px 10px;font-size:11px;font-weight:600;
  display:inline-flex;align-items:center;gap:5px}
.dot-ok{width:6px;height:6px;border-radius:50%;background:#22A85A;
  display:inline-block;animation:pulse 2s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
.kpi{background:#fff;border-radius:10px;border:0.5px solid #E5E1DC;padding:14px 16px;margin-bottom:4px}
.kpi-l{font-size:10px;color:#6E6E6E;text-transform:uppercase;letter-spacing:.05em;margin-bottom:5px}
.kpi-v{font-size:22px;font-weight:800;color:#141414;line-height:1.1}
.kpi-d{font-size:11px;margin-top:4px}
.pos{color:#22A85A}.neg{color:#D93025}.warn{color:#D97706}.muted{color:#6E6E6E}
.insight{border-left:3px solid #F05A22;background:#FFF5F0;
  padding:12px 16px;border-radius:0 8px 8px 0;
  font-size:13px;line-height:1.75;color:#141414;margin:10px 0}
.pill{display:inline-block;padding:2px 9px;border-radius:20px;font-size:10px;font-weight:600}
.ok{background:#E5F7ED;color:#0A5C2E}
.er{background:#FDECEB;color:#8B1A1A}
.wa{background:#FEF3CD;color:#7A4F00}
.bl{background:#E6F2FB;color:#1A3F8A}
.gr{background:#F0EDE8;color:#555}
.chat-u{background:#F05A22;color:#fff;border-radius:12px 4px 12px 12px;
  padding:10px 14px;font-size:13px;line-height:1.6;max-width:82%;margin:4px 0 4px auto}
.chat-a{background:#fff;border:0.5px solid #E5E1DC;border-radius:4px 12px 12px 12px;
  padding:10px 14px;font-size:13px;line-height:1.6;max-width:86%;margin:4px 0}
.chat-lbl{font-size:10px;font-weight:600;margin-bottom:2px}
.lbl-a{color:#F05A22}.lbl-u{color:#6E6E6E;text-align:right}
div[data-testid="stSidebar"]{background:#141414 !important}
div[data-testid="stSidebar"] .stRadio label span{color:#AAA !important}
.src-bar{background:#F6F4F1;border-radius:8px;padding:8px 12px;
  font-size:11px;color:#6E6E6E;margin-bottom:12px}
</style>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════
# ESTADO GLOBAL
# ══════════════════════════════════════════════════════════
STAT_ZERO = dict(
    # Clientes
    n_clientes=0, n_ativos=0, n_inad=0, n_suspensos=0, n_cancelados=0,
    # Financeiro Hubsoft (4 categorias principais)
    fat_total=0.0,      # Total faturado (todas as faturas emitidas)
    fat_recebido=0.0,   # Total efetivamente recebido/pago
    fat_a_receber=0.0,  # A receber (não vencido)
    fat_atrasado=0.0,   # Em atraso (vencido e não pago)
    fat_inad=0.0,       # Valor inadimplente (legado)
    fat_rec=0.0,        # Estimativa recebimento
    n_fat_recebido=0,   # Qtd faturas pagas
    n_fat_a_receber=0,  # Qtd faturas a receber
    n_fat_atrasado=0,   # Qtd faturas atrasadas
    # Contas a pagar
    pag_total=0.0, pag_vencidas=0.0, pag_avencer=0.0,
    n_pag=0, n_pag_venc=0, n_pag_avenc=0,
    # Percentuais
    inad_pct=0.0, rec_pct=0.0, adimplencia_pct=0.0,
)
for k, v in {
    "hub_df": None, "pag_df": None, "pag_classif": None,
    "inad_df": None, "ext_result": None,
    "stats": STAT_ZERO.copy(),
    "chat_history": [], "api_key": "",
    "data_src": "Sem dados importados",
    "last_update": None,
    "hub_col_map": {}, "col_expanded": False,
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ══════════════════════════════════════════════════════════
# UTILITÁRIOS
# ══════════════════════════════════════════════════════════
def brl(v):
    """Formata valor no padrão brasileiro: R$ 1.234.567,89"""
    try:
        n = float(v)
        # f"{n:,.2f}" → "1,234,567.89" (padrão US)
        # Converte para BR: . milhar, , decimal
        s = f"{n:,.2f}".replace(".", "X").replace(",", ".").replace("X", ",")
        return f"R$ {s}"
    except:
        return "R$ —"

def pv(v):
    if v is None or str(v).strip() == "": return 0.0
    try: return float(v)
    except:
        s = str(v).replace("R$","").replace(" ","").replace(".","").replace(",",".")
        try: return float(s)
        except: return 0.0

def fmtd(v):
    if v is None or str(v).strip() == "": return "—"
    if isinstance(v,(datetime,date)): return v.strftime("%d/%m/%Y")
    try:
        d = pd.to_datetime(v, dayfirst=True)
        return d.strftime("%d/%m/%Y") if not pd.isna(d) else str(v)
    except: return str(v)

def dcol(df, *terms):
    if df is None or df.empty: return None
    n = lambda s: str(s).lower().replace(" ","").replace("_","").replace("-","").replace("/","")
    for col in df.columns:
        for t in terms:
            if n(t) in n(col) or n(col) in n(t): return col
    return None

def read_file(f):
    name = f.name.lower()
    try:
        if name.endswith(".csv"):
            for enc in ["utf-8","latin-1","cp1252"]:
                try: f.seek(0); return pd.read_csv(f, encoding=enc)
                except: pass
        elif name.endswith((".xlsx",".xls")):
            f.seek(0)
            xl = pd.ExcelFile(f)
            sheets = xl.sheet_names
            if len(sheets) == 1:
                return pd.read_excel(f, sheet_name=0)
            # pega a aba com mais linhas
            best = None
            for sh in sheets:
                try:
                    tmp = pd.read_excel(f, sheet_name=sh)
                    if best is None or len(tmp) > len(best): best = tmp
                except: pass
            return best
    except Exception as e:
        st.error(f"Erro ao ler {f.name}: {e}")
    return None

# ══════════════════════════════════════════════════════════
# PROCESSAMENTO CENTRAL — chamado ao importar qualquer dado
# ══════════════════════════════════════════════════════════
def recalc():
    # Alias para evitar conflito entre streamlit (st) e dict de stats (S)
    import streamlit as _st
    hub  = _st.session_state.hub_df
    pag  = _st.session_state.pag_df
    hoje = pd.Timestamp.now().normalize()
    S    = STAT_ZERO.copy()
    srcs = []

    # ── HUBSOFT — 4 categorias financeiras ──
    if hub is not None and not hub.empty:
        srcs.append(f"Hubsoft ({len(hub)} reg.)")
        hub = hub.copy()

        # ── Usa mapa manual se definido pelo usuário, senão detecta automaticamente ──
        col_map = _st.session_state.get("hub_col_map", {})

        def _col(manual_key, *auto_terms):
            """Retorna coluna manual se definida, senão detecta automaticamente."""
            manual = col_map.get(manual_key)
            if manual and manual in hub.columns:
                return manual
            return dcol(hub, *auto_terms)

        sc   = _col("status",  "status","situacao","estado","situation","situação")
        nc   = _col("valor",   "mensalidade","valor","value","amount","mensal","monthly","valormensal","valorplano","plano")
        dc2  = _col("dias",    "diasatraso","dias","atraso","days","overdue","diasdeatraso")
        vc   = _col("atraso",  "valoraberto","aberto","debito","saldo","balance","valordevido","devido","valoratraso")
        pc   = _col("pago",    "datapagamento","pagamento","pago","datapag","paid","payment","dtpagamento")
        vpc  = dcol(hub,       "valorpago","valorrecebido","recebido","amountpaid","paidamount")
        venc = _col("venc",    "vencimento","datavencimento","vencto","duedate","datavenc","venc","dtavencimento")
        vpc2 = dcol(hub,       "valorafaturado","faturado","invoiced","valorcobranca","cobranca","valorliquido")

        # ── Diagnóstico: evita somar coluna com valores absurdos ──
        # Se nc detectado mas média/cliente > R$ 100.000, provavelmente coluna errada
        if nc:
            sample_vals = hub[nc].apply(pv).dropna()
            avg_val = sample_vals.mean() if len(sample_vals) > 0 else 0
            # Se média > 100k ou < 0.01, ignora coluna e usa None
            if avg_val > 100000 or (avg_val < 0.01 and avg_val > 0):
                nc = None  # força usuário a selecionar manualmente

        # ── Normaliza status ──
        if sc:
            hub["_st"] = hub[sc].astype(str).str.lower().str.strip()
        else:
            hub["_st"] = "ativo"

        is_inad = hub["_st"].str.contains("inad|delinq|atraso|inadim", na=False)
        is_susp = hub["_st"].str.contains("suspen|bloq|suspens", na=False)
        is_canc = hub["_st"].str.contains("cancel|inativ", na=False)
        is_ativ = ~(is_inad | is_susp | is_canc)

        S["n_clientes"]   = len(hub)
        S["n_ativos"]     = int(is_ativ.sum())
        S["n_inad"]       = int(is_inad.sum())
        S["n_suspensos"]  = int(is_susp.sum())
        S["n_cancelados"] = int(is_canc.sum())

        # ── Valor base (mensalidade/valor do plano) ──
        if nc:
            hub["_mens"] = hub[nc].apply(pv)
        else:
            hub["_mens"] = 0.0

        # ── FATURADO: total de mensalidades emitidas ──
        # Usa coluna de valor faturado se existir, senão usa mensalidade
        if vpc2:
            hub["_fat"] = hub[vpc2].apply(pv)
        else:
            hub["_fat"] = hub["_mens"]
        S["fat_total"] = float(hub["_fat"].sum())

        # ── RECEBIDO: efetivamente pago ──
        # Detecta por: (1) coluna valor pago, (2) data pagamento preenchida,
        # (3) status "pago/recebido", (4) fallback: ativos sem atraso
        def detectar_recebido(row):
            # Tem valor pago explícito?
            if vpc and pv(row.get(vpc, 0)) > 0:
                return True
            # Tem data de pagamento preenchida?
            if pc:
                dp = str(row.get(pc, "")).strip()
                if dp and dp not in ["", "nan", "None", "0", "NaT"]:
                    return True
            # Status indica pago?
            s2 = str(row.get(sc, "") if sc else "").lower()
            if any(x in s2 for x in ["pago","recebido","quitado","liquidado","paid"]):
                return True
            return False

        hub["_recebido"] = hub.apply(detectar_recebido, axis=1)

        if vpc:
            hub["_val_rec"] = hub.apply(
                lambda r: pv(r[vpc]) if r["_recebido"] else 0.0, axis=1)
        else:
            hub["_val_rec"] = hub.apply(
                lambda r: r["_fat"] if r["_recebido"] else 0.0, axis=1)

        S["fat_recebido"]   = float(hub["_val_rec"].sum())
        S["n_fat_recebido"] = int(hub["_recebido"].sum())

        # ── ATRASADO: vencido e não pago ──
        def detectar_atrasado(row):
            if row["_recebido"]: return False
            # Tem dias de atraso?
            if dc2:
                d = pv(row.get(dc2, 0))
                if d > 0: return True
            # Tem valor em aberto?
            if vc:
                v2 = pv(row.get(vc, 0))
                if v2 > 0: return True
            # Status inadimplente?
            if is_inad[row.name] if hasattr(row, "name") else False:
                return True
            # Data vencimento no passado?
            if venc:
                try:
                    dv = pd.to_datetime(row.get(venc), dayfirst=True)
                    if not pd.isna(dv) and dv < hoje:
                        return True
                except: pass
            return False

        hub["_atrasado"] = hub.apply(detectar_atrasado, axis=1)

        if vc:
            hub["_val_atraso"] = hub.apply(
                lambda r: pv(r[vc]) if r["_atrasado"] else 0.0, axis=1)
        else:
            hub["_val_atraso"] = hub.apply(
                lambda r: r["_fat"] if r["_atrasado"] else 0.0, axis=1)

        S["fat_atrasado"]   = float(hub["_val_atraso"].sum())
        S["n_fat_atrasado"] = int(hub["_atrasado"].sum())

        # ── A RECEBER: não vencido e não pago ──
        hub["_a_receber"] = ~hub["_recebido"] & ~hub["_atrasado"]

        hub["_val_a_rec"] = hub.apply(
            lambda r: r["_fat"] if r["_a_receber"] else 0.0, axis=1)

        S["fat_a_receber"]   = float(hub["_val_a_rec"].sum())
        S["n_fat_a_receber"] = int(hub["_a_receber"].sum())

        # ── Legado e percentuais ──
        S["fat_inad"] = S["fat_atrasado"]
        S["fat_rec"]  = S["fat_recebido"]

        if S["fat_total"] > 0:
            S["adimplencia_pct"] = round(S["fat_recebido"] / S["fat_total"] * 100, 1)
            S["inad_pct"]        = round(S["fat_atrasado"] / S["fat_total"] * 100, 1)
            S["rec_pct"]         = S["adimplencia_pct"]

        # Coluna de categoria financeira para exibição
        def cat_fin(row):
            if row["_recebido"]:  return "✅ Recebido"
            if row["_atrasado"]:  return "🔴 Atrasado"
            if row["_a_receber"]: return "🔵 A Receber"
            return "⚪ Sem classif."
        hub["_cat_fin"] = hub.apply(cat_fin, axis=1)

        # ── DFs filtrados ──
        inad = hub[hub["_atrasado"]].copy()
        if dc2:  inad["_dias"]   = inad[dc2].apply(lambda x: int(pv(x)))
        else:    inad["_dias"]   = 0
        inad["_val_ab"] = inad["_val_atraso"]
        st_session_inad = inad.sort_values("_val_ab", ascending=False)

        rec_df = hub[hub["_recebido"]].copy()
        st_session_rec = rec_df
        st_session_hub = hub
    else:
        st_session_inad = pd.DataFrame()
        st_session_rec  = pd.DataFrame()
        st_session_hub  = hub

    # ── CONTAS A PAGAR ──
    if pag is not None and not pag.empty:
        srcs.append(f"Contas a Pagar ({len(pag)} reg.)")
        pag = pag.copy()
        vc2 = dcol(pag,"vencimento","vencto","duedate","prazo","datavenc","venc")
        vv  = dcol(pag,"valor","value","amount","total")
        sc2 = dcol(pag,"status","situacao","pago","paid","estado")

        pag["_val"] = pag[vv].apply(pv) if vv else 0.0

        def cls_pag(row):
            if sc2:
                s2 = str(row[sc2]).lower()
                if any(x in s2 for x in ["pago","paid","liquidado","quitado","ok"]):
                    return "pago"
            if vc2:
                try:
                    d = pd.to_datetime(row[vc2], dayfirst=True)
                    diff = (d - hoje).days
                    if diff < 0:    return "vencida"
                    elif diff == 0: return "vence hoje"
                    elif diff <= 7: return "a vencer"
                    else:           return "em dia"
                except: return "—"
            return "—"

        pag["_st_pag"] = pag.apply(cls_pag, axis=1)
        if vc2:
            pag["_venc_d"] = pd.to_datetime(pag[vc2], dayfirst=True, errors="coerce")
            pag["_dias_v"] = (pag["_venc_d"] - hoje).dt.days.fillna(999).astype(int)
        else:
            pag["_dias_v"] = 999

        pag_ativ = pag[pag["_st_pag"] != "pago"]
        S["pag_total"]    = float(pag_ativ["_val"].sum())
        S["pag_vencidas"] = float(pag[pag["_st_pag"]=="vencida"]["_val"].sum())
        S["pag_avencer"]  = float(pag[pag["_st_pag"].isin(["a vencer","vence hoje"])]["_val"].sum())
        S["n_pag"]        = len(pag_ativ)
        S["n_pag_venc"]   = int((pag["_st_pag"]=="vencida").sum())
        S["n_pag_avenc"]  = int(pag["_st_pag"].isin(["a vencer","vence hoje"]).sum())

        ordem = {"vencida":0,"vence hoje":1,"a vencer":2,"em dia":3,"—":4,"pago":5}
        pag["_ord"] = pag["_st_pag"].map(ordem).fillna(9)
        pag = pag.sort_values(["_ord","_val"], ascending=[True,False])
        st_session_pag = pag
    else:
        st_session_pag = pag

    # Salva estado
    st_session = st  # evitar conflito de nome
    st_module  = st_session  # stats dict

    # Atualiza session_state
    import streamlit as _st
    _st.session_state.stats      = S
    _st.session_state.hub_df     = st_session_hub
    _st.session_state.inad_df    = st_session_inad
    _st.session_state.pag_df     = st_session_pag
    _st.session_state.pag_classif= st_session_pag
    _st.session_state.data_src   = " · ".join(srcs) if srcs else "Sem dados importados"
    _st.session_state.last_update= datetime.now().strftime("%d/%m/%Y %H:%M")


# ══════════════════════════════════════════════════════════
# API
# ══════════════════════════════════════════════════════════
def get_client():
    key = ""
    try:    key = st.secrets.get("ANTHROPIC_API_KEY","")
    except: pass
    if not key: key = st.session_state.get("api_key","")
    return anthropic.Anthropic(api_key=key) if key else None

def ctx_financeiro():
    s    = st.session_state.stats
    inad = st.session_state.inad_df
    pag  = st.session_state.pag_classif
    src  = st.session_state.data_src

    t_inad = ""
    if inad is not None and not inad.empty:
        nc = dcol(inad,"nome","razaosocial","cliente","name")
        if nc and "_val_ab" in inad.columns:
            t_inad = "; ".join(
                f"{r[nc]}: {brl(r['_val_ab'])} ({int(r.get('_dias',0))}d)"
                for _,r in inad.head(5).iterrows()
            )
    t_pag = ""
    if pag is not None and not pag.empty and "_st_pag" in pag.columns:
        fn = dcol(pag,"fornecedor","supplier","nome","beneficiario","empresa","name")
        venc = pag[pag["_st_pag"].isin(["vencida","vence hoje"])]
        if fn and "_val" in venc.columns:
            t_pag = "; ".join(
                f"{r[fn]}: {brl(r['_val'])} ({r['_st_pag']})"
                for _,r in venc.head(5).iterrows()
            )
    return (
        f"DADOS REAIS JET TELECOM | Fonte: {src} | Atualização: {st.session_state.last_update or 'não importado'}\n"
        f"Clientes: {s['n_clientes']} total | {s['n_ativos']} ativos | {s['n_inad']} inad. | {s['n_suspensos']} susp.\n"
        f"FINANCEIRO HUBSOFT:\n"
        f"  Faturado total: {brl(s['fat_total'])}\n"
        f"  Recebido: {brl(s['fat_recebido'])} ({s['n_fat_recebido']} faturas / {s['adimplencia_pct']}% adimplência)\n"
        f"  A Receber: {brl(s['fat_a_receber'])} ({s['n_fat_a_receber']} faturas)\n"
        f"  Atrasado: {brl(s['fat_atrasado'])} ({s['n_fat_atrasado']} faturas / {s['inad_pct']}% inadimplência)\n"
        f"Contas a pagar: {brl(s['pag_total'])} | Vencidas: {brl(s['pag_vencidas'])} ({s['n_pag_venc']}) | A vencer 7d: {brl(s['pag_avencer'])}\n"
        f"Top atrasados: {t_inad or 'nenhum'}\n"
        f"Pagamentos urgentes: {t_pag or 'nenhum'}"
    )

def cfo(prompt, max_tokens=1024):
    client = get_client()
    if not client:
        return "⚠️ Configure a chave da API Anthropic na sidebar."
    sys = (
        "Você é Maxwell, CFO IA do Grupo Jet / Jet Telecom. "
        "USE SEMPRE os dados reais do contexto fornecido — nunca invente números. "
        "Se não houver dados, oriente o usuário a importar as planilhas. "
        "Português do Brasil. Objetivo, estratégico. Emojis estratégicos. Estruture em tópicos. "
        "Máximo 400 palavras."
    )
    ctx = ctx_financeiro()
    full = f"CONTEXTO FINANCEIRO REAL:\n{ctx}\n\n---\nPERGUNTA: {prompt}"
    msgs = st.session_state.chat_history[-16:] + [{"role":"user","content":full}]
    try:
        r = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=max_tokens,
            system=sys,
            messages=msgs,
        )
        return r.content[0].text
    except Exception as e:
        return f"❌ Erro: {e}"

# ══════════════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown("""
    <div style='padding:12px 4px 10px;border-bottom:1px solid #2A2A2A;margin-bottom:8px'>
      <div style='display:flex;align-items:center;gap:8px'>
        <div style='width:30px;height:30px;background:#F05A22;border-radius:7px;
          display:flex;align-items:center;justify-content:center;
          font-weight:900;color:white;font-size:16px'>J</div>
        <div>
          <div style='color:#fff;font-size:14px;font-weight:700'>Grupo Jet</div>
          <div style='color:#444;font-size:10px;letter-spacing:.05em'>CFO INTELIGENTE</div>
        </div>
      </div>
    </div>""", unsafe_allow_html=True)

    page = st.radio("", [
        "📊  Dashboard",
        "👥  Clientes",
        "🏦  Extratos Bancários",
        "📥  Importar Planilhas",
        "📋  Contas a Pagar",
        "📈  Previsão",
        "🤝  Negociação",
        "🤖  CFO IA · Maxwell",
    ], label_visibility="collapsed")

    st.markdown("<div style='border-top:1px solid #2A2A2A;margin:10px 0'></div>", unsafe_allow_html=True)

    with st.expander("🔑 Chave API Anthropic"):
        k = st.text_input("API", type="password",
            value=st.session_state.get("api_key",""),
            placeholder="sk-ant-...", label_visibility="collapsed")
        if k: st.session_state.api_key = k; st.success("✅ Salva")
        st.caption("console.anthropic.com → API Keys")

    s = st.session_state.stats
    st.markdown(f"""
    <div style='background:#1A1A1A;border-radius:8px;padding:10px 12px;margin-top:8px;font-size:11px'>
      <div style='color:#666;margin-bottom:6px;font-weight:600;text-transform:uppercase;letter-spacing:.05em'>Status dos dados</div>
      <div style='color:{"#22A85A" if s["n_clientes"]>0 else "#444"}'>
        {"✅" if s["n_clientes"]>0 else "○"} Hubsoft: {s["n_clientes"]} clientes</div>
      <div style='color:{"#22A85A" if s["n_pag"]>0 else "#444"}'>
        {"✅" if s["n_pag"]>0 else "○"} A Pagar: {s["n_pag"]} contas</div>
      <div style='color:{"#22A85A" if st.session_state.ext_result else "#444"}'>
        {"✅" if st.session_state.ext_result else "○"} Extrato: {"analisado" if st.session_state.ext_result else "pendente"}</div>
      {f'<div style="color:#333;font-size:10px;margin-top:5px">↑ {st.session_state.last_update}</div>' if st.session_state.last_update else ""}
    </div>
    <div style='background:linear-gradient(135deg,#F05A22,#FF8040);border-radius:10px;
      padding:10px 12px;margin-top:10px'>
      <div style='color:#fff;font-size:12px;font-weight:700'>● Maxwell CFO · Online</div>
      <div style='color:rgba(255,255,255,.7);font-size:10px;margin-top:2px'>Usando dados reais importados</div>
    </div>
    """, unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════
# TOPBAR
# ══════════════════════════════════════════════════════════
s   = st.session_state.stats
src = st.session_state.data_src
now = datetime.now().strftime("%d/%m/%Y %H:%M")
st.markdown(f"""
<div class="jet-topbar">
  <div class="jet-icon">J</div>
  <div>
    <div class="jet-title">Grupo Jet · Plataforma CFO IA</div>
    <div class="jet-sub">{src} · {now}</div>
  </div>
  <div style='margin-left:auto'>
    <span class="badge-ok"><span class="dot-ok"></span>Maxwell CFO ativo</span>
  </div>
</div>""", unsafe_allow_html=True)

def show_src():
    if st.session_state.last_update:
        st.markdown(f'<div class="src-bar">📡 Dados reais · {src} · Atualizado: {st.session_state.last_update}</div>', unsafe_allow_html=True)
    else:
        st.warning("📥 Sem dados importados. Vá em **Importar Planilhas** para carregar os dados reais.")

# helper para ocultar colunas internas
def limpar(df):
    if df is None or df.empty: return pd.DataFrame()
    cols = [c for c in df.columns if not c.startswith("_")]
    return df[cols]

# ══════════════════════════════════════════════════════════
# DASHBOARD
# ══════════════════════════════════════════════════════════
if "Dashboard" in page:
    st.markdown("## Dashboard Financeiro")
    show_src()
    tem = s["n_clientes"] > 0 or s["n_pag"] > 0

    c1,c2,c3,c4 = st.columns(4)
    def kpi_html(lbl, val, sub, cls):
        return f'<div class="kpi"><div class="kpi-l">{lbl}</div><div class="kpi-v">{val}</div><div class="kpi-d {cls}">{sub}</div></div>'

    with c1: st.markdown(kpi_html("Faturamento Carteira",
        brl(s["fat_total"]) if tem else "—",
        f"{s['n_ativos']} ativos" if tem else "sem dados","pos"), unsafe_allow_html=True)
    with c2: st.markdown(kpi_html("Recebimento Est.",
        brl(s["fat_rec"]) if tem else "—",
        f"{s['rec_pct']}% da carteira" if tem else "sem dados","pos"), unsafe_allow_html=True)
    with c3: st.markdown(kpi_html("Inadimplência",
        brl(s["fat_inad"]) if tem else "—",
        f"{s['n_inad']} clientes ({s['inad_pct']}%)" if tem else "sem dados",
        "neg" if s["inad_pct"]>5 else "warn"), unsafe_allow_html=True)
    with c4: st.markdown(kpi_html("Contas a Pagar",
        brl(s["pag_total"]) if s["n_pag"] else "—",
        f"{s['n_pag_venc']} vencidas" if s["n_pag"] else "sem dados",
        "neg" if s["n_pag_venc"]>0 else "muted"), unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    col_g, col_a = st.columns([1.6,1])

    with col_g:
        hub = st.session_state.hub_df
        if hub is not None and not hub.empty and "_st" in hub.columns and "_mens" in hub.columns:
            grp = hub.groupby("_st")["_mens"].sum().reset_index()
            grp.columns = ["Status","Valor"]
            cores = {"ativo":"#22A85A","inadimplente":"#D93025","suspenso":"#D97706","cancelado":"#888"}
            fig = go.Figure(go.Bar(
                x=grp["Status"], y=grp["Valor"],
                marker_color=[cores.get(s_,"#AAA") for s_ in grp["Status"]],
                text=[brl(v) for v in grp["Valor"]],
                textposition="outside", textfont_size=11
            ))
            fig.update_layout(title="Faturamento por status (dados reais)", height=230,
                margin=dict(t=36,b=0,l=0,r=0),
                plot_bgcolor="white", paper_bgcolor="white",
                yaxis=dict(visible=False), xaxis=dict(gridcolor="white"))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("📊 Importe a planilha Hubsoft para ver os gráficos reais.")

    with col_a:
        st.markdown("**⚡ Prioridades imediatas**")
        pag_c = st.session_state.pag_classif
        inad  = st.session_state.inad_df
        mostrou = False

        if pag_c is not None and not pag_c.empty and "_st_pag" in pag_c.columns:
            fn = dcol(pag_c,"fornecedor","supplier","nome","beneficiario","empresa","name")
            urg = pag_c[pag_c["_st_pag"].isin(["vencida","vence hoje","a vencer"])].head(4)
            for _,row in urg.iterrows():
                nm  = str(row[fn])[:28] if fn else "Conta"
                val = brl(row["_val"]) if "_val" in row else "—"
                sp  = row["_st_pag"]
                cor = "#D93025" if sp in ["vencida","vence hoje"] else "#D97706"
                st.markdown(f"""
                <div style='display:flex;align-items:center;gap:8px;background:#F6F4F1;
                  border-radius:8px;padding:8px 11px;margin-bottom:5px'>
                  <div style='width:7px;height:7px;border-radius:50%;background:{cor};flex-shrink:0'></div>
                  <div style='flex:1;font-size:12px;font-weight:600'>{nm}</div>
                  <div style='font-weight:700;color:{cor};font-size:12px'>{val}</div>
                  <span class="pill {'er' if cor=='#D93025' else 'wa'}">{sp}</span>
                </div>""", unsafe_allow_html=True)
                mostrou = True

        if not mostrou and inad is not None and not inad.empty:
            nc = dcol(inad,"nome","razaosocial","cliente","name")
            for _,row in inad.head(3).iterrows():
                nm  = str(row[nc])[:28] if nc else "Cliente"
                val = brl(row["_val_ab"]) if "_val_ab" in row else "—"
                st.markdown(f"""
                <div style='display:flex;align-items:center;gap:8px;background:#F6F4F1;
                  border-radius:8px;padding:8px 11px;margin-bottom:5px'>
                  <div style='width:7px;height:7px;border-radius:50%;background:#D93025;flex-shrink:0'></div>
                  <div style='flex:1;font-size:12px;font-weight:600'>{nm}</div>
                  <div style='font-weight:700;color:#D93025;font-size:12px'>{val}</div>
                  <span class="pill er">Inad.</span>
                </div>""", unsafe_allow_html=True)
                mostrou = True

        if not mostrou:
            st.info("Importe dados para ver alertas reais.")

    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("🧠 Diagnóstico rápido CFO IA (dados reais)", type="primary", use_container_width=True):
        with st.spinner("Maxwell analisando..."):
            resp = cfo("Faça um diagnóstico financeiro em 4 pontos com os dados reais. Destaque o ponto crítico e a ação imediata.", max_tokens=600)
        st.markdown(f'<div class="insight">{resp.replace(chr(10),"<br>")}</div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════
# CLIENTES
# ══════════════════════════════════════════════════════════
elif "Clientes" in page:
    st.markdown("## Clientes & Carteira")
    show_src()
    hub = st.session_state.hub_df
    if hub is None or hub.empty:
        st.info("📥 Importe a planilha Hubsoft em **Importar Planilhas**.")
        st.stop()

    s = st.session_state.stats
    c1,c2,c3,c4,c5 = st.columns(5)
    c1.metric("Total",      s["n_clientes"])
    c2.metric("Ativos",     s["n_ativos"])
    c3.metric("Inad.",      s["n_inad"],       delta=f"{s['inad_pct']}%" if s["n_inad"] else None, delta_color="inverse")
    c4.metric("Suspensos",  s["n_suspensos"])
    c5.metric("Cancelados", s["n_cancelados"])

    f1,f2,f3 = st.columns([3,1,1])
    with f1: busca = st.text_input("🔍 Buscar...", key="cs")
    with f2: fst   = st.selectbox("Status", ["Todos","ativo","inadimplente","suspenso","cancelado"], key="cst")
    with f3:
        if st.button("🤖 Análise CFO", type="primary", use_container_width=True):
            with st.spinner("Analisando..."):
                resp = cfo("Analise a carteira de clientes. Destaque os 3 principais riscos e 3 ações imediatas.")
            st.markdown(f'<div class="insight">{resp.replace(chr(10),"<br>")}</div>', unsafe_allow_html=True)

    df_v = limpar(hub)
    if busca:
        df_v = df_v[df_v.apply(lambda r: busca.lower() in " ".join(r.astype(str).str.lower()), axis=1)]
    if fst != "Todos":
        sc = dcol(hub,"status","situacao","estado")
        if sc and sc in df_v.columns:
            df_v = df_v[df_v[sc].astype(str).str.lower().str.contains(fst)]

    st.markdown(f"**{len(df_v)} registros**")
    st.dataframe(df_v, use_container_width=True, height=380, hide_index=True)

    if "_st" in hub.columns:
        grp = hub.groupby("_st").size().reset_index(name="n")
        fig = go.Figure(go.Pie(labels=grp["_st"], values=grp["n"],
            marker_colors=["#22A85A","#D93025","#D97706","#888"],
            hole=0.6, textinfo="percent+label", textfont_size=11))
        fig.update_layout(title="Distribuição por status (dados reais)",
            height=200, margin=dict(t=30,b=0,l=0,r=0),
            showlegend=False, paper_bgcolor="white")
        st.plotly_chart(fig, use_container_width=True)


# ══════════════════════════════════════════════════════════
# EXTRATOS
# ══════════════════════════════════════════════════════════
elif "Extratos" in page:
    st.markdown("## Extratos Bancários")
    show_src()

    bancos = {
        "BTG Pactual":"🔵","Caixa Econômica Federal":"💙",
        "C6 Bank":"⚫","Banco Safra":"🔴","Banco do Brasil":"🟡"
    }
    col_f, col_r = st.columns([1,1.1])
    with col_f:
        banco = st.radio("Banco", list(bancos.keys()),
            format_func=lambda b: f"{bancos[b]} {b}", label_visibility="collapsed")
        c1,c2 = st.columns(2)
        with c1: dti = st.date_input("De",  value=date.today().replace(day=1), label_visibility="collapsed")
        with c2: dtf = st.date_input("Até", value=date.today(), label_visibility="collapsed")
        emp  = st.text_input("Empresa", "Grupo Jet")
        tipo = st.selectbox("Tipo", ["Análise completa","Fluxo de caixa","Receitas e despesas","Inadimplência","Planejamento"])

        ups = st.file_uploader("Extrato", type=["pdf","csv","ofx","txt","xlsx","xls"],
            accept_multiple_files=True, label_visibility="collapsed")
        if ups:
            for f in ups: st.markdown(f"✅ **{f.name}** · {f.size//1024}KB")

            if st.button("🤖 Analisar com CFO IA", type="primary", use_container_width=True):
                with st.spinner("Lendo extrato completo..."):
                    ofx_data  = None   # resultado do parser OFX
                    txt_extra = ""     # para CSV/XLSX

                    for f in ups:
                        name = f.name.lower()
                        try:
                            if name.endswith(".ofx"):
                                # ── PARSER OFX COMPLETO (lê 100% das transações) ──
                                f.seek(0)
                                for enc in ["latin-1","cp1252","utf-8"]:
                                    try:
                                        raw_ofx = f.read().decode(enc)
                                        ofx_data = parse_ofx(raw_ofx)
                                        break
                                    except: pass

                            elif name.endswith(".csv"):
                                f.seek(0)
                                for enc in ["utf-8","latin-1","cp1252"]:
                                    try:
                                        txt_extra += f"\n---{f.name}---\n" + f.read().decode(enc)[:4000]
                                        break
                                    except: pass

                            elif name.endswith((".xlsx",".xls")):
                                f.seek(0)
                                df_e = pd.read_excel(f)
                                txt_extra += f"\n---{f.name}---\n" + df_e.head(80).to_string()

                        except Exception as ex:
                            txt_extra += f"\nErro ao ler {f.name}: {ex}"

                    # ── Monta contexto para o CFO IA ──
                    ctx_safe = ctx_financeiro().replace('"',"\'").replace("\n"," | ")

                    if ofx_data:
                        o = ofx_data
                        brl_f = lambda v: f"R$ {float(v):,.2f}".replace(".", "X").replace(",", ".").replace("X", ",")
                        top_e_txt = " | ".join(f"{r['memo'][:40]} ({brl_f(r['valor'])})" for r in o["top_ent"][:5])
                        top_s_txt = " | ".join(f"{r['memo'][:40]} ({brl_f(r['valor'])})" for r in o["top_sai"][:5])
                        cats_txt  = " | ".join(f"{cat}: ent={brl_f(v['ent'])} sai={brl_f(v['sai'])} n={v['n']}"
                                               for cat,v in o["cats"].items())
                        prompt = (
                            f"CONTEXTO EMPRESA: {ctx_safe}\n\n"
                            f"EXTRATO OFX COMPLETO — Banco: {o['banco']} | Conta: {o['conta']} | Periodo: {o['periodo']}\n"
                            f"Total transacoes: {o['n_trans']}\n"
                            f"Entradas totais: {brl_f(o['entradas'])}\n"
                            f"Saidas totais:   {brl_f(o['saidas'])}\n"
                            f"Saldo atual:     {brl_f(o['saldo'])}\n"
                            f"Por categoria: {cats_txt}\n"
                            f"Top 5 maiores entradas: {top_e_txt}\n"
                            f"Top 5 maiores saidas:   {top_s_txt}\n\n"
                            f"Analise solicitada: {tipo}\n\n"
                            "Responda SOMENTE JSON valido e COMPLETO sem texto extra:\n"
                            '{"resumo":{"entradas":"R$ X","saidas":"R$ X","saldo":"R$ X","transacoes":0},'
                            '"parecer":"analise estrategica em 2 frases",'
                            '"insights":["insight 1","insight 2","insight 3"],'
                            '"alertas":[{"tipo":"warn","texto":"alerta"}],'
                            '"recomendacoes":["acao 1","acao 2","acao 3"],'
                            '"transacoes_destaque":[{"desc":"memo","valor":"R$ X","tipo":"entrada","data":"DD/MM"}]}'
                        )
                        # Monta transacoes_destaque direto dos dados reais (sem depender da IA)
                        trans_dest = (
                            [{"desc":r["memo"],"valor":brl_f(r["valor"]),"tipo":"entrada","data":r["data"]} for r in o["top_ent"][:4]] +
                            [{"desc":r["memo"],"valor":brl_f(abs(r["valor"])),"tipo":"saida","data":r["data"]} for r in o["top_sai"][:4]]
                        )
                        resumo_real = {
                            "entradas":   brl_f(o["entradas"]),
                            "saidas":     brl_f(o["saidas"]),
                            "saldo":      brl_f(o["saldo"]),
                            "transacoes": o["n_trans"],
                        }
                    else:
                        txt_safe = txt_extra[:3000].replace('"',"\'")
                        prompt = (
                            f"CONTEXTO: {ctx_safe}\n\n"
                            f"EXTRATO: {banco} | {dti} a {dtf} | {emp} | {tipo}\n"
                            f"DADOS:\n{txt_safe}\n\n"
                            "Responda SOMENTE JSON:\n"
                            '{"resumo":{"entradas":"R$ X","saidas":"R$ X","saldo":"R$ X","transacoes":0},'
                            '"parecer":"analise em 2 frases","insights":["i1"],"alertas":[{"tipo":"warn","texto":"a"}],'
                            '"recomendacoes":["r1"],"transacoes_destaque":[{"desc":"d","valor":"R$ X","tipo":"entrada","data":"DD/MM"}]}'
                        )
                        resumo_real = None
                        trans_dest  = None

                    sys_e = (
                        "Voce e Maxwell CFO IA do Grupo Jet/Jet Telecom. "
                        "Os dados do extrato ja foram pre-calculados e estao no prompt. "
                        "Use os numeros exatos fornecidos. "
                        "Responda APENAS JSON valido e COMPLETO. Nunca truncar."
                    )
                    raw = ""
                    try:
                        r = get_client().messages.create(
                            model="claude-sonnet-4-6",
                            max_tokens=1500,
                            system=sys_e,
                            messages=[{"role":"user","content":prompt}]
                        )
                        raw = r.content[0].text.strip()
                        raw = raw.replace("```json","").replace("```","").strip()
                        s_idx = raw.find("{"); e_idx = raw.rfind("}") + 1
                        if s_idx >= 0 and e_idx > s_idx:
                            raw = raw[s_idx:e_idx]
                        j = json.loads(raw)
                        # Se temos dados reais do OFX, substitui os valores calculados
                        if resumo_real:
                            j["resumo"] = resumo_real
                        if trans_dest:
                            j["transacoes_destaque"] = trans_dest
                        st.session_state.ext_result = j
                        st.rerun()
                    except json.JSONDecodeError:
                        # Fallback: monta resultado direto dos dados OFX sem depender de JSON da IA
                        if ofx_data:
                            o = ofx_data
                            brl_f = lambda v: f"R$ {float(v):,.2f}".replace(".", "X").replace(",", ".").replace("X", ",")
                            st.session_state.ext_result = {
                                "resumo": resumo_real,
                                "parecer": f"Extrato {o['banco']} ({o['periodo']}): {o['n_trans']} transacoes. Entradas {brl_f(o['entradas'])}, saidas {brl_f(o['saidas'])}, saldo {brl_f(o['saldo'])}.",
                                "insights": [
                                    f"Total de {o['n_trans']} transacoes no periodo {o['periodo']}",
                                    f"Maiores entradas: {top_e_txt[:120]}",
                                    f"Maiores saidas: {top_s_txt[:120]}",
                                ],
                                "alertas": [{"tipo":"warn","texto":"Analise textual gerada diretamente dos dados OFX (JSON da IA incompleto)."}],
                                "recomendacoes": ["Verifique as maiores saidas para RDMI Participacoes.","Acompanhe o saldo diario."],
                                "transacoes_destaque": trans_dest,
                            }
                        else:
                            st.session_state.ext_result = {
                                "resumo":{"entradas":"—","saidas":"—","saldo":"—","transacoes":0},
                                "parecer":"Nao foi possivel processar o arquivo.",
                                "insights":["Tente exportar como CSV pelo internet banking."],
                                "alertas":[{"tipo":"warn","texto":"Arquivo nao lido."}],
                                "recomendacoes":["Use formato CSV ou OFX padrao."],
                                "transacoes_destaque":[],
                            }
                        st.rerun()
                    except Exception as e:
                        st.error(f"Erro na API: {e}")



    with col_r:
        st.markdown("**🧠 Análise do CFO**")
        res = st.session_state.ext_result
        if res:
            rm = res.get("resumo",{})
            m1,m2 = st.columns(2)
            m1.metric("Entradas",   rm.get("entradas","—"))
            m2.metric("Saídas",     rm.get("saidas","—"))
            m1.metric("Saldo",      rm.get("saldo","—"))
            m2.metric("Transações", rm.get("transacoes","—"))
            st.markdown(f'<div class="insight">{res.get("parecer","")}</div>', unsafe_allow_html=True)
            for a in res.get("alertas",[]):
                {"danger":st.error,"success":st.success,"warn":st.warning}.get(a.get("tipo","warn"),st.warning)(a.get("texto",""))
            tr = res.get("transacoes_destaque",[])
            if tr:
                st.markdown("**📌 Transações em destaque**")
                for t in tr[:5]:
                    isE = t.get("tipo")=="entrada"
                    cor = "#22A85A" if isE else "#D93025"
                    st.markdown(f"""
                    <div style='display:flex;align-items:center;gap:8px;background:#F6F4F1;
                      border-radius:7px;padding:7px 10px;margin-bottom:5px;font-size:12px'>
                      <span>{"↙️" if isE else "↗️"}</span>
                      <div style='flex:1;font-weight:600'>{t.get("desc","")}</div>
                      <div style='color:#6E6E6E'>{t.get("data","")}</div>
                      <div style='font-weight:700;color:{cor}'>{t.get("valor","")}</div>
                    </div>""", unsafe_allow_html=True)
            recs = res.get("recomendacoes",[])
            if recs:
                st.markdown("**🎯 Recomendações**")
                for i,r in enumerate(recs,1): st.markdown(f"**{i}.** {r}")
        else:
            st.info("Envie um extrato para análise.")


# ══════════════════════════════════════════════════════════
# IMPORTAR PLANILHAS
# ══════════════════════════════════════════════════════════
elif "Importar" in page:
    st.markdown("## Importar Planilhas")
    st.markdown("**Dados importados aqui alimentam automaticamente todos os módulos da plataforma.**")

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("#### 🏪 Planilha Hubsoft")
        st.caption("Exporte: Relatórios → Clientes / Faturamento / Inadimplência")
        if st.session_state.hub_df is not None:
            hub_raw = st.session_state.hub_df
            n_rows  = len(limpar(hub_raw))
            st.success(f"✅ **{n_rows}** registros carregados")

            # ── Seletor de colunas ──
            with st.expander("⚙️ Configurar colunas (clique se os valores estiverem errados)", expanded=st.session_state.get("col_expanded", False)):
                st.caption("Selecione qual coluna da planilha representa cada informação financeira:")
                cols_disp = ["(auto)"] + list(hub_raw.columns)

                # Mostra amostra de valores para ajudar o usuário
                st.markdown("**Prévia das primeiras linhas:**")
                st.dataframe(hub_raw.head(3), use_container_width=True, hide_index=True)

                g1, g2 = st.columns(2)
                with g1:
                    col_valor = st.selectbox("💰 Coluna de valor/mensalidade:",
                        cols_disp, key="col_valor",
                        index=0,
                        help="Valor mensal cobrado por cliente")
                    col_status = st.selectbox("📌 Coluna de status:",
                        cols_disp, key="col_status",
                        index=0,
                        help="Status do cliente: ativo, inadimplente, etc")
                    col_pago = st.selectbox("✅ Coluna de data/valor pago:",
                        cols_disp, key="col_pago",
                        index=0,
                        help="Data de pagamento ou valor efetivamente pago")
                with g2:
                    col_atraso = st.selectbox("🔴 Coluna de valor em atraso:",
                        cols_disp, key="col_atraso",
                        index=0,
                        help="Valor em aberto ou atrasado")
                    col_dias = st.selectbox("⏱ Coluna de dias de atraso:",
                        cols_disp, key="col_dias",
                        index=0,
                        help="Número de dias em atraso")
                    col_venc = st.selectbox("📅 Coluna de vencimento:",
                        cols_disp, key="col_venc",
                        index=0,
                        help="Data de vencimento da fatura")

                # Salva mapeamento manual
                col_map = {
                    "valor":  col_valor  if col_valor  != "(auto)" else None,
                    "status": col_status if col_status != "(auto)" else None,
                    "pago":   col_pago   if col_pago   != "(auto)" else None,
                    "atraso": col_atraso if col_atraso != "(auto)" else None,
                    "dias":   col_dias   if col_dias   != "(auto)" else None,
                    "venc":   col_venc   if col_venc   != "(auto)" else None,
                }
                st.session_state.hub_col_map = col_map

                if st.button("🔄 Reaplicar com estas colunas", type="primary", use_container_width=True):
                    st.session_state.col_expanded = True
                    recalc()
                    st.rerun()

                # Mostra média por cliente para validação
                s_prev = st.session_state.stats
                if s_prev["fat_total"] > 0 and s_prev["n_clientes"] > 0:
                    media = s_prev["fat_total"] / s_prev["n_clientes"]
                    st.markdown(f"""
                    <div style='background:#F6F4F1;border-radius:8px;padding:10px 12px;margin-top:8px;font-size:12px'>
                        📊 <strong>Validação:</strong> Média por cliente = <strong>{brl(media)}</strong>
                        {'✅ Parece correto' if 50 < media < 50000 else '⚠️ Valor suspeito — verifique a coluna selecionada'}
                    </div>""", unsafe_allow_html=True)

            if st.button("🗑️ Remover Hubsoft"):
                st.session_state.hub_df = None
                st.session_state.hub_col_map = {}
                st.session_state.inad_df = pd.DataFrame()
                st.session_state.col_expanded = False
                recalc()
                st.rerun()
        else:
            if "hub_col_map" not in st.session_state:
                st.session_state.hub_col_map = {}
            fh = st.file_uploader("Hubsoft", type=["xlsx","xls","csv"],
                label_visibility="collapsed", key="hu")
            if fh:
                with st.spinner(f"Lendo {fh.name}..."):
                    df = read_file(fh)
                if df is not None and not df.empty:
                    st.session_state.hub_df = df
                    st.session_state.hub_col_map = {}
                    st.session_state.col_expanded = True  # abre config automaticamente
                    recalc()
                    st.success(f"✅ {fh.name} · {len(df)} linhas importadas!")
                    st.rerun()
                else:
                    st.error("Não foi possível ler o arquivo.")

    with col2:
        st.markdown("#### 📋 Contas a Pagar")
        st.caption("Vencidas e a vencer — qualquer formato")
        if st.session_state.pag_classif is not None and not st.session_state.pag_classif.empty:
            n = len(limpar(st.session_state.pag_classif))
            st.success(f"✅ **{n}** contas carregadas")
            st.dataframe(limpar(st.session_state.pag_classif).head(8), use_container_width=True, hide_index=True)
            if st.button("🗑️ Remover Contas a Pagar"):
                st.session_state.pag_df = None
                st.session_state.pag_classif = pd.DataFrame()
                recalc()
                st.rerun()
        else:
            fp = st.file_uploader("Contas a Pagar", type=["xlsx","xls","csv"],
                label_visibility="collapsed", key="pu")
            if fp:
                with st.spinner(f"Lendo {fp.name}..."):
                    df = read_file(fp)
                if df is not None and not df.empty:
                    st.session_state.pag_df = df
                    recalc()
                    st.success(f"✅ {fp.name} · {len(df)} linhas importadas!")
                    st.rerun()
                else:
                    st.error("Não foi possível ler o arquivo.")

    # ── KPIs e tabelas ──
    s = st.session_state.stats
    tem = s["n_clientes"] > 0 or s["n_pag"] > 0
    if tem:
        st.markdown("---")

        # ── PAINEL FINANCEIRO 4 CATEGORIAS ──
        st.markdown("### 💰 Painel Financeiro — Faturamento Hubsoft")
        k1,k2,k3,k4 = st.columns(4)
        with k1:
            st.markdown(f"""
            <div class="kpi" style="border-left:4px solid #555">
              <div class="kpi-l">📋 Faturado</div>
              <div class="kpi-v">{brl(s["fat_total"])}</div>
              <div class="kpi-d muted">{s["n_clientes"]} clientes</div>
            </div>""", unsafe_allow_html=True)
        with k2:
            pct_rec = s["adimplencia_pct"]
            st.markdown(f"""
            <div class="kpi" style="border-left:4px solid #22A85A">
              <div class="kpi-l">✅ Recebido</div>
              <div class="kpi-v" style="color:#22A85A">{brl(s["fat_recebido"])}</div>
              <div class="kpi-d pos">{s["n_fat_recebido"]} faturas · {pct_rec}% do total</div>
            </div>""", unsafe_allow_html=True)
        with k3:
            st.markdown(f"""
            <div class="kpi" style="border-left:4px solid #1D6FA4">
              <div class="kpi-l">🔵 A Receber</div>
              <div class="kpi-v" style="color:#1D6FA4">{brl(s["fat_a_receber"])}</div>
              <div class="kpi-d muted">{s["n_fat_a_receber"]} faturas em aberto</div>
            </div>""", unsafe_allow_html=True)
        with k4:
            pct_at = s["inad_pct"]
            cor_at = "#D93025" if pct_at > 5 else "#D97706"
            st.markdown(f"""
            <div class="kpi" style="border-left:4px solid {cor_at}">
              <div class="kpi-l">🔴 Atrasado</div>
              <div class="kpi-v" style="color:{cor_at}">{brl(s["fat_atrasado"])}</div>
              <div class="kpi-d neg">{s["n_fat_atrasado"]} faturas · {pct_at}% do total</div>
            </div>""", unsafe_allow_html=True)

        # Barra de composição visual
        if s["fat_total"] > 0:
            t = s["fat_total"]
            p_rec = s["fat_recebido"]/t*100
            p_are = s["fat_a_receber"]/t*100
            p_ats = s["fat_atrasado"]/t*100
            p_out = max(0, 100 - p_rec - p_are - p_ats)
            st.markdown(f"""
            <div style="margin:12px 0 4px;font-size:11px;color:#6E6E6E;font-weight:600">COMPOSIÇÃO DO FATURAMENTO</div>
            <div style="display:flex;height:18px;border-radius:6px;overflow:hidden;gap:1px">
              <div style="width:{p_rec:.1f}%;background:#22A85A;title:Recebido" title="Recebido {p_rec:.1f}%"></div>
              <div style="width:{p_are:.1f}%;background:#1D6FA4" title="A Receber {p_are:.1f}%"></div>
              <div style="width:{p_ats:.1f}%;background:#D93025" title="Atrasado {p_ats:.1f}%"></div>
              <div style="width:{p_out:.1f}%;background:#DDD" title="Outros {p_out:.1f}%"></div>
            </div>
            <div style="display:flex;gap:16px;margin-top:5px;font-size:11px">
              <span style="color:#22A85A">■ Recebido {p_rec:.1f}%</span>
              <span style="color:#1D6FA4">■ A receber {p_are:.1f}%</span>
              <span style="color:#D93025">■ Atrasado {p_ats:.1f}%</span>
            </div>
            """, unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)

        tab1,tab2,tab3,tab4,tab5,tab6 = st.tabs([
            "👥 Todos Clientes",
            "✅ Recebido",
            "🔵 A Receber",
            "🔴 Atrasado",
            "📋 Contas a Pagar",
            "🤖 Análise CFO"
        ])

        with tab1:
            hub = st.session_state.hub_df
            if hub is not None and not hub.empty:
                df_v = limpar(hub).copy()
                if "_cat_fin" in hub.columns: df_v.insert(0,"💰 Situação", hub["_cat_fin"])
                if "_fat"     in hub.columns: df_v.insert(1,"Faturado",    hub["_fat"].apply(brl))
                if "_val_rec" in hub.columns: df_v.insert(2,"Recebido",    hub["_val_rec"].apply(brl))
                if "_val_a_rec" in hub.columns: df_v.insert(3,"A Receber", hub["_val_a_rec"].apply(brl))
                if "_val_atraso" in hub.columns: df_v.insert(4,"Atrasado", hub["_val_atraso"].apply(brl))
                # Filtro rápido
                f_cat = st.selectbox("Filtrar por situação:",
                    ["Todos","✅ Recebido","🔵 A Receber","🔴 Atrasado","⚪ Sem classif."],
                    key="tab1_fcat")
                if f_cat != "Todos" and "_cat_fin" in hub.columns:
                    df_v = df_v[hub["_cat_fin"] == f_cat]
                st.markdown(f"**{len(df_v)} registros**")
                st.dataframe(df_v, use_container_width=True, height=340, hide_index=True)
            else:
                st.info("Importe a planilha Hubsoft.")

        with tab2:
            hub = st.session_state.hub_df
            if hub is not None and not hub.empty and "_recebido" in hub.columns:
                df_r = limpar(hub[hub["_recebido"]]).copy()
                if "_val_rec" in hub.columns:
                    df_r["💵 Valor Recebido"] = hub[hub["_recebido"]]["_val_rec"].apply(brl)
                total_r = s["fat_recebido"]
                st.metric("Total Recebido", brl(total_r), f"{s['n_fat_recebido']} faturas")
                st.dataframe(df_r, use_container_width=True, height=300, hide_index=True)
            else:
                st.info("Nenhum recebimento identificado nos dados.")

        with tab3:
            hub = st.session_state.hub_df
            if hub is not None and not hub.empty and "_a_receber" in hub.columns:
                df_ar = limpar(hub[hub["_a_receber"]]).copy()
                if "_val_a_rec" in hub.columns:
                    df_ar["🔵 A Receber"] = hub[hub["_a_receber"]]["_val_a_rec"].apply(brl)
                st.metric("Total a Receber", brl(s["fat_a_receber"]), f"{s['n_fat_a_receber']} faturas")
                st.dataframe(df_ar, use_container_width=True, height=300, hide_index=True)
            else:
                st.info("Nenhum valor a receber identificado.")

        with tab4:
            inad = st.session_state.inad_df
            if inad is not None and not inad.empty:
                df_i = limpar(inad).copy()
                if "_val_ab" in inad.columns: df_i["🔴 Valor Atrasado"] = inad["_val_ab"].apply(brl)
                if "_dias"   in inad.columns: df_i["⏱ Dias Atraso"]    = inad["_dias"].astype(int)
                c1a, c2a, c3a = st.columns(3)
                c1a.metric("Total Atrasado", brl(s["fat_atrasado"]))
                c2a.metric("Nº de clientes", s["n_fat_atrasado"])
                c3a.metric("% do faturamento", f"{s['inad_pct']}%")
                st.dataframe(df_i, use_container_width=True, height=300, hide_index=True)
                if st.button("🤖 Estratégia de cobrança IA", type="primary"):
                    with st.spinner("Maxwell gerando estratégia..."):
                        resp = cfo(f"Com {s['n_fat_atrasado']} clientes atrasados e {brl(s['fat_atrasado'])} em aberto, gere estratégia de cobrança segmentada por valor e dias de atraso.")
                    st.markdown(f'<div class="insight">{resp.replace(chr(10),"<br>")}</div>', unsafe_allow_html=True)
            else:
                st.success("✅ Nenhum valor atrasado identificado nos dados.")

        with tab5:
            pc = st.session_state.pag_classif
            if pc is not None and not pc.empty:
                df_p = limpar(pc).copy()
                if "_val"    in pc.columns: df_p["Valor"]       = pc["_val"].apply(brl)
                if "_st_pag" in pc.columns: df_p["Status"]      = pc["_st_pag"]
                if "_dias_v" in pc.columns: df_p["Dias p/Venc"] = pc["_dias_v"].apply(lambda x: int(x) if x < 900 else "—")
                st.dataframe(df_p, use_container_width=True, height=300, hide_index=True)
            else:
                st.info("Importe a planilha de contas a pagar.")

        with tab6:
            if st.button("🤖 Gerar análise CFO completa com dados reais", type="primary", use_container_width=True):
                with st.spinner("Maxwell analisando todos os dados..."):
                    resp = cfo(
                        f"Relatório executivo CFO: "
                        f"Faturado={brl(s['fat_total'])}, Recebido={brl(s['fat_recebido'])}, "
                        f"A Receber={brl(s['fat_a_receber'])}, Atrasado={brl(s['fat_atrasado'])}. "
                        "1) Diagnóstico e risco de liquidez "
                        "2) Prioridade de pagamentos justificada "
                        "3) Estratégia de cobrança segmentada "
                        "4) Alertas críticos e ações imediatas "
                        "5) Projeção 30 dias. "
                        "Use APENAS dados reais.",
                        max_tokens=1200
                    )
                st.markdown(f'<div class="insight">{resp.replace(chr(10),"<br>")}</div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════
# CONTAS A PAGAR
# ══════════════════════════════════════════════════════════
elif "Contas" in page:
    st.markdown("## Contas a Pagar")
    show_src()
    s  = st.session_state.stats
    pc = st.session_state.pag_classif

    c1,c2,c3,c4 = st.columns(4)
    c1.metric("Total a Pagar",  brl(s["pag_total"])    if s["n_pag"] else "—", f"{s['n_pag']} contas")
    c2.metric("Vencidas",       brl(s["pag_vencidas"]) if s["n_pag"] else "—", f"{s['n_pag_venc']} contas", delta_color="inverse")
    c3.metric("A vencer 7 dias",brl(s["pag_avencer"])  if s["n_pag"] else "—", f"{s['n_pag_avenc']} contas", delta_color="inverse")
    c4.metric("Faturamento",    brl(s["fat_total"])     if s["n_clientes"] else "—", "Disponível para cobrir")

    if pc is not None and not pc.empty and "_st_pag" in pc.columns:
        ativ = pc[pc["_st_pag"] != "pago"]
        df_m = limpar(ativ).copy()
        if "_val"    in ativ.columns: df_m["💰 Valor"]  = ativ["_val"].apply(brl)
        if "_st_pag" in ativ.columns: df_m["📌 Status"] = ativ["_st_pag"]
        if "_dias_v" in ativ.columns: df_m["⏱ Dias"]   = ativ["_dias_v"].apply(lambda x: int(x) if x < 900 else "—")

        st.markdown(f"**{len(df_m)} contas pendentes — ordenadas por urgência**")
        st.dataframe(df_m, use_container_width=True, height=350, hide_index=True)

        grp = pc["_st_pag"].value_counts().reset_index()
        grp.columns=["status","n"]
        cores = {"vencida":"#D93025","vence hoje":"#FF6B35","a vencer":"#D97706","em dia":"#22A85A","pago":"#CCC"}
        fig = go.Figure(go.Bar(x=grp["status"], y=grp["n"],
            marker_color=[cores.get(ss,"#888") for ss in grp["status"]],
            text=grp["n"], textposition="outside"))
        fig.update_layout(title="Contas por status", height=180,
            margin=dict(t=30,b=0,l=0,r=0), plot_bgcolor="white",
            paper_bgcolor="white", yaxis=dict(visible=False))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("📥 Importe a planilha de contas a pagar em **Importar Planilhas**.")

    if st.button("🤖 Estratégia de pagamento CFO IA", type="primary"):
        with st.spinner("Analisando..."):
            resp = cfo("Com os dados reais das contas a pagar e faturamento, gere um plano de pagamento prioritizado para 30 dias considerando o fluxo de caixa disponível.")
        st.markdown(f'<div class="insight">{resp.replace(chr(10),"<br>")}</div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════
# PREVISÃO
# ══════════════════════════════════════════════════════════
elif "Previsão" in page:
    st.markdown("## Previsão Estratégica")
    show_src()
    s = st.session_state.stats
    fat = s["fat_total"] if s["fat_total"] > 0 else 0
    pag = s["pag_total"] if s["pag_total"] > 0 else 0

    if fat > 0:
        oti = fat * 1.15; base = fat; cons = fat * 0.85; be = pag if pag > 0 else fat * 0.80
        nota = "Baseado nos dados reais importados"
    else:
        oti = 4830000; base = 4200000; cons = 3570000; be = 3400000
        nota = "⚠️ Dados de referência — importe o Hubsoft para projeções reais"

    c1,c2,c3,c4 = st.columns(4)
    c1.metric("Otimista (+15%)",   brl(oti),  "+15% crescimento")
    c2.metric("Base (atual)",      brl(base), nota[:30])
    c3.metric("Conservador (-15%)",brl(cons), "-15% retração", delta_color="inverse")
    c4.metric("Break-even",        brl(be),   "Mínimo operacional")

    if fat == 0:
        st.info(nota)

    meses = ["Jun","Jul","Ago","Set","Out","Nov","Dez","Jan","Fev","Mar","Abr","Mai"]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=meses, y=[oti*(1+i*0.012)  for i in range(12)],
        name="Otimista",line=dict(color="#22A85A",width=1.5,dash="dot"),mode="lines+markers",marker=dict(size=4)))
    fig.add_trace(go.Scatter(x=meses, y=[base*(1+i*0.008) for i in range(12)],
        name="Base (real)",line=dict(color="#F05A22",width=2.5),mode="lines+markers",marker=dict(size=5)))
    fig.add_trace(go.Scatter(x=meses, y=[cons*(1-i*0.004) for i in range(12)],
        name="Conservador",line=dict(color="#D93025",width=1.5,dash="dot"),mode="lines+markers",marker=dict(size=4)))
    if pag > 0:
        fig.add_trace(go.Scatter(x=meses, y=[pag]*12,
            name="Compromissos (a pagar)",line=dict(color="#D97706",width=1.5,dash="longdash"),mode="lines"))
    fig.update_layout(title="Projeção 12 meses com dados reais", height=300,
        margin=dict(t=40,b=0,l=0,r=0), plot_bgcolor="white", paper_bgcolor="white",
        legend=dict(orientation="h",y=-0.2),
        yaxis=dict(tickformat=",.0f",gridcolor="#F0EDE8"),
        xaxis=dict(gridcolor="#F0EDE8"))
    st.plotly_chart(fig, use_container_width=True)

    ca, cb = st.columns(2)
    with ca:
        if st.button("🤖 Projeção personalizada CFO IA", type="primary", use_container_width=True):
            with st.spinner("Projetando..."):
                resp = cfo("Com os dados reais, elabore projeção 12 meses com ações por trimestre.")
            st.markdown(f'<div class="insight">{resp.replace(chr(10),"<br>")}</div>', unsafe_allow_html=True)
    with cb:
        if st.button("🛡️ Riscos e mitigações", use_container_width=True):
            with st.spinner("Analisando riscos..."):
                resp = cfo("Liste os principais riscos financeiros reais dos próximos 6 meses com ações concretas de mitigação.")
            st.markdown(f'<div class="insight">{resp.replace(chr(10),"<br>")}</div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════
# NEGOCIAÇÃO
# ══════════════════════════════════════════════════════════
elif "Negociação" in page:
    st.markdown("## Negociação Estratégica")
    show_src()
    s    = st.session_state.stats
    inad = st.session_state.inad_df
    pc   = st.session_state.pag_classif

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**💰 Inadimplência — Potencial de recuperação**")
        if inad is not None and not inad.empty and "_val_ab" in inad.columns:
            tot = float(inad["_val_ab"].sum())
            st.metric("Total a recuperar", brl(tot), f"{s['n_inad']} clientes")
            st.metric("Recuperação 50%",   brl(tot*0.5), "meta conservadora")
            st.metric("Recuperação 80%",   brl(tot*0.8), "meta agressiva")
        else:
            st.info("Importe dados do Hubsoft para ver potencial real.")

        if st.button("🤖 Estratégia de cobrança IA", type="primary", use_container_width=True):
            with st.spinner("Gerando estratégia..."):
                resp = cfo("Com os dados reais dos inadimplentes, elabore estratégia segmentada por valor e tempo de atraso com script de abordagem e desconto sugerido por faixa.")
            st.markdown(f'<div class="insight">{resp.replace(chr(10),"<br>")}</div>', unsafe_allow_html=True)

    with col2:
        st.markdown("**⚠️ Top inadimplentes (dados reais)**")
        if inad is not None and not inad.empty:
            nc  = dcol(inad,"nome","razaosocial","cliente","name")
            for _,row in inad.head(6).iterrows():
                nm  = str(row[nc])[:30] if nc else "Cliente"
                val = brl(row["_val_ab"]) if "_val_ab" in row else "—"
                d   = int(row.get("_dias",0))
                cor = "#D93025" if d > 30 else "#D97706"
                st.markdown(f"""
                <div style='display:flex;align-items:center;gap:8px;background:#F6F4F1;
                  border-radius:8px;padding:8px 11px;margin-bottom:5px'>
                  <div style='width:7px;height:7px;border-radius:50%;background:{cor};flex-shrink:0'></div>
                  <div style='flex:1;font-size:12px;font-weight:600'>{nm}</div>
                  <div style='font-size:11px;color:#6E6E6E'>{d}d</div>
                  <div style='font-weight:700;color:{cor}'>{val}</div>
                </div>""", unsafe_allow_html=True)
        else:
            st.info("Sem inadimplentes nos dados importados.")

    # Contas a vencer — oportunidade de negociar prazo
    st.markdown("---")
    st.markdown("**📋 Contas a vencer — negociar prazo com fornecedores**")
    if pc is not None and not pc.empty and "_st_pag" in pc.columns:
        av = pc[pc["_st_pag"].isin(["a vencer","vence hoje"])].copy()
        if not av.empty:
            df_av = limpar(av).copy()
            if "_val"    in av.columns: df_av["Valor"]  = av["_val"].apply(brl)
            if "_st_pag" in av.columns: df_av["Status"] = av["_st_pag"]
            if "_dias_v" in av.columns: df_av["Dias"]   = av["_dias_v"].apply(lambda x: int(x) if x < 900 else "—")
            st.dataframe(df_av, use_container_width=True, height=200, hide_index=True)

            fn = dcol(av,"fornecedor","supplier","nome","beneficiario","empresa","name")
            if fn and st.button("🤖 Gerar propostas para fornecedores", type="primary"):
                forn = ", ".join(str(v) for v in av[fn].head(5).tolist())
                with st.spinner("Elaborando propostas..."):
                    resp = cfo(f"Elabore propostas de negociação de prazo para os fornecedores: {forn}. Para cada um, argumento principal e contra-proposta sugerida.")
                st.markdown(f'<div class="insight">{resp.replace(chr(10),"<br>")}</div>', unsafe_allow_html=True)
        else:
            st.success("✅ Nenhuma conta a vencer nos próximos 7 dias.")
    else:
        st.info("📥 Importe a planilha de contas a pagar para ver oportunidades.")


# ══════════════════════════════════════════════════════════
# CFO IA · MAXWELL
# ══════════════════════════════════════════════════════════
elif "CFO" in page:
    st.markdown("## Diretor CFO IA · Maxwell")
    s = st.session_state.stats

    st.markdown(f"""
    <div style='background:#fff;border-radius:10px;border:0.5px solid #E5E1DC;
      padding:13px 18px;display:flex;align-items:center;gap:12px;margin-bottom:12px'>
      <div style='width:44px;height:44px;border-radius:50%;background:#F05A22;
        display:flex;align-items:center;justify-content:center;font-size:22px;color:#fff'>🤖</div>
      <div>
        <div style='font-size:14px;font-weight:700'>Maxwell CFO · IA Estratégica</div>
        <div style='font-size:12px;color:#6E6E6E'>Dados em uso: {st.session_state.data_src}</div>
      </div>
      <div style='margin-left:auto;font-size:11px;color:#22A85A;font-weight:600'>● Online</div>
    </div>""", unsafe_allow_html=True)

    # Chips rápidos
    chips = st.columns(3)
    qs = [
        ("📊 Diagnóstico financeiro",   "Diagnóstico financeiro completo com dados reais."),
        ("💳 Priorizar pagamentos",      "Com os dados reais de contas a pagar, o que pagar primeiro e por quê?"),
        ("📉 Reduzir inadimplência",     "Estratégia para reduzir inadimplência com os dados reais."),
        ("💰 Melhorar fluxo de caixa",   "Como melhorar o fluxo de caixa com os dados importados?"),
        ("📈 Projeção de crescimento",   "Projete crescimento 6 meses com ações concretas baseadas em dados reais."),
        ("⚠️ Riscos principais",         "Quais os principais riscos nos dados reais importados?"),
    ]
    for i,(lbl,prm) in enumerate(qs):
        with chips[i%3]:
            if st.button(lbl, key=f"q{i}", use_container_width=True):
                st.session_state._pcfo = prm

    st.markdown("---")

    # Exibe histórico
    if not st.session_state.chat_history:
        tem = s["n_clientes"] > 0 or s["n_pag"] > 0
        intro = (
            "Olá! Sou o **Maxwell**, seu CFO IA do Grupo Jet. 👋<br><br>"
            + (f"📊 **Dados carregados:** {st.session_state.data_src}<br>"
               f"Analisando: **{s['n_clientes']} clientes**, faturamento **{brl(s['fat_total'])}**, "
               f"{s['n_inad']} inadimplentes, {s['n_pag']} contas a pagar.<br><br>"
               "Faça uma pergunta financeira!"
               if tem else
               "⚠️ **Nenhum dado importado ainda.** Vá em **Importar Planilhas** para carregar dados reais — "
               "assim todas as análises serão baseadas em números reais da empresa.")
        )
        st.markdown(f'<div class="chat-a"><div class="chat-lbl lbl-a">🤖 Maxwell CFO</div>{intro}</div>', unsafe_allow_html=True)

    for msg in st.session_state.chat_history:
        if msg["role"] == "user":
            # Mostra apenas a pergunta, sem o contexto
            txt = msg["content"].split("---")[0].replace("CONTEXTO FINANCEIRO REAL:","").strip()
            txt = txt.split("PERGUNTA:")[-1].strip() if "PERGUNTA:" in txt else txt
            st.markdown(f'<div style="text-align:right"><div class="chat-lbl lbl-u">Você</div><div class="chat-u">{txt}</div></div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="chat-a"><div class="chat-lbl lbl-a">🤖 Maxwell CFO</div>{msg["content"].replace(chr(10),"<br>")}</div>', unsafe_allow_html=True)

    # Input
    st.markdown("<br>", unsafe_allow_html=True)
    ci, cb = st.columns([5,1])
    with ci:
        user_txt = st.text_area("Mensagem", placeholder="Faça uma pergunta financeira...",
            height=68, label_visibility="collapsed", key="ci")
    with cb:
        st.markdown("<br>", unsafe_allow_html=True)
        send = st.button("Enviar ▶", type="primary", use_container_width=True)

    pending = st.session_state.pop("_pcfo", None)
    if pending:
        with st.spinner("Maxwell analisando dados reais..."):
            reply = cfo(pending)
            st.session_state.chat_history.append({"role":"user","content":pending})
            st.session_state.chat_history.append({"role":"assistant","content":reply})
        st.rerun()

    if send and user_txt.strip():
        with st.spinner("Maxwell analisando..."):
            reply = cfo(user_txt.strip())
            st.session_state.chat_history.append({"role":"user","content":user_txt.strip()})
            st.session_state.chat_history.append({"role":"assistant","content":reply})
        st.rerun()

    if st.session_state.chat_history:
        if st.button("🗑️ Limpar conversa"):
            st.session_state.chat_history = []
            st.rerun()
