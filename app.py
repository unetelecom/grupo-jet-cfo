"""
AGENDA DE CAIXA — GRUPO JET
Plataforma de gestão de fluxo de caixa dia a dia.
Baseada na planilha Agenda_DEFINITIVA_GrupoJet.xlsx
"""
import re, io, unicodedata
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import date, timedelta

# ── Anthropic (opcional — para análise IA) ──
try:
    import anthropic
    _HAS_AI = True
except ImportError:
    _HAS_AI = False

# ── Hubsoft API (opcional) ──
try:
    from hubsoft_api import HubsoftAPI
    _HAS_HUB = True
except ImportError:
    _HAS_HUB = False

# ══════════════════════════════════════════════════════════════════════
# CONFIGURAÇÃO
# ══════════════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="Agenda de Caixa — Grupo Jet",
    page_icon="📅",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ══════════════════════════════════════════════════════════════════════
# ESTILOS
# ══════════════════════════════════════════════════════════════════════
st.markdown("""
<style>
/* Fundo geral */
.stApp { background:#0E0E0E; color:#F5F5F5; }
/* Sidebar */
[data-testid="stSidebar"] { background:#111; border-right:1px solid #222; }
/* Cards de métricas */
[data-testid="stMetric"] { background:#1A1A1A; border-radius:10px; padding:12px 16px; }
[data-testid="stMetricLabel"] { font-size:11px !important; color:#AAA !important; }
[data-testid="stMetricValue"] { font-size:20px !important; font-weight:700 !important; }
/* Tabela */
[data-testid="stDataFrame"] { border-radius:8px; overflow:hidden; }
/* Separador */
hr { border-color:#2A2A2A !important; margin:12px 0 !important; }
/* Cabeçalho de dia */
.dia-header {
    background:linear-gradient(90deg,#1E1E1E,#181818);
    border-left:4px solid #F05A22;
    border-radius:0 8px 8px 0;
    padding:10px 16px;
    margin:16px 0 4px 0;
}
.dia-header-fds {
    background:#161616;
    border-left:4px solid #444;
    border-radius:0 8px 8px 0;
    padding:10px 16px;
    margin:16px 0 4px 0;
}
/* Badge de criticidade */
.badge { display:inline-block; padding:2px 8px; border-radius:12px; font-size:11px; font-weight:700; margin:1px; }
.badge-crit  { background:#3D0B0B; color:#FF4444; }
.badge-alta  { background:#3D2000; color:#FF9800; }
.badge-media { background:#2D2A00; color:#FFD600; }
.badge-baixa { background:#0D2A0D; color:#4CAF50; }
/* Saldo colorido */
.saldo-ok   { color:#4CAF50; font-weight:700; }
.saldo-warn { color:#FF9800; font-weight:700; }
.saldo-crit { color:#FF4444; font-weight:700; }
/* Insight box */
.insight {
    background:#1A1A1A; border-left:4px solid #F05A22;
    border-radius:4px 8px 8px 4px;
    padding:14px 18px; margin:12px 0;
    font-size:13px; line-height:1.7;
}
</style>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════
DIAS_PT = {0:"Segunda",1:"Terça",2:"Quarta",3:"Quinta",4:"Sexta",5:"Sábado",6:"Domingo"}
DIAS_ABR = {0:"Seg",1:"Ter",2:"Qua",3:"Qui",4:"Sex",5:"Sáb",6:"Dom"}

def brl(v: float) -> str:
    """Formata valor em R$ brasileiro."""
    try:
        n = abs(float(v))
        s = f"{n:,.2f}".replace(".", "X").replace(",", ".").replace("X", ",")
        return f"R$ {s}"
    except:
        return "R$ —"

def pv(v) -> float:
    """Parse de valor monetário — aceita US, BR e floats do Excel."""
    if v is None: return 0.0
    if isinstance(v, (int, float)):
        f = float(v)
        return 0.0 if f != f else abs(f)  # NaN check
    s = str(v).strip().replace("R$","").replace("$","").replace("\xa0","").replace(" ","")
    if s in ("","-","nan","None","null","—","n/d","nd"): return 0.0
    # 1ª tentativa: float direto — cobre "396564.88000000024", inteiros, US
    try:
        return abs(float(s))
    except:
        pass
    # 2ª tentativa: formato BR com vírgula decimal
    try:
        hd = "." in s; hc = "," in s
        if hd and hc:
            # Decide separador decimal pelo último separador
            s2 = s.replace(".","").replace(",",".") if s.rfind(",")>s.rfind(".") else s.replace(",","")
            return abs(float(s2))
        elif hc and not hd:
            p = s.split(",")
            s2 = s.replace(",",".") if len(p)==2 and len(p[1])<=2 else s.replace(",","")
            return abs(float(s2))
        return 0.0
    except:
        return 0.0


def parse_date(series: pd.Series) -> pd.Series:
    """
    Parser robusto de datas — aceita todos os formatos:
    - ISO: '2026-05-10' ou '2026-05-10 00:00:00'  (Excel com hora)
    - BR:  '10/05/2026' ou '10-05-2026'            (formato brasileiro)
    """
    # 1ª tentativa: ISO/automático (funciona para datas do Excel)
    result = pd.to_datetime(series, errors='coerce')
    # 2ª tentativa: formato BR para os que falharam
    mask = result.isna() & series.fillna('').astype(str).str.strip().ne('')
    if mask.any():
        result[mask] = pd.to_datetime(series[mask], dayfirst=True, errors='coerce')
    return result.dt.normalize()


def norm_col(s: str) -> str:
    """Normaliza nome de coluna para matching."""
    s = unicodedata.normalize("NFKD", str(s).lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    for ch in (" ","_","-","/",".","`","'",'"',"(",")"): s = s.replace(ch,"")
    return s

def dcol(df: pd.DataFrame, *terms) -> str | None:
    """Detecta coluna por termos (exact → substring → 72% match)."""
    cols = {norm_col(c): c for c in df.columns}
    for t in terms:
        nt = norm_col(t)
        for nc, orig in cols.items():
            if nc == nt: return orig
        for nc, orig in cols.items():
            if nt in nc: return orig
        for nc, orig in cols.items():
            if nc in nt and len(nc) >= max(5, int(len(nt)*0.72)): return orig
    return None

def cor_saldo(v: float) -> str:
    if v < 0:      return "🚨 NEGATIVO"
    if v < 500:    return "🔴 CRÍTICO"
    if v < 2000:   return "🟠 APERTADO"
    if v < 10000:  return "🟡 OK"
    return "✅ Saudável"

# ══════════════════════════════════════════════════════════════════════
# CRITICIDADE POR CATEGORIA
# ══════════════════════════════════════════════════════════════════════
CRITICIDADE = {
    # 🔴 CRÍTICO — prio 0
    "energia elétrica":             (0, "🔴 CRÍTICO", "Risco CORTE energia"),
    "energia eletrica":             (0, "🔴 CRÍTICO", "Risco CORTE energia"),
    "salários":                     (0, "🔴 CRÍTICO", "Compromisso trabalhista"),
    "salarios":                     (0, "🔴 CRÍTICO", "Compromisso trabalhista"),
    "folha pj":                     (0, "🔴 CRÍTICO", "Compromisso trabalhista"),
    "pgfn":                         (0, "🔴 CRÍTICO", "Risco fiscal / multa"),
    "pagamento de empréstimos":     (0, "🔴 CRÍTICO", "Risco contratual"),
    "pagamento de emprestimos":     (0, "🔴 CRÍTICO", "Risco contratual"),
    "simples nacional":             (0, "🔴 CRÍTICO", "Obrigação fiscal"),
    "inss":                         (0, "🔴 CRÍTICO", "Obrigação trabalhista"),
    "fgts":                         (0, "🔴 CRÍTICO", "Obrigação trabalhista"),
    "irrf":                         (0, "🔴 CRÍTICO", "Obrigação fiscal"),

    # 🟠 ALTA — prio 1
    "aluguel - imóveis":            (1, "🟠 ALTA", "Risco despejo"),
    "aluguel - imoveis":            (1, "🟠 ALTA", "Risco despejo"),
    "aluguel-imóveis":              (1, "🟠 ALTA", "Risco despejo"),
    "aluguel-imoveis":              (1, "🟠 ALTA", "Risco despejo"),
    "aluguel de veículos":          (1, "🟠 ALTA", "Operacional"),
    "aluguel de veiculos":          (1, "🟠 ALTA", "Operacional"),
    "serviços de links/ ip`s":      (1, "🟠 ALTA", "Core do negócio"),
    "servicos de links/ ip`s":      (1, "🟠 ALTA", "Core do negócio"),
    "links":                        (1, "🟠 ALTA", "Core do negócio"),
    "compras de mercadorias para redes": (1, "🟠 ALTA", "Operacional"),
    "serviços de instalação tomados":(1, "🟠 ALTA", "Operacional"),
    "servicos de instalacao tomados":(1, "🟠 ALTA", "Operacional"),
    "advogados/assessoria":         (1, "🟠 ALTA", "Risco jurídico"),
    "negociação":                   (1, "🟠 ALTA", "Acordo firmado"),
    "negociacao":                   (1, "🟠 ALTA", "Acordo firmado"),
    "sistema operacional":          (1, "🟠 ALTA", "Operacional"),
    "manutenção de equipamentos":   (1, "🟠 ALTA", "Operacional"),
    "manutencao de equipamentos":   (1, "🟠 ALTA", "Operacional"),
    "reembolso":                    (1, "🟠 ALTA", "Obrigação contratual"),

    # 🟡 MÉDIA — prio 2
    "compras de mercadorias Para Redes": (2, "🟡 MÉDIA", "Impacta entregas"),
    "compra de material aplicado":  (2, "🟡 MÉDIA", "Impacta entregas"),
    "compras de mercadorias para instalação": (2, "🟡 MÉDIA", "Impacta entregas"),
    "compras de mercadorias para instalacao": (2, "🟡 MÉDIA", "Impacta entregas"),
    "telefonia":                    (2, "🟡 MÉDIA", "Serviços operacionais"),
    "contabilidade":                (2, "🟡 MÉDIA", "Regularidade fiscal"),
    "assistência médica":           (2, "🟡 MÉDIA", "Benefício equipe"),
    "assistencia medica":           (2, "🟡 MÉDIA", "Benefício equipe"),
    "água e esgoto":                (2, "🟡 MÉDIA", "Risco corte"),
    "agua e esgoto":                (2, "🟡 MÉDIA", "Risco corte"),
    "epi":                          (2, "🟡 MÉDIA", "Segurança trabalho"),
    "uniformes":                    (2, "🟡 MÉDIA", "Operacional regular"),

    # 🟢 BAIXA — prio 3
    "material de escritório":       (3, "🟢 BAIXA", "Pode adiar"),
    "material de escritorio":       (3, "🟢 BAIXA", "Pode adiar"),
    "móveis e utensílios":          (3, "🟢 BAIXA", "Pode adiar"),
    "moveis e utensilios":          (3, "🟢 BAIXA", "Pode adiar"),
    "retiradas sócios":             (3, "🟢 BAIXA", "Pode adiar"),
    "retiradas socios":             (3, "🟢 BAIXA", "Pode adiar"),
    "limpeza":                      (3, "🟢 BAIXA", "Pode adiar"),
    "serviços de instalação":       (3, "🟢 BAIXA", "Pode adiar"),
    "servicos de instalacao":       (3, "🟢 BAIXA", "Pode adiar"),
    "consultoria":                  (3, "🟢 BAIXA", "Pode adiar"),
    "outras despesas":              (3, "🟢 BAIXA", "Avaliar"),
    "benefícios":                   (1, "🟠 ALTA",  "Benefício equipe"),
    "beneficios":                   (1, "🟠 ALTA",  "Benefício equipe"),
    "caju":                         (1, "🟠 ALTA",  "Cartão benefício"),
    "vale refeição":                (1, "🟠 ALTA",  "Benefício equipe"),
    "vale refeicao":                (1, "🟠 ALTA",  "Benefício equipe"),
    "vale transporte":              (1, "🟠 ALTA",  "Benefício equipe"),
    "plano de saúde":               (1, "🟠 ALTA",  "Benefício equipe"),
    "plano de saude":               (1, "🟠 ALTA",  "Benefício equipe"),
}

def get_crit(categoria: str):
    """Retorna (prio, emoji, motivo) para uma categoria."""
    k = str(categoria).strip().lower()
    if k in CRITICIDADE:
        return CRITICIDADE[k]
    # Substring match
    for key, val in CRITICIDADE.items():
        if key in k or k in key:
            return val
    return (2, "🟡 MÉDIA", "Avaliar prioridade")

# ══════════════════════════════════════════════════════════════════════
# PARSE DE PLANILHAS
# ══════════════════════════════════════════════════════════════════════
def parse_pagar(uploaded) -> pd.DataFrame:
    """Lê planilha de Contas a Pagar — aceita xlsx/xls/csv."""
    try:
        if uploaded.name.lower().endswith(".csv"):
            for enc in ["utf-8","latin-1","cp1252"]:
                try: df = pd.read_csv(uploaded, dtype=str, encoding=enc); break
                except: uploaded.seek(0)
        else:
            df = pd.read_excel(uploaded, dtype=str)
    except Exception as e:
        st.error(f"Erro ao ler planilha: {e}")
        return pd.DataFrame()

    if df.empty: return df

    VAZIOS = {"","—","-","nan","none","null","n/a"}
    col_forn  = dcol(df,"razao_social","razaosocial","fornecedor","nome","razão social")
    col_cat   = dcol(df,"categoria","category","tipo")
    col_vpago = dcol(df,"valor_pago","valorpago","pago")
    col_ap_raw= dcol(df,"a_pagar","apagar","saldo","pendente")

    # ── CASO ESPECIAL: linhas onde Razão Social está vazia mas
    #    "Valor Pago" contém o nome (ex: CAJU) e "A Pagar" tem um valor real.
    #    Padrão Hubsoft: benefícios, cartões, linhas fora do padrão.
    linhas_especiais = []
    if col_forn and col_vpago and col_ap_raw:
        sem_razao = df[col_forn].fillna("").astype(str).str.strip().str.len() < 2
        vpago_texto = df[col_vpago].fillna("").astype(str).str.strip()
        apagar_val  = df[col_ap_raw].apply(pv)

        mask_especial = (
            sem_razao &
            (vpago_texto.str.len() >= 2) &
            (~vpago_texto.str.lower().isin(VAZIOS)) &
            # Exclui totalizadores: "TOTAL MAIO", "TOTAL", números puros
            (~vpago_texto.str.upper().str.startswith("TOTAL")) &
            (vpago_texto.str.contains("[A-Za-záàãâéêíóôõúüçÁÀÃÂÉÊÍÓÔÕÚÜÇ]", regex=True, na=False)) &
            (apagar_val > 0)
        )

        if mask_especial.any():
            especiais = df[mask_especial].copy()
            # Usa o texto de "Valor Pago" como Razão Social
            especiais[col_forn] = especiais[col_vpago].astype(str).str.strip()
            # Categoria padrão se vazia
            if col_cat:
                especiais[col_cat] = especiais[col_cat].fillna("").astype(str).apply(
                    lambda c: "Benefícios" if c.strip() in ("", "nan") else c
                )
            linhas_especiais.append(especiais)

    # Remove totalizadores e linhas inválidas
    if col_forn:
        df = df[~df[col_forn].fillna("").astype(str).str.strip().str.lower().isin(VAZIOS)]
        df = df[df[col_forn].fillna("").astype(str).str.strip().str.len() >= 2]
    if col_cat:
        df = df[~df[col_cat].fillna("").astype(str).str.strip().str.lower().isin(VAZIOS)]

    # Adiciona linhas especiais (CAJU e similares) ao final
    if linhas_especiais:
        df = pd.concat([df] + linhas_especiais, ignore_index=True)

    # Detecta colunas
    col_vliq   = dcol(df,"valor_liquido","valorliquido","liquido","valor da conta","valor")
    col_vpago  = dcol(df,"valor_pago","valorpago","pago")
    col_apagar = dcol(df,"a_pagar","apagar","saldo","pendente")
    col_venc   = dcol(df,"vencimento","data_vencimento","datavencimento","vencim")
    col_crit   = dcol(df,"criticidade","prioridade","priority")
    col_status = dcol(df,"status","situacao")

    df["__forn"]   = df[col_forn].fillna("").astype(str).str.strip() if col_forn else "Sem nome"
    df["__cat"]    = df[col_cat].fillna("Outros").astype(str).str.strip() if col_cat else "Outros"
    df["__vliq"]   = df[col_vliq].apply(pv) if col_vliq else 0.0
    df["__vpago"]  = df[col_vpago].apply(pv) if col_vpago else 0.0
    df["__venc"]   = parse_date(df[col_venc]) if col_venc else pd.NaT
    df["__status_orig"] = df[col_status].fillna("").astype(str) if col_status else ""

    # A Pagar: usa coluna específica ou calcula
    if col_apagar:
        df["__apagar"] = df[col_apagar].apply(pv)
        # Trata linha CAJU (texto onde deveria ser valor)
        mask_caju = (df["__apagar"] == 0) & (df["__vliq"] > 0)
        df.loc[mask_caju, "__apagar"] = df.loc[mask_caju, "__vliq"]
    else:
        df["__apagar"] = (df["__vliq"] - df["__vpago"]).clip(lower=0)

    hoje = pd.Timestamp.now().normalize()
    df["__status_venc"] = df["__venc"].apply(
        lambda d: "ATRASADO" if pd.notna(d) and d < hoje else "A VENCER")
    df["__dias_atr"] = (hoje - df["__venc"]).dt.days.fillna(0).clip(lower=0).astype(int)
    df["__venc_str"] = df["__venc"].apply(lambda d: d.strftime("%d/%m") if pd.notna(d) else "—")

    # Criticidade — usa coluna existente ou auto-atribui
    if col_crit:
        df["__crit_orig"] = df[col_crit].fillna("").astype(str)
        df["__prio"]  = df["__crit_orig"].apply(lambda c: 0 if "CRÍTICO" in c.upper() else
                                                            1 if "ALTA" in c.upper() else
                                                            2 if "MÉDIA" in c.upper() or "MEDIA" in c.upper() else 3)
        df["__crit"]  = df["__crit_orig"]
        df["__motivo"]= df["__cat"].apply(lambda c: get_crit(c)[2])
    else:
        crit_info     = df["__cat"].apply(get_crit)
        df["__prio"]  = crit_info.apply(lambda x: x[0])
        df["__crit"]  = crit_info.apply(lambda x: x[1])
        df["__motivo"]= crit_info.apply(lambda x: x[2])

    return df[df["__apagar"] > 0].copy()


def parse_receber(uploaded) -> pd.DataFrame:
    """Lê planilha de Faturamento/Recebimentos Hubsoft."""
    try:
        if uploaded.name.lower().endswith(".csv"):
            for enc in ["utf-8","latin-1","cp1252"]:
                try: df = pd.read_csv(uploaded, dtype=str, encoding=enc); break
                except: uploaded.seek(0)
        else:
            df = pd.read_excel(uploaded, dtype=str)
    except Exception as e:
        st.error(f"Erro ao ler planilha: {e}"); return pd.DataFrame()

    if df.empty: return df
    df = df[df.iloc[:,0].fillna("").astype(str).str.strip().str.len() >= 2].copy()

    col_nome  = dcol(df,"nome","razaosocial","nome_razaosocial","cliente","name")
    col_val   = dcol(df,"valor","value","mensalidade","amount")
    col_venc  = dcol(df,"data_vencimento","datavencimento","vencimento","duedate")
    col_st    = dcol(df,"status","situacao")

    if not col_val or not col_venc:
        st.warning("Planilha de recebimentos: colunas 'valor' e 'data_vencimento' não encontradas.")
        return pd.DataFrame()

    STATUS_PAGO = {"baixado_banco","baixado_pix","baixado_manual","baixado_parcial",
                   "baixado_faturamento","baixado_cheque","pago","recebido","quitado"}

    df["__nome"] = df[col_nome].fillna("Cliente").astype(str).str.strip() if col_nome else "Cliente"
    df["__val"]  = df[col_val].apply(pv)
    df["__venc"] = parse_date(df[col_venc])
    df["__st"]   = df[col_st].fillna("").astype(str).str.lower().str.strip() if col_st else "faturado"
    df["__pago"] = df["__st"].isin(STATUS_PAGO)

    result = df[(df["__val"] > 0) & df["__venc"].notna()].copy()
    # __nome_c = nome limpo para agrupamento por cliente
    result["__nome_c"] = result["__nome"]
    return result


# ══════════════════════════════════════════════════════════════════════
# PARSER — CONTAS JÁ RECEBIDAS (extrato OFX ou planilha manual)
# ══════════════════════════════════════════════════════════════════════
def parse_recebidos(uploaded) -> pd.DataFrame:
    """
    Lê planilha/extrato com valores já efetivamente recebidos.
    Aceita:
      - Planilha xlsx/csv com colunas: cliente/pagante, valor, data
      - Arquivo OFX (extrato bancário)
    Retorna DataFrame com __pagante, __val, __data, __memo
    """
    import re as _re

    name = uploaded.name.lower()

    # ── OFX: extrato bancário ──
    if name.endswith(".ofx") or name.endswith(".txt"):
        raw = ""
        for enc in ["latin-1","cp1252","utf-8"]:
            try:
                uploaded.seek(0)
                raw = uploaded.read().decode(enc)
                break
            except: pass
        if not raw: return pd.DataFrame()

        trns = _re.findall(r"<STMTTRN>(.*?)</STMTTRN>", raw, _re.DOTALL | _re.IGNORECASE)
        rows = []
        for trn in trns:
            def g(t):
                pat = "<" + t + ">" + r"\s*(.*?)(?:\n|<|$)"
                m = _re.search(pat, trn, _re.IGNORECASE)
                return m.group(1).strip() if m else ""
            try:
                val = float(g("TRNAMT").replace(",","."))
                if val <= 0: continue          # só entradas (créditos)
                dt  = g("DTPOSTED")[:8]
                mem = g("MEMO").strip()[:80]
                data_str = f"{dt[6:8]}/{dt[4:6]}/{dt[:4]}" if len(dt)>=8 else ""
                # Ignora intercompany (RDMI, RRD, etc.)
                INTERCOMPANY = ["RDMI","RRD TELECOM","GRUPO JET","JET TELECOM"]
                if any(ic.upper() in mem.upper() for ic in INTERCOMPANY):
                    continue
                rows.append({
                    "__pagante": mem,
                    "__val":     abs(val),
                    "__data":    pd.to_datetime(data_str, dayfirst=True, errors="coerce"),
                    "__memo":    mem,
                })
            except: pass
        return pd.DataFrame(rows) if rows else pd.DataFrame()

    # ── XLSX / CSV: planilha manual ──
    try:
        if name.endswith(".csv"):
            df = None
            for enc in ["utf-8","latin-1","cp1252"]:
                try: df = pd.read_csv(uploaded, dtype=str, encoding=enc); break
                except: uploaded.seek(0)
            if df is None: return pd.DataFrame()
        else:
            # Tenta header=0; se colunas forem "Unnamed", pula a linha de título (header=1)
            df = pd.read_excel(uploaded, dtype=str)
            unnamed = sum(1 for c in df.columns if "Unnamed" in str(c) or str(c).strip() == "")
            if unnamed >= len(df.columns) // 2:
                uploaded.seek(0)
                df = pd.read_excel(uploaded, header=1, dtype=str)
            # Remove linhas completamente vazias
            df = df.dropna(how="all").reset_index(drop=True)
            # Remove linha totalizadora do Hubsoft (última linha sem data/cliente)
            # O Hubsoft adiciona uma linha de TOTAL no final: só tem valor, resto é NaN
            col_first = df.columns[0]  # Minha Empresa
            col_sec   = df.columns[1]  # Data de Crédito
            mask_total = (
                df[col_first].isna() | df[col_first].astype(str).str.strip().isin(["","nan"])
            ) & (
                df[col_sec].isna()   | df[col_sec].astype(str).str.strip().isin(["","nan"])
            )
            if mask_total.any():
                df = df[~mask_total].reset_index(drop=True)
    except Exception as e:
        st.error(f"Erro ao ler arquivo: {e}"); return pd.DataFrame()

    if df.empty: return pd.DataFrame()

    # Detecta colunas — inclui variações do Hubsoft financeiro
    col_pag  = dcol(df,"razao_social","razaosocial","pagante","cliente","nome",
                    "pagador","payer","description","memo","descricao")
    col_val  = dcol(df,"recebido","valor_recebido","valorrecebido","valor","value",
                    "amount","credito","entrada","valor_da_conta")
    col_data = dcol(df,"data_credito","datacredito","data_de_credito",
                    "data","date","data_pagamento","datapagamento","vencimento")

    if not col_val:
        st.warning(f"Coluna de valor não encontrada. Colunas disponíveis: {list(df.columns)}")
        return pd.DataFrame()

    # Razão Social "N/D" → substitui por "Não Identificado"
    if col_pag:
        df[col_pag] = df[col_pag].fillna("").astype(str).str.strip()
        df.loc[df[col_pag].str.upper().isin(["N/D","ND","N.D","N.D.","","NAN"]), col_pag] = "Não identificado"

    df["__pagante"] = df[col_pag].astype(str).str.strip() if col_pag else "Não identificado"
    df["__val"]     = df[col_val].apply(pv)
    df["__data"]    = parse_date(df[col_data]) if col_data else pd.NaT
    df["__memo"]    = df["__pagante"]

    return df[df["__val"] > 0].copy()


# ══════════════════════════════════════════════════════════════════════
# CRUZAMENTO CLIENTE A CLIENTE: Faturamento × OFX
# ══════════════════════════════════════════════════════════════════════
def cruzar_clientes(rec_df: pd.DataFrame, rec_df_recebidos: pd.DataFrame) -> dict:
    """
    Cruza faturamento (Hubsoft) com pagamentos recebidos (OFX/extrato).
    Para cada cobrança classifica: recebido / atrasado / a_vencer.
    Agrupa por cliente.
    """
    import unicodedata as _uc, re as _re2

    if rec_df.empty or "__val" not in rec_df.columns:
        return {"cli": pd.DataFrame(), "rec_aug": pd.DataFrame(),
                "ofx_casado": 0.0, "ofx_nc": 0.0, "n_matches": 0}

    today = pd.Timestamp.now().normalize()
    rec = rec_df.copy().reset_index(drop=True)

    def _norm(s):
        s = _uc.normalize("NFKD", str(s).upper())
        s = "".join(c for c in s if not _uc.combining(c))
        for t in ["LTDA","S.A","S/A","ME","EIRELI","SA","SS","EPP","DE","DA","DO","DOS","DAS","E"]:
            s = _re2.sub(rf"\b{t}\b", "", s)
        return _re2.sub(r"\s+", " ", s).strip()
    def _pw(s): return {w for w in _norm(s).split() if len(w) > 3}

    # ── Sem OFX: classifica só por data de vencimento ────────────────
    if rec_df_recebidos.empty:
        rec["_cat"]     = "a_vencer"
        rec.loc[rec["__venc"] < today, "_cat"] = "atrasado"
        rec["_val_rec"] = 0.0
        cli = _agrupa_clientes(rec, today)
        return {"cli": cli, "rec_aug": rec, "ofx_casado": 0.0,
                "ofx_nc": 0.0, "n_matches": 0}

    # ── Com OFX: concilia cobrança a cobrança ────────────────────────
    ofx = rec_df_recebidos.copy().reset_index(drop=True)
    hub_vc = rec["__val"].round(2).value_counts().to_dict()

    cands = []
    for io, o in ofx.iterrows():
        vo = float(o["__val"]); memo = str(o.get("__memo",""))
        do = pd.Timestamp(o["__data"]) if pd.notna(o.get("__data")) else today
        mu = memo.upper()
        if mu.startswith("PIX RECEBIDO DE"):   tipo="PIX";    pag=mu.replace("PIX RECEBIDO DE","").split("|")[0].strip()
        elif mu.startswith("TED RECEBIDA DE"): tipo="TED";    pag=mu.replace("TED RECEBIDA DE","").split("|")[0].strip()
        elif mu.startswith("BOLETO PAGO POR"): tipo="BOLETO"; pag=mu.replace("BOLETO PAGO POR","").strip()
        else:                                  tipo="OUTRO";  pag=memo
        pag_pw = _pw(pag)
        for ih, h in rec.iterrows():
            vh = float(h["__val"])
            if abs(vo - vh) / max(vh, 0.01) > 0.012: continue
            dd = 999
            if pd.notna(h["__venc"]):
                try: dd = abs(int((do - pd.Timestamp(h["__venc"])).total_seconds() / 86400))
                except: pass
            if dd > 30: continue
            n_same = hub_vc.get(round(vh, 2), 1)
            unico = (n_same == 1); raro = (n_same <= 2)
            cli_pw = _pw(str(h.get("__nome", h.iloc[0]))); nm = len(cli_pw & pag_pw)
            if tipo in ("PIX","TED") and nm == 0 and not unico: continue
            if tipo == "BOLETO" and not unico and nm == 0 and dd > 5: continue
            sc  = (50 if abs(vo-vh)/max(vh,0.01) < 0.001 else 30)
            sc += (30 if dd<=2 else 20 if dd<=5 else 10 if dd<=10 else 4)
            sc += min(nm*20, 40); sc += (15 if unico else 5 if raro else 0)
            cands.append({"io":io,"ih":ih,"sc":sc,"val_hub":vh,"val_ofx":vo,
                          "data":do,"venc":h["__venc"],"tipo":tipo,"pag":pag[:50],
                          "nome":str(h.get("__nome",h.iloc[0]))})

    cdf = pd.DataFrame(cands).sort_values("sc", ascending=False) if cands else pd.DataFrame()
    uo = set(); uh = set(); ml = []
    if not cdf.empty:
        for _, c in cdf.iterrows():
            if c["io"] not in uo and c["ih"] not in uh:
                uo.add(c["io"]); uh.add(c["ih"]); ml.append(c)
    mdf    = pd.DataFrame(ml) if ml else pd.DataFrame()
    mid    = set(mdf["ih"].tolist()) if not mdf.empty else set()
    ofx_c  = float(mdf["val_hub"].sum()) if not mdf.empty else 0.0
    ofx_nc = float(ofx[~ofx.index.isin(uo)]["__val"].sum()) if not ofx.empty else 0.0

    rec["_cat"]     = "a_vencer"
    rec.loc[rec.index.isin(mid), "_cat"] = "recebido"
    rec.loc[(~rec.index.isin(mid)) & (rec["__venc"] < today), "_cat"] = "atrasado"
    rec["_val_rec"] = rec.apply(lambda r: r["__val"] if r.name in mid else 0.0, axis=1)

    # Nome do cliente
    nome_col = "__nome" if "__nome" in rec.columns else rec.columns[1]
    rec["__nome_c"] = rec[nome_col].fillna("").astype(str).str.strip()

    cli = _agrupa_clientes(rec, today)
    return {"cli": cli, "rec_aug": rec, "mdf": mdf,
            "ofx_casado": ofx_c, "ofx_nc": ofx_nc, "n_matches": len(mdf)}


def _agrupa_clientes(rec: pd.DataFrame, today) -> pd.DataFrame:
    nome_col = "__nome_c" if "__nome_c" in rec.columns else (
               "__nome" if "__nome" in rec.columns else rec.columns[1])
    g = rec.groupby(nome_col)
    cli = g.agg(
        faturado = ("__val",   "sum"),
        recebido = ("_val_rec","sum"),
        atrasado = ("__val",   lambda x: x[rec.loc[x.index,"_cat"]=="atrasado"].sum()),
        a_vencer = ("__val",   lambda x: x[rec.loc[x.index,"_cat"]=="a_vencer"].sum()),
        n_cob    = ("__val",   "count"),
        n_rec    = ("_cat",    lambda x: (x=="recebido").sum()),
        n_atr    = ("_cat",    lambda x: (x=="atrasado").sum()),
        n_av     = ("_cat",    lambda x: (x=="a_vencer").sum()),
    ).reset_index().rename(columns={nome_col:"cliente"})
    return cli.sort_values("faturado", ascending=False)


# ══════════════════════════════════════════════════════════════════════
# INTELIGÊNCIA FINANCEIRA — AGENDAMENTO INTELIGENTE
# ══════════════════════════════════════════════════════════════════════
def agendar_inteligente(pag_df: pd.DataFrame, rec_df: pd.DataFrame,
                        rec_recebidos: pd.DataFrame,
                        caixa_inicial: float, data_ini: pd.Timestamp,
                        dias_horizonte: int,
                        perc_inadimplencia: float = 0.30,
                        usar_recebidos: bool = True) -> dict:
    """
    Agendamento inteligente de pagamentos.
    Diferente do algoritmo simples, este:
    1. Projeta o caixa para todo o horizonte antes de agendar
    2. Agrupa pagamentos por dia para reduzir transações
    3. Adia pagamentos BAIXA/MÉDIA se o caixa estiver apertado
    4. Antecipa pagamentos CRÍTICO quando há folga de caixa
    5. Sugere o melhor dia para cada conta
    6. Classifica o risco de cada conta não coberta
    """
    data_fim = data_ini + pd.Timedelta(days=dias_horizonte - 1)
    hoje     = pd.Timestamp.now().normalize()

    # ── Entradas já confirmadas (recebidos reais) ──
    entradas_confirmadas = {}
    if usar_recebidos and not rec_recebidos.empty and "__val" in rec_recebidos.columns:
        for _, r in rec_recebidos.iterrows():
            d = pd.Timestamp(r["__data"]).normalize() if pd.notna(r.get("__data")) else data_ini
            if d >= data_ini:
                entradas_confirmadas[d] = entradas_confirmadas.get(d, 0.0) + float(r["__val"])

    # ── Entradas projetadas do faturamento (com desconto de inadimplência) ──
    entradas_projetadas = {}
    n_proj_dia = {}
    if not rec_df.empty and "__val" in rec_df.columns and "__venc" in rec_df.columns:
        STATUS_PAGO_REC = {"baixado_banco","baixado_pix","baixado_manual","pago","recebido"}
        rec_pend = rec_df
        if "__pago" in rec_df.columns:
            rec_pend = rec_df[~rec_df["__pago"]]
        for _, r in rec_pend.iterrows():
            if not pd.notna(r["__venc"]): continue
            d = r["__venc"].normalize()
            if d > data_fim: continue
            # Cobranças vencidas antes do período: projeta para o primeiro dia
            d_efetivo = d if d >= data_ini else data_ini
            # Desconta inadimplência esperada
            fator = (1.0 - perc_inadimplencia)
            val_proj = float(r["__val"]) * fator
            entradas_projetadas[d_efetivo] = entradas_projetadas.get(d_efetivo, 0.0) + val_proj
            n_proj_dia[d_efetivo] = n_proj_dia.get(d_efetivo, 0) + 1

    # ── Combine: confirmadas têm prioridade ──
    entradas_totais = {}
    for d in set(list(entradas_confirmadas.keys()) + list(entradas_projetadas.keys())):
        # Se há confirmado, usa confirmado; senão usa projetado
        conf = entradas_confirmadas.get(d, 0.0)
        proj = entradas_projetadas.get(d, 0.0)
        entradas_totais[d] = conf if conf > 0 else proj

    # ── Projeta saldo diário futuro (look-ahead) ──
    saldo_projetado = {}
    saldo_tmp = float(caixa_inicial)
    d = data_ini
    while d <= data_fim:
        saldo_tmp += entradas_totais.get(d.normalize(), 0.0)
        saldo_projetado[d.normalize()] = saldo_tmp
        d += pd.Timedelta(days=1)

    # ── Prepara contas pendentes ──
    VAZIOS2 = {"","—","-","nan","none","null"}
    pend = pag_df[
        pag_df["__venc"].isna() | (pag_df["__venc"] <= data_fim)
    ].copy()
    pend = pend[pend["__apagar"] > 0]
    pend = pend[~pend["__forn"].str.strip().str.lower().isin(VAZIOS2)]

    # ── Agendamento inteligente ──
    # Para cada conta, determina o MELHOR dia para pagar:
    # - CRÍTICO: pagar no vencimento (ou antes se já atrasado)
    # - ALTA:    pagar no vencimento se houver saldo, senão +3 dias
    # - MÉDIA:   pagar no vencimento se saldo ok, senão +7 dias
    # - BAIXA:   pagar quando houver folga de caixa (até +15 dias)
    TOLERANCIA = {0: 0, 1: 3, 2: 7, 3: 15}  # dias de tolerância por prio
    MARGEM_SEG = {0: 500, 1: 200, 2: 100, 3: 0}  # margem mínima pós-pagamento

    agendamento = []
    nao_cobertos_intel = []

    # Ordena: CRÍTICO primeiro, depois por vencimento, depois por valor desc
    pend_sorted = pend.sort_values(
        ["__prio", "__venc", "__apagar"],
        ascending=[True, True, False],
        na_position="last"
    )

    saldo_diario = {d: float(caixa_inicial) for d in
                    [data_ini + pd.Timedelta(days=i) for i in range(dias_horizonte)]}

    # Carrega entradas no saldo diário
    for d_key, val in entradas_totais.items():
        if d_key in saldo_diario:
            saldo_diario[d_key] += val
    # Acumula (saldo diário = saldo_anterior + entrada_dia)
    dias_ord = sorted(saldo_diario.keys())
    for i in range(1, len(dias_ord)):
        saldo_diario[dias_ord[i]] += saldo_diario[dias_ord[i-1]] - entradas_totais.get(dias_ord[i], 0.0)
    # Recalcula saldo acumulado corretamente
    saldo_simples = float(caixa_inicial)
    saldo_dia_acum = {}
    for d_k in dias_ord:
        saldo_simples += entradas_totais.get(d_k, 0.0)
        saldo_dia_acum[d_k] = saldo_simples

    # Desconta pagamentos agendados do saldo projetado
    saldo_ag = dict(saldo_dia_acum)  # cópia do saldo livre

    for _, conta in pend_sorted.iterrows():
        prio     = int(conta["__prio"])
        val      = float(conta["__apagar"])
        tol      = TOLERANCIA[prio]
        margem   = MARGEM_SEG[prio]
        venc     = conta["__venc"].normalize() if pd.notna(conta["__venc"]) else data_ini
        melhor_dia = None
        tipo_ag  = "normal"

        # Janela de pagamento
        d_inicio = max(data_ini, venc)
        d_fim_ag = min(data_fim, venc + pd.Timedelta(days=tol))

        # Procura o melhor dia com saldo disponível
        d_check = d_inicio
        while d_check <= d_fim_ag:
            saldo_naquele_dia = saldo_ag.get(d_check.normalize(), 0.0)
            if saldo_naquele_dia - val >= margem:
                melhor_dia = d_check.normalize()
                break
            d_check += pd.Timedelta(days=1)

        if melhor_dia:
            saldo_ag[melhor_dia] = saldo_ag.get(melhor_dia, 0.0) - val
            # Propaga desconto para dias seguintes
            d_prop = melhor_dia + pd.Timedelta(days=1)
            while d_prop <= data_fim:
                if d_prop.normalize() in saldo_ag:
                    saldo_ag[d_prop.normalize()] -= val
                d_prop += pd.Timedelta(days=1)

            esta_atrasado = venc < hoje
            adiado = melhor_dia > venc and melhor_dia >= hoje
            tipo_ag = "atrasado" if esta_atrasado else ("adiado" if adiado else "normal")
            saldo_apos = saldo_ag.get(melhor_dia, 0.0)
            agendamento.append({
                "forn":       conta["__forn"],
                "cat":        conta["__cat"],
                "crit":       conta["__crit"],
                "prio":       prio,
                "val":        val,
                "venc":       venc,
                "venc_str":   conta["__venc_str"],
                "dia_ideal":  melhor_dia,
                "dia_str":    melhor_dia.strftime("%d/%m/%Y"),
                "dow":        DIAS_PT.get(melhor_dia.weekday(), ""),
                "tipo":       tipo_ag,
                "dias_dif":   int((melhor_dia - venc).days),
                "saldo_apos": saldo_apos,
                "motivo":     conta["__motivo"],
            })
        else:
            # Não cabe em nenhum dia
            prio2 = prio
            if prio2 == 0:   acao = "🚨 URGENTE — buscar caixa adicional imediatamente"
            elif prio2 == 1: acao = "📞 Negociar prazo — pedir no mínimo +15 dias"
            elif prio2 == 2: acao = "📅 Agendar para próximo mês"
            else:            acao = "📅 Adiar — sem impacto imediato"
            nao_cobertos_intel.append({
                "forn":     conta["__forn"],
                "cat":      conta["__cat"],
                "crit":     conta["__crit"],
                "prio":     prio2,
                "val":      val,
                "venc_str": conta["__venc_str"],
                "acao":     acao,
                "motivo":   conta["__motivo"],
            })

    # ── Agrupa por dia de pagamento ──
    dias_agenda = {}
    for item in agendamento:
        d = item["dia_ideal"]
        if d not in dias_agenda:
            dias_agenda[d] = []
        dias_agenda[d].append(item)

    # ── Saldo dia a dia real (com agendamentos) ──
    saldo_real = float(caixa_inicial)
    timeline = []
    todos_os_dias = set(dias_agenda.keys()) | {
        (data_ini + pd.Timedelta(days=i)).normalize()
        for i in range(dias_horizonte)
    }
    for d_k in sorted(todos_os_dias):
        ent  = entradas_totais.get(d_k.normalize(), 0.0)
        pags = dias_agenda.get(d_k, [])
        total_pago = sum(p["val"] for p in pags)
        saldo_real_ini = saldo_real + ent
        saldo_real     = saldo_real_ini - total_pago
        timeline.append({
            "data":        d_k,
            "data_str":    d_k.strftime("%d/%m/%Y"),
            "dow":         DIAS_PT.get(d_k.weekday(), ""),
            "saldo_inicio":saldo_real_ini - ent,
            "entradas":    ent,
            "pagamentos":  total_pago,
            "n_contas":    len(pags),
            "saldo_fim":   saldo_real,
            "status":      cor_saldo(saldo_real),
            "fim_semana":  d_k.weekday() >= 5,
            "itens":       sorted(pags, key=lambda x: x["prio"]),
        })

    # ── Totais ──
    total_pagar   = float(pend["__apagar"].sum())
    total_ag      = sum(a["val"] for a in agendamento)
    total_nc      = sum(n["val"] for n in nao_cobertos_intel)
    total_ent_conf= sum(entradas_confirmadas.values())
    total_ent_proj= sum(entradas_projetadas.values())
    dias_crit     = sum(1 for t in timeline if t["status"] in ("🔴 CRÍTICO","🚨 NEGATIVO") and not t["fim_semana"])
    n_adiados     = sum(1 for a in agendamento if a["tipo"]=="adiado")
    n_atrasados   = sum(1 for a in agendamento if a["tipo"]=="atrasado")

    return {
        "agendamento":     agendamento,
        "nao_cobertos":    nao_cobertos_intel,
        "timeline":        timeline,
        "total_pagar":     total_pagar,
        "total_agendado":  total_ag,
        "total_nc":        total_nc,
        "total_ent_conf":  total_ent_conf,
        "total_ent_proj":  total_ent_proj,
        "entradas_totais": entradas_totais,
        "dias_crit":       dias_crit,
        "n_adiados":       n_adiados,
        "n_atrasados":     n_atrasados,
        "pct_coberto":     round(len(agendamento)/max(len(pend),1)*100,1),
        "saldo_final":     saldo_real,
        "data_fim":        data_fim,
        "perc_inadimplencia": perc_inadimplencia,
    }


# ══════════════════════════════════════════════════════════════════════
# ALGORITMO DE AGENDA
# ══════════════════════════════════════════════════════════════════════
def gerar_agenda(pag_df: pd.DataFrame, rec_df: pd.DataFrame,
                 caixa_inicial: float, data_ini: pd.Timestamp,
                 dias_horizonte: int,
                 rec_pago_total: float = 0.0) -> dict:
    """
    rec_pago_total: total já recebido (do extrato OFX). Escalona as projeções.
    Algoritmo principal: distribui pagamentos dia a dia conforme entradas.
    Retorna dict com resultado_dias, nao_cobertos, totais.
    """
    data_fim = data_ini + pd.Timedelta(days=dias_horizonte - 1)
    hoje     = pd.Timestamp.now().normalize()

    # ── Recebimentos por dia ─────────────────────────────────────────
    # Inclui TODOS os recebíveis (atrasados + período + além do horizonte)
    # escalados pelo fator pendente = (1 - já_recebido / total_faturado)
    # Isso corrige a assimetria: pend tem todos os atrasos, rec também
    rec_por_dia = {}
    n_rec_dia   = {}
    if not rec_df.empty and "__val" in rec_df.columns and "__venc" in rec_df.columns:
        faturado_total  = float(rec_df["__val"].sum())
        # Fator: proporção ainda a receber (descontando OFX já recebido)
        fator_pendente  = max(1.0 - rec_pago_total / faturado_total, 0.0)                           if faturado_total > 0 else 1.0
        for _, r in rec_df.iterrows():
            if not pd.notna(r["__venc"]) or r["__val"] <= 0: continue
            d = r["__venc"].normalize()
            # Atrasados → primeiro dia | Além do horizonte → último dia
            if   d < data_ini: d_ef = data_ini
            elif d > data_fim: d_ef = data_fim
            else:              d_ef = d
            val_aj = r["__val"] * fator_pendente
            rec_por_dia[d_ef] = rec_por_dia.get(d_ef, 0.0) + val_aj
            n_rec_dia[d_ef]   = n_rec_dia.get(d_ef,  0)    + 1

    # Pendentes: atrasados OU vencem até data_fim
    pend = pag_df[
        pag_df["__venc"].isna() | (pag_df["__venc"] <= data_fim)
    ].sort_values(
        ["__prio", "__venc", "__apagar"],
        ascending=[True, True, False],
        na_position="last"
    ).copy()

    # ── Iterar dia a dia ──
    resultado_dias = []
    nao_cobertos   = []
    saldo          = float(caixa_inicial)
    pagos_ids      = set()
    # Note: rec_por_dia already accounts for the pending receivables
    # caixa_inicial = current bank balance (user should input actual saldo BTG)

    data_atual = data_ini
    while data_atual <= data_fim:
        d_norm       = data_atual.normalize()
        entradas_dia = rec_por_dia.get(d_norm, 0.0)
        n_ent        = n_rec_dia.get(d_norm, 0)
        saldo_inicio = saldo
        saldo       += entradas_dia
        fim_semana   = data_atual.weekday() >= 5

        # Contas elegíveis: atrasadas + vencendo até hoje
        contas_hoje = pend[
            (~pend.index.isin(pagos_ids)) &
            (pend["__venc"].isna() | (pend["__venc"].dt.normalize() <= d_norm))
        ]

        pagamentos_dia = []
        for idx, conta in contas_hoje.iterrows():
            val = float(conta["__apagar"])
            if saldo >= val:
                saldo -= val
                pagos_ids.add(idx)
                pagamentos_dia.append({
                    "seq":      len(pagamentos_dia) + 1,
                    "forn":     conta["__forn"],
                    "cat":      conta["__cat"],
                    "crit":     conta["__crit"],
                    "prio":     int(conta["__prio"]),
                    "status":   conta["__status_venc"],
                    "venc_str": conta["__venc_str"],
                    "dias_atr": int(conta["__dias_atr"]),
                    "motivo":   conta["__motivo"],
                    "val":      val,
                    "saldo_apos": saldo,
                })

        total_pago = sum(p["val"] for p in pagamentos_dia)
        resultado_dias.append({
            "data":          data_atual,
            "data_str":      data_atual.strftime("%d/%m/%Y"),
            "dow":           DIAS_PT[data_atual.weekday()],
            "dow_abr":       DIAS_ABR[data_atual.weekday()],
            "fim_semana":    fim_semana,
            "saldo_inicio":  saldo_inicio,
            "entradas":      entradas_dia,
            "n_recebimentos":n_ent,
            "pagamentos":    total_pago,
            "n_contas":      len(pagamentos_dia),
            "liquido":       entradas_dia - total_pago,
            "saldo_fim":     saldo,
            "status_dia":    cor_saldo(saldo),
            "itens":         pagamentos_dia,
        })
        data_atual += pd.Timedelta(days=1)

    # Não cobertos
    for idx, conta in pend.iterrows():
        if idx not in pagos_ids:
            p = int(conta["__prio"])
            if p == 0:   acao = "🚨 RENEGOCIAR PRAZO ou buscar caixa adicional"
            elif p == 1: acao = "📞 Conversar com fornecedor — pedir +7 dias"
            elif p == 2: acao = "📅 Aguardar próximo período"
            else:        acao = "📅 Aguardar próximo período"
            nao_cobertos.append({
                "forn":     conta["__forn"],
                "cat":      conta["__cat"],
                "crit":     conta["__crit"],
                "prio":     p,
                "venc_str": conta["__venc_str"],
                "venc":     conta["__venc"],
                "status":   conta["__status_venc"],
                "val":      float(conta["__apagar"]),
                "motivo":   conta["__motivo"],
                "acao":     acao,
            })
    nao_cobertos.sort(key=lambda x: (x["prio"], -(x["val"])))

    # Totais
    total_pagar    = float(pend["__apagar"].sum())
    total_coberto  = sum(d["pagamentos"] for d in resultado_dias)
    total_nc       = sum(n["val"] for n in nao_cobertos)
    total_rec_esp  = sum(rec_por_dia.values())
    # GAP usa entradas confirmadas (extrato) + projetadas do faturamento
    gap            = total_rec_esp + caixa_inicial - total_pagar
    saldo_final    = resultado_dias[-1]["saldo_fim"] if resultado_dias else caixa_inicial
    n_dias_crit    = sum(1 for d in resultado_dias
                         if d["status_dia"] in ("🔴 CRÍTICO","🚨 NEGATIVO") and not d["fim_semana"])
    pct_coberto    = round(len(pagos_ids) / max(len(pend), 1) * 100, 1)

    return {
        "dias":          resultado_dias,
        "nao_cobertos":  nao_cobertos,
        "total_pagar":   total_pagar,
        "total_coberto": total_coberto,
        "total_nc":      total_nc,
        "total_rec_esp": total_rec_esp,
        "gap":           gap,
        "saldo_final":   saldo_final,
        "n_dias_crit":   n_dias_crit,
        "pct_coberto":   pct_coberto,
        "n_cobertos":    len(pagos_ids),
        "n_nc":          len(nao_cobertos),
        "n_pend":        len(pend),
        "data_fim":      data_fim,
    }


# ══════════════════════════════════════════════════════════════════════
# IA (MAXWELL)
# ══════════════════════════════════════════════════════════════════════
def maxwell(prompt: str, api_key: str, max_tokens: int = 1000) -> str:
    if not _HAS_AI:
        return "⚠️ Biblioteca anthropic não instalada. Execute: pip install anthropic"
    # Limpa a chave (remove espaços, quebras de linha)
    key = (api_key or "").strip().replace("\n","").replace("\r","").replace(" ","")
    if not key:
        return "⚠️ Chave API não informada. Insira a chave na barra lateral."
    if not key.startswith("sk-ant-"):
        return f"⚠️ Chave inválida — deve começar com 'sk-ant-'. Verifique a chave copiada."
    try:
        client = anthropic.Anthropic(api_key=key)
        msg = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=max_tokens,
            system=(
                "Você é Maxwell, CFO IA do Grupo Jet Telecom. "
                "Analisa fluxo de caixa com precisão cirúrgica e linguagem direta. "
                "Responde em português brasileiro. Seja objetivo, use emojis estratégicos."
            ),
            messages=[{"role":"user","content":prompt}]
        )
        return msg.content[0].text
    except Exception as e:
        err = str(e)
        if "401" in err or "authentication" in err.lower():
            return "❌ Chave API inválida ou expirada. Gere uma nova em console.anthropic.com"
        if "429" in err or "rate" in err.lower():
            return "⏳ Limite de requisições atingido. Aguarde alguns segundos e tente novamente."
        return f"Erro na IA: {err}"


# ══════════════════════════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown("""
    <div style='text-align:center;padding:16px 0 8px'>
        <div style='font-size:36px'>📅</div>
        <div style='font-size:17px;font-weight:700;color:#F05A22'>Agenda de Caixa</div>
        <div style='font-size:11px;color:#888;margin-top:2px'>Grupo Jet · CFO Inteligente</div>
    </div>
    <hr>
    """, unsafe_allow_html=True)

    st.markdown("### 📂 Importar Dados")

    up_pagar = st.file_uploader(
        "💸 Contas a Pagar (xlsx/csv)",
        type=["xlsx","xls","csv"],
        key="up_pagar",
        help="Planilha com Fornecedor, Categoria, Vencimento, A Pagar"
    )
    _hub_ativo = _HAS_HUB and all([
        (lambda: (lambda k: (st.secrets.get(k,"") if hasattr(st,"secrets") else ""))("HUBSOFT_CLIENT_SECRET"))()
    ])
    if not _hub_ativo:
        up_receber = st.file_uploader(
            "📥 Faturamento / A Receber (xlsx/csv)",
            type=["xlsx","xls","csv"],
            key="up_receber",
            help="Planilha Hubsoft com nome_razaosocial, valor, data_vencimento"
        )
    else:
        up_receber = None
        st.info("📥 Faturamento via **Hubsoft** (automático)", icon="🔗")

    # ── Seletor de mês do Hubsoft ─────────────────────────────────────
    if _hub_ativo:
        st.markdown("---")
        st.markdown("#### 📅 Período Hubsoft")
        from datetime import datetime as _dt_s, timezone as _tz_s, timedelta as _td_s
        _brt_s = _tz_s(_td_s(hours=-3))
        _mes_atual = _dt_s.now(_brt_s).strftime("%Y-%m")
        _ano_atual = int(_mes_atual[:4])
        _mes_num   = int(_mes_atual[5:7])

        _col_m1, _col_m2 = st.columns(2)
        with _col_m1:
            _meses_pt = ["Jan","Fev","Mar","Abr","Mai","Jun",
                         "Jul","Ago","Set","Out","Nov","Dez"]
            _mes_sel = st.selectbox(
                "Mês", _meses_pt,
                index=_mes_num - 1,
                key="hub_mes_sel"
            )
            _mes_num_sel = _meses_pt.index(_mes_sel) + 1
        with _col_m2:
            _anos = list(range(_ano_atual - 2, _ano_atual + 2))
            _ano_sel = st.selectbox(
                "Ano", _anos,
                index=_anos.index(_ano_atual),
                key="hub_ano_sel"
            )

        _hub_mes_sidebar = f"{_ano_sel}-{_mes_num_sel:02d}"
        st.caption(f"Consultando: **{_mes_sel}/{_ano_sel}** ({_hub_mes_sidebar})")

        if st.button("🔄 Recarregar Hubsoft", key="btn_reload_hub", use_container_width=True):
            st.cache_data.clear()
            st.rerun()


    up_recebidos = st.file_uploader(
        "✅ Já Recebidos (xlsx/csv/ofx)",
        type=["xlsx","xls","csv","ofx","txt"],
        key="up_recebidos",
        help="Extrato bancário OFX ou planilha com pagamentos já recebidos"
    )

    st.markdown("---")
    st.markdown("### ⚙️ Parâmetros")

    caixa_ini = st.number_input(
        "💵 Caixa disponível hoje (R$)",
        min_value=0.0, value=0.0, step=500.0, format="%.2f",
        help="Informe o saldo bancário atual. Saldo BTG: R$ 3.391,22 (extrato OFX)"
    )
    data_ini_input = st.date_input(
        "📅 Data de início",
        value=date.today()
    )
    dias_hor = st.number_input(
        "📆 Horizonte (dias)",
        min_value=7, max_value=60, value=15, step=1
    )

    st.markdown("---")
    st.markdown("### 🤖 CFO IA — Maxwell")

    # Tenta carregar do Streamlit Secrets primeiro (deploy)
    _secret_key = ""
    try:
        _secret_key = st.secrets.get("ANTHROPIC_API_KEY", "")
    except:
        pass

    if _secret_key:
        api_key = _secret_key
        st.success("🔑 Chave API carregada dos Secrets", icon="✅")
    else:
        api_key = st.text_input(
            "Chave API Anthropic",
            type="password",
            key="api_key",
            placeholder="sk-ant-api03-...",
            help="Gere sua chave em console.anthropic.com → API Keys"
        )
        if api_key and not api_key.strip().startswith("sk-ant-"):
            st.error("⚠️ Chave inválida — deve começar com 'sk-ant-'")

    st.markdown("---")
    st.markdown(
        "<div style='font-size:10px;color:#555;text-align:center'>"
        "Grupo Jet · Plataforma CFO IA<br>v2.0 · 2026</div>",
        unsafe_allow_html=True
    )

# ══════════════════════════════════════════════════════════════════════
# CARREGA DADOS
# ══════════════════════════════════════════════════════════════════════
pag_df  = pd.DataFrame()
rec_df  = pd.DataFrame()
agenda  = None

if up_pagar:
    with st.spinner("Lendo Contas a Pagar..."):
        pag_df = parse_pagar(up_pagar)

if up_receber:
    with st.spinner("Lendo planilha de recebimentos..."):
        rec_df = parse_receber(up_receber)

rec_df_recebidos = pd.DataFrame()
if up_recebidos:
    with st.spinner("Lendo pagamentos já recebidos..."):
        rec_df_recebidos = parse_recebidos(up_recebidos)

# ── AUTO-LOAD DO HUBSOFT ─────────────────────────────────────────────
# Se credenciais configuradas nos Secrets, carrega automaticamente
_hub_auto_ok = False
if _HAS_HUB:
    def _gs(k, d=""):
        try: return st.secrets.get(k, d)
        except: return d
    _hub_url  = _gs("HUBSOFT_URL",  "https://api.jettelecom.hubsoft.com.br")
    _hub_cid  = _gs("HUBSOFT_CLIENT_ID",  "")
    _hub_csec = _gs("HUBSOFT_CLIENT_SECRET", "")
    _hub_user = _gs("HUBSOFT_USERNAME", "")
    _hub_pass = _gs("HUBSOFT_PASSWORD", "")
    _hub_cred_ok = all([_hub_url, _hub_cid, _hub_csec, _hub_user, _hub_pass])

    if _hub_cred_ok:
        from datetime import datetime as _dtnow, timezone, timedelta as _td
        _brt = timezone(_td(hours=-3))  # Brazil timezone UTC-3
        # Usa o mês selecionado na sidebar (ou mês atual como padrão)
        _hub_mes = st.session_state.get("hub_mes_sel_val",
                   _dtnow.now(_brt).strftime("%Y-%m"))
        # Salva o mês selecionado no session_state para o auto-load
        if _hub_ativo:
            _m = st.session_state.get("hub_mes_sel", _dtnow.now(_brt).strftime("%b")[:3])
            _a = st.session_state.get("hub_ano_sel", _dtnow.now(_brt).year)
            _meses_pt2 = ["Jan","Fev","Mar","Abr","Mai","Jun",
                          "Jul","Ago","Set","Out","Nov","Dez"]
            try:
                _mn = _meses_pt2.index(_m) + 1
                _hub_mes = f"{_a}-{_mn:02d}"
            except: pass

        @st.cache_data(ttl=300, show_spinner=False)
        def _hub_importar(url, cid, csec, user, pwd, mes):
            hub = HubsoftAPI(url, cid, csec, user, pwd)
            hub.autenticar()
            return hub.importar_tudo(mes)

        try:
            with st.spinner("🔄 Carregando dados do Hubsoft..."):
                _hub_data = _hub_importar(
                    _hub_url, _hub_cid, _hub_csec, _hub_user, _hub_pass, _hub_mes
                )
            # Usa dados do Hubsoft como fonte primária (sobrepõe uploads)
            if not _hub_data["rec_df"].empty:
                rec_df = _hub_data["rec_df"]
            if not _hub_data["rec_recebidos"].empty and rec_df_recebidos.empty:
                rec_df_recebidos = _hub_data["rec_recebidos"]
            _hub_auto_ok = True
            _hub_totais  = _hub_data["totais"]
        except Exception as _hub_err:
            _err_msg = str(_hub_err)
            st.session_state["hub_erro"] = _err_msg
            st.sidebar.error(f"🔗 Hubsoft: erro — ver logs")
            # Log completo para o Streamlit Cloud logs
            import traceback as _tb
            print("=== HUBSOFT ERROR ===")
            print(_err_msg)
            print(_tb.format_exc())
            print("====================")
            _hub_auto_ok = False

data_ini_ts = pd.Timestamp(data_ini_input)

# ── Calcula rec_pago ANTES de chamar gerar_agenda ──────────────────
rec_total_pre = float(rec_df["__val"].sum()) if not rec_df.empty and "__val" in rec_df.columns else 0.0
if not rec_df_recebidos.empty and "__val" in rec_df_recebidos.columns:
    rec_pago_pre = float(rec_df_recebidos["__val"].sum())
elif not rec_df.empty and "__pago" in rec_df.columns:
    rec_pago_pre = float(rec_df.loc[rec_df["__pago"], "__val"].sum())
else:
    rec_pago_pre = 0.0

if not pag_df.empty:
    with st.spinner("Calculando agenda de caixa..."):
        agenda = gerar_agenda(pag_df, rec_df, caixa_ini, data_ini_ts, int(dias_hor),
                            rec_pago_total=rec_pago_pre)

# ══════════════════════════════════════════════════════════════════════
# TELA INICIAL — sem dados
# ══════════════════════════════════════════════════════════════════════
if pag_df.empty:
    # Mostra aba Hubsoft mesmo sem planilha de contas a pagar
    _tab_boas_vindas, _tab_hub_init = st.tabs(["🏠 Início", "🔗 Hubsoft"])

    with _tab_boas_vindas:
        st.markdown("""
        <div style='text-align:center;padding:60px 20px'>
            <div style='font-size:64px'>📅</div>
            <h1 style='color:#F05A22;margin:16px 0 8px'>Agenda de Caixa</h1>
            <p style='color:#888;font-size:15px;max-width:500px;margin:0 auto'>
                Distribui pagamentos dia a dia conforme as entradas previstas.<br>
                Mostra o que pagar, o que não cabe e o saldo a cada dia.
            </p>
            <div style='margin-top:40px;display:flex;gap:24px;justify-content:center;flex-wrap:wrap'>
        """, unsafe_allow_html=True)

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.markdown("""
            <div style='background:#1A1A1A;border-radius:12px;padding:20px;text-align:center'>
                <div style='font-size:28px'>💸</div>
                <div style='font-weight:700;margin:8px 0 4px'>Contas a Pagar</div>
                <div style='font-size:11px;color:#888'>Importe sua planilha com fornecedores, categorias, vencimentos e valores</div>
            </div>""", unsafe_allow_html=True)
        with col2:
            st.markdown("""
            <div style='background:#1A1A1A;border-radius:12px;padding:20px;text-align:center'>
                <div style='font-size:28px'>📥</div>
                <div style='font-weight:700;margin:8px 0 4px'>Faturamento</div>
                <div style='font-size:11px;color:#888'>Planilha Hubsoft com cobranças a receber do mês</div>
            </div>""", unsafe_allow_html=True)
        with col3:
            st.markdown("""
            <div style='background:#1A1A1A;border-radius:12px;padding:20px;text-align:center'>
                <div style='font-size:28px'>🧮</div>
                <div style='font-weight:700;margin:8px 0 4px'>Algoritmo</div>
                <div style='font-size:11px;color:#888'>Distribui pagamentos por prioridade: 🔴 Crítico → 🟠 Alta → 🟡 Média → 🟢 Baixa</div>
            </div>""", unsafe_allow_html=True)
        with col4:
            st.markdown("""
            <div style='background:#1A1A1A;border-radius:12px;padding:20px;text-align:center'>
                <div style='font-size:28px'>🤖</div>
                <div style='font-weight:700;margin:8px 0 4px'>Maxwell CFO</div>
                <div style='font-size:11px;color:#888'>IA analisa o fluxo e recomenda ações prioritárias</div>
            </div>""", unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)
        # Mostra erro Hubsoft na tela inicial se existir
        if st.session_state.get("hub_erro"):
            with st.expander("🔗 Erro Hubsoft — clique para ver detalhes", expanded=True):
                st.error("❌ Falha na conexão com o Hubsoft:")
                st.code(st.session_state["hub_erro"], language="text")
                st.markdown("""
    **Como resolver:**
    1. Vá em **Manage app → Logs** para ver o erro completo
    2. Verifique os **Secrets** — a URL deve ser `https://api.jettelecom.hubsoft.com.br`
    3. A senha pode ter sido alterada após o vazamento no GitHub
                """)
        else:
            st.info("👈 **Comece importando a planilha de Contas a Pagar** na barra lateral.")
    with _tab_hub_init:
        st.markdown("### 🔗 Hubsoft — Diagnóstico e Dados ao Vivo")
        if not _HAS_HUB:
            st.error("hubsoft_api.py não encontrado no repositório.")
        elif st.session_state.get("hub_erro"):
            st.error("❌ Erro na conexão:")
            st.code(st.session_state["hub_erro"], language="text")
            st.markdown("""
**Como resolver:**
1. **Manage app → Logs** para ver o erro completo
2. URL nos Secrets: `https://api.jettelecom.hubsoft.com.br`
3. Credenciais no Streamlit Cloud → Settings → Secrets
            """)
        elif _hub_auto_ok:
            st.success(f"✅ Hubsoft conectado — {_hub_totais.get('atualizado_em','?')}")
            totais_h = _hub_totais
            hc1,hc2,hc3,hc4 = st.columns(4)
            hc1.metric("📋 Faturado",   brl(totais_h.get("faturado",0)),   f"{totais_h.get('n_cobrancas',0)} cobranças")
            hc2.metric("✅ Recebido",   brl(totais_h.get("recebido",0)),   f"{totais_h.get('adimplencia',0)}% adimpl.")
            hc3.metric("🔴 Atrasado",   brl(totais_h.get("atrasado",0)),   f"{totais_h.get('n_atrasadas',0)} cobranças", delta_color="inverse")
            hc4.metric("🔵 A Vencer",   brl(totais_h.get("a_vencer",0)),   f"{totais_h.get('n_a_vencer',0)} cobranças")
            st.info("👈 Para ver o diagnóstico completo, importe a **Contas a Pagar** e acesse a aba 🔗 Hubsoft completa.")
        else:
            _gs2 = lambda k,d="": (st.secrets.get(k,d) if hasattr(st,"secrets") else d)
            hub_url2   = _gs2("HUBSOFT_URL","https://api.jettelecom.hubsoft.com.br")
            hub_cid2   = _gs2("HUBSOFT_CLIENT_ID","")
            hub_csec2  = _gs2("HUBSOFT_CLIENT_SECRET","")
            hub_user2  = _gs2("HUBSOFT_USERNAME","")
            hub_pass2  = _gs2("HUBSOFT_PASSWORD","")
            if all([hub_cid2, hub_csec2, hub_user2, hub_pass2]):
                if st.button("🔄 Tentar conectar ao Hubsoft", key="btn_hub_init"):
                    st.cache_data.clear()
                    st.rerun()
            else:
                st.warning("Configure as credenciais nos **Secrets** do Streamlit Cloud.")
                st.code("""HUBSOFT_URL           = "https://api.jettelecom.hubsoft.com.br"
HUBSOFT_CLIENT_ID     = "147"
HUBSOFT_CLIENT_SECRET = "seu_secret"
HUBSOFT_USERNAME      = "ruan.lobo@grupojet.com.br"
HUBSOFT_PASSWORD      = "sua_senha"
ANTHROPIC_API_KEY     = "sk-ant-..."
""", language="toml")
    st.stop()

# ══════════════════════════════════════════════════════════════════════
# STATUS DAS PLANILHAS
# ══════════════════════════════════════════════════════════════════════
# Badge da fonte de dados
if _HAS_HUB and _hub_auto_ok:
    st.success(
        f"🔗 **Hubsoft ao vivo** — atualizado em {_hub_totais.get('atualizado_em','?')}  "
        f"· {_hub_totais.get('n_cobrancas',0)} cobranças  "
        f"· {_hub_totais.get('n_clientes', len(rec_df.iloc[:,0].unique()) if not rec_df.empty else 0)} clientes",
    )
    if st.button("🔄 Atualizar Hubsoft", key="btn_atualiza_hub"):
        st.cache_data.clear()
        st.rerun()
else:
    _scols = st.columns(3 if not rec_df_recebidos.empty else 2)
    with _scols[0]:
        st.success(f"✅ **Contas a Pagar** — {len(pag_df)} contas · {brl(pag_df['__apagar'].sum())}")
    with _scols[1]:
        if not rec_df.empty:
            st.success(f"✅ **Faturamento** — {len(rec_df)} cobranças · {brl(rec_df['__val'].sum())}")
        else:
            st.warning("⚠️ Planilha de faturamento não importada — entradas serão R$ 0")
    if len(_scols) > 2 and not rec_df_recebidos.empty:
        with _scols[2]:
            st.success(f"✅ **Já Recebidos** — {len(rec_df_recebidos)} pagtos · {brl(rec_df_recebidos['__val'].sum())}")

# ══════════════════════════════════════════════════════════════════════
# HEADER — título da agenda
# ══════════════════════════════════════════════════════════════════════
data_fim_ts = agenda["data_fim"]
st.markdown(f"""
<div style='margin:16px 0 8px'>
    <h1 style='margin:0;color:#F5F5F5'>📅 Agenda Oficial — Grupo Jet</h1>
    <p style='color:#888;margin:4px 0 0;font-size:13px'>
        {data_ini_ts.strftime('%d/%m/%Y')} a {data_fim_ts.strftime('%d/%m/%Y')} ·
        Base: Faturado {brl(rec_df['__val'].sum() if not rec_df.empty else 0)} ·
        A Pagar {brl(pag_df['__apagar'].sum())} ·
        Caixa {brl(caixa_ini)}
    </p>
</div>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════
# DASHBOARD — KPIs
# ══════════════════════════════════════════════════════════════════════
a = agenda  # atalho

# ── Fonte de verdade: Recebido = extrato OFX > Hubsoft baixados ──
hoje_ts     = pd.Timestamp.now().normalize()
rec_total   = float(rec_df["__val"].sum()) if not rec_df.empty else 0.0
rec_faturado= rec_total  # total faturado = todas as cobranças

# Recebido real: prioridade para o extrato OFX (Já Recebidos)
if not rec_df_recebidos.empty:
    rec_pago = float(rec_df_recebidos["__val"].sum())
    fonte_rec = f"{len(rec_df_recebidos)} pgtos (sem intercompany)"
elif not rec_df.empty and "__pago" in rec_df.columns:
    rec_pago = float(rec_df.loc[rec_df["__pago"], "__val"].sum())
    fonte_rec = "Hubsoft baixados"
else:
    rec_pago  = 0.0
    fonte_rec = "não importado"

rec_a_receber = max(rec_total - rec_pago, 0.0)
pct_adimpl    = round(rec_pago / max(rec_total, 1) * 100, 1)

# Linha 1 — visão geral
k1,k2,k3,k4,k5 = st.columns(5)
_n_cli = rec_df.iloc[:,0].nunique() if not rec_df.empty else 0
_n_cobr = len(rec_df) if not rec_df.empty else 0
k1.metric("💰 Faturado",   brl(rec_total),    f"{_n_cobr} cobranças · {_n_cli} clientes")
k2.metric("✅ Recebido",   brl(rec_pago),     f"{pct_adimpl}% — {fonte_rec}")
k3.metric("📊 A Receber",  brl(rec_a_receber),f"{round(100-pct_adimpl,1)}% pendente")
k4.metric("💸 A Pagar",    brl(pag_df["__apagar"].sum()), f"{len(pag_df)} contas")
k5.metric("💵 Caixa Hoje", brl(caixa_ini))

st.markdown("---")

# Detalhamento A Pagar / A Receber
col_det1, col_det2 = st.columns(2)
with col_det1:
    st.markdown(f"**💸 Detalhamento A Pagar — {brl(pag_df['__apagar'].sum())}**")
    atras_pag = pag_df[pag_df["__status_venc"]=="ATRASADO"]["__apagar"].sum()
    avent_pag = pag_df[pag_df["__status_venc"]=="A VENCER"]["__apagar"].sum()
    da1,da2 = st.columns(2)
    da1.metric("🔴 Em Atraso",        brl(atras_pag))
    da2.metric("⏳ A Vencer (período)", brl(avent_pag))

with col_det2:
    st.markdown(f"**📥 Detalhamento A Receber — {brl(rec_faturado)}**")
    if not rec_df_recebidos.empty:
        # Com extrato: mostra recebido confirmado vs pendente
        db1,db2,db3 = st.columns(3)
        db1.metric("✅ Recebido (extrato)",  brl(rec_pago),       fonte_rec)
        db2.metric("🔵 A Receber",           brl(rec_a_receber))
        # Inadimplentes = vencidos não recebidos
        if not rec_df.empty and "__venc" in rec_df.columns:
            vencidos_hub = rec_df[
                rec_df["__venc"].apply(lambda d: pd.notna(d) and d < hoje_ts)
            ]["__val"].sum()
            inadimp = max(vencidos_hub - rec_pago, 0)
            db3.metric("🚨 Inadimplentes est.", brl(inadimp))
    elif not rec_df.empty:
        rec_inad = rec_df[
            rec_df["__venc"].apply(lambda d: pd.notna(d) and d < hoje_ts)
        ]["__val"].sum() if "__venc" in rec_df.columns else 0
        rec_normal = max(rec_a_receber - rec_inad, 0)
        db1,db2 = st.columns(2)
        db1.metric("🚨 Inadimplentes", brl(rec_inad))
        db2.metric("⏳ A Vencer",      brl(rec_normal))
    else:
        st.info("Sem planilha de recebimentos")

st.markdown("---")

# ── GAP REAL: A Receber − A Pagar ──────────────────────────────────────────
# A Receber = o que ainda está pendente de entrar (faturado - já recebido)
# A Pagar   = total de compromissos em aberto
# GAP       = A Receber - A Pagar  →  negativo = vai faltar dinheiro
total_a_pagar  = float(pag_df["__apagar"].sum())
gap_real       = rec_a_receber - total_a_pagar     # rec_a_receber = faturado - rec_pago
gap_com_caixa  = rec_a_receber + caixa_ini - total_a_pagar  # considera o que já tem no caixa

st.markdown("#### 📌 Posição Financeira Real")
an1, an2, an3, an4 = st.columns(4)
an1.metric("✅ Já Recebido",        brl(rec_pago),         fonte_rec)
an2.metric("🔵 A Receber (pend.)",  brl(rec_a_receber),    f"{round(100-pct_adimpl,1)}% do faturado")
an3.metric("💸 A Pagar (total)",    brl(total_a_pagar),    f"{len(pag_df)} contas")
an4.metric(
    "⚖️ GAP Real (A Receber − A Pagar)",
    brl(abs(gap_real)),
    f"{'DÉFICIT — vai faltar 🔴' if gap_real < 0 else 'SUPERÁVIT ✅'}",
    delta_color="inverse" if gap_real < 0 else "normal"
)

if gap_real < 0:
    st.error(
        f"🚨 **Déficit real de {brl(abs(gap_real))}** — "
        f"O que ainda será recebido (**{brl(rec_a_receber)}**) "
        f"não cobre o que precisa ser pago (**{brl(total_a_pagar)}**). "
        f"{'Com o caixa atual, o déficit é ' + brl(abs(gap_com_caixa)) if gap_com_caixa < 0 else 'Com o caixa atual (' + brl(caixa_ini) + '), déficit reduz para ' + brl(abs(gap_com_caixa))}"
    )
else:
    st.success(
        f"✅ **Superávit de {brl(gap_real)}** — "
        f"O que será recebido ({brl(rec_a_receber)}) supera os compromissos ({brl(total_a_pagar)})."
    )

st.markdown("---")

# ── Projeção consistente: A Receber total vs A Pagar total ──────────────
# Usa rec_a_receber (tudo que ainda não entrou) para comparar com total a pagar
# O gap_real já foi calculado acima: rec_a_receber - total_a_pagar
gap_periodo = rec_a_receber + caixa_ini - total_a_pagar

st.markdown(f"#### 📅 Projeção dos Próximos {int(dias_hor)} Dias")
an_p1, an_p2, an_p3 = st.columns(3)
an_p1.metric("💸 Compromissos (total)",     brl(total_a_pagar),        f"{len(pag_df)} contas")
an_p2.metric("📥 A Receber (pendente)",    brl(rec_a_receber),        f"= Faturado {brl(rec_total)} − Recebido {brl(rec_pago)}")
an_p3.metric(
    "⚖️ GAP (A Receber + Caixa − A Pagar)",
    brl(abs(gap_periodo)),
    "DÉFICIT" if gap_periodo < 0 else "SUPERÁVIT",
    delta_color="inverse" if gap_periodo < 0 else "normal"
)

st.markdown("---")

# Resultado
st.markdown("#### ✅ Resultado da Agenda")
re1,re2,re3,re4 = st.columns(4)
re1.metric("✅ Cobertos",       brl(a["total_coberto"]),
           f"{a['n_cobertos']} contas — {a['pct_coberto']}%")
re2.metric("❌ Não Cobertos",   brl(a["total_nc"]),
           f"{a['n_nc']} contas — {round(a['n_nc']/max(a['n_pend'],1)*100,1)}%",
           delta_color="inverse")
re3.metric("💵 Saldo Final",    brl(a["saldo_final"]))
re4.metric("🚨 Dias Críticos",  str(a["n_dias_crit"]),
           "saldo < R$ 500",
           delta_color="inverse" if a["n_dias_crit"] > 2 else "off")

st.markdown("---")

# ── FLUXO DIÁRIO PROJETADO ──
st.markdown("#### 📅 Fluxo Diário Projetado")

fluxo_rows = []
for d in a["dias"]:
    fluxo_rows.append({
        "Data":        d["data_str"],
        "Dia":         d["dow"],
        "Saldo Início":brl(d["saldo_inicio"]),
        "Entradas":    brl(d["entradas"]),
        "Pagamentos":  brl(d["pagamentos"]),
        "Líquido":     brl(d["liquido"]),
        "Saldo Fim":   brl(d["saldo_fim"]),
        "Qtde Pgto":   d["n_contas"],
        "Status":      d["status_dia"],
    })
st.dataframe(pd.DataFrame(fluxo_rows), use_container_width=True, hide_index=True, height=360)

# ── GRÁFICO ──
fig = go.Figure()
datas   = [d["data"].strftime("%d/%m") for d in a["dias"]]
saldos  = [d["saldo_fim"] for d in a["dias"]]
entradas= [d["entradas"]  for d in a["dias"]]
pagtos  = [d["pagamentos"] for d in a["dias"]]

fig.add_trace(go.Bar(name="📥 Entradas", x=datas, y=entradas,
    marker_color="#22A85A", opacity=0.8))
fig.add_trace(go.Bar(name="💸 Pagamentos", x=datas, y=pagtos,
    marker_color="#F05A22", opacity=0.8))
fig.add_trace(go.Scatter(name="💵 Saldo Fim", x=datas, y=saldos,
    mode="lines+markers", line=dict(color="#FFD600", width=2.5),
    marker=dict(size=7, color=[
        "#FF4444" if s<500 else "#FF9800" if s<2000 else "#4CAF50"
        for s in saldos
    ])))
fig.update_layout(
    barmode="group", height=340,
    plot_bgcolor="#111", paper_bgcolor="#111",
    font_color="#CCC",
    xaxis=dict(gridcolor="#222", tickfont=dict(size=11)),
    yaxis=dict(gridcolor="#222", tickprefix="R$ "),
    legend=dict(bgcolor="#1A1A1A", bordercolor="#333", x=0, y=1.12, orientation="h"),
    margin=dict(t=30,b=30,l=60,r=20),
)
st.plotly_chart(fig, use_container_width=True)

# ── DIAGNÓSTICO FINAL ──
st.markdown("#### 🎯 Diagnóstico Final")
nc_crit = [n for n in a["nao_cobertos"] if n["prio"] == 0]
dias_crit_list = [d for d in a["dias"] if d["status_dia"] in ("🔴 CRÍTICO","🚨 NEGATIVO") and not d["fim_semana"]]
st.markdown(f"""
**📋 SITUAÇÃO BASE:**
- 💵 Caixa atual: **{brl(caixa_ini)}**
- ✅ Já recebido: **{brl(rec_pago)}** ({fonte_rec})
- 🔵 A receber (pendente): **{brl(rec_a_receber)}**
- 💸 A pagar (total): **{brl(total_a_pagar)}**
- ⚖️ **GAP REAL (A Receber − A Pagar): {brl(abs(gap_real))} {'DÉFICIT 🔴' if gap_real < 0 else 'SUPERÁVIT ✅'}**

**📅 PROJEÇÃO DOS PRÓXIMOS {int(dias_hor)} DIAS:**
- Compromissos do período: **{brl(a['total_pagar'])}** ({a['n_pend']} contas)
- A Receber (pendente): **{brl(rec_a_receber)}** = Faturado {brl(rec_total)} − Recebido {brl(rec_pago)}
- GAP do período: **{brl(abs(gap_periodo))}** ({'DÉFICIT 🔴' if gap_periodo < 0 else 'SUPERÁVIT ✅'})

**✅ RESULTADO DA AGENDA:**
- Pagamentos COBERTOS: **{brl(a['total_coberto'])}** ({a['n_cobertos']} contas — {a['pct_coberto']}%)
- Pagamentos NÃO COBERTOS: **{brl(a['total_nc'])}** ({a['n_nc']} contas — {round(a['n_nc']/max(a['n_pend'],1)*100,1)}%)
- Saldo final do período: **{brl(a['saldo_final'])}**

**🚨 AÇÕES OBRIGATÓRIAS:**
1. COBRAR os **{brl(rec_a_receber)}** pendentes para cobrir o déficit de **{brl(abs(gap_real))}**
2. RENEGOCIAR prazo de **{a['n_nc']} contas** que não cabem no caixa *(ver ⚠️ Não Cobertos)*
3. Monitorar os **{a['n_dias_crit']} dias críticos** com saldo < R$ 500
""")

# ══════════════════════════════════════════════════════════════════════
# TABS — as 3 abas restantes da planilha
# ══════════════════════════════════════════════════════════════════════
st.markdown("---")
_n_rec = len(rec_df_recebidos) if not rec_df_recebidos.empty else 0
_v_rec = rec_df_recebidos["__val"].sum() if not rec_df_recebidos.empty else 0.0

# Calcula cruzamento cliente a cliente
with st.spinner("📊 Cruzando faturamento × recebimentos..."):
    crz = cruzar_clientes(rec_df, rec_df_recebidos)

# Calcula inteligência financeira
with st.spinner("🧠 Calculando agendamento inteligente..."):
    intel = agendar_inteligente(
        pag_df, rec_df, rec_df_recebidos,
        caixa_ini, data_ini_ts, int(dias_hor),
        perc_inadimplencia=0.30,
        usar_recebidos=True,
    )

tab_intel, tab_agenda, tab_hub, tab_crz, tab_recebidos, tab_categ, tab_lista, tab_nc, tab_maxwell = st.tabs([
    "🧠 Inteligência Financeira",
    "📅 Agenda Detalhada",
    "🔗 Hubsoft",
    "📊 Cruzamento Clientes",
    f"✅ Já Recebidos ({_n_rec}) — {brl(_v_rec)}",
    "📂 Por Categoria",
    f"📋 Lista Completa ({a['n_pend']})",
    f"⚠️ Não Cobertos ({a['n_nc']}) — {brl(a['total_nc'])}",
    "🤖 Maxwell CFO",
])

# ══════════════════════════════════════════════════════════════════════
# TAB INTELIGÊNCIA FINANCEIRA
# ══════════════════════════════════════════════════════════════════════
with tab_intel:
    st.markdown("### 🧠 Inteligência Financeira — Agendamento Otimizado")
    st.markdown(
        "O sistema projeta o caixa dia a dia e agenda cada pagamento no **melhor momento possível**, "
        "respeitando criticidade, vencimentos e margem de segurança."
    )

    # ── Parâmetros da inteligência ──
    with st.expander("⚙️ Parâmetros do agendamento inteligente", expanded=False):
        pc1, pc2, pc3 = st.columns(3)
        with pc1:
            perc_inad = st.slider(
                "📉 Inadimplência esperada (%)",
                min_value=0, max_value=80, value=30, step=5,
                help="Percentual dos recebimentos esperados que provavelmente não entrarão"
            )
        with pc2:
            st.markdown("**Tolerância de atraso por criticidade:**")
            st.markdown("🔴 CRÍTICO: 0d | 🟠 ALTA: +3d | 🟡 MÉDIA: +7d | 🟢 BAIXA: +15d")
        with pc3:
            usar_rec_conf = st.checkbox(
                "Usar recebimentos confirmados (extrato)",
                value=True,
                help="Se marcado, prioriza os valores já confirmados no extrato bancário"
            )
        if st.button("🔄 Recalcular com estes parâmetros", type="primary"):
            with st.spinner("Recalculando..."):
                intel = agendar_inteligente(
                    pag_df, rec_df, rec_df_recebidos,
                    caixa_ini, data_ini_ts, int(dias_hor),
                    perc_inadimplencia=perc_inad/100,
                    usar_recebidos=usar_rec_conf,
                )
            st.success("✅ Agendamento recalculado!")
            st.rerun()

    st.markdown("---")

    # ── KPIs da inteligência ──
    ik1,ik2,ik3,ik4,ik5 = st.columns(5)
    ik1.metric("✅ Agendado",         brl(intel["total_agendado"]),
               f"{len(intel['agendamento'])} contas ({intel['pct_coberto']}%)")
    ik2.metric("❌ Não coberto",      brl(intel["total_nc"]),
               f"{len(intel['nao_cobertos'])} contas", delta_color="inverse")
    ik3.metric("📥 Entradas confirmadas", brl(intel["total_ent_conf"]))
    ik4.metric("📊 Entradas projetadas",  brl(intel["total_ent_proj"]),
               f"c/ {round(intel['perc_inadimplencia']*100,0):.0f}% inadimpl.")
    ik5.metric("💵 Saldo final projetado", brl(intel["saldo_final"]),
               delta_color="inverse" if intel["saldo_final"]<0 else "normal")

    # alertas
    if intel["n_adiados"] > 0:
        st.warning(
            f"⏳ **{intel['n_adiados']} contas foram adiadas** além do vencimento "
            f"por falta de saldo no dia — mas serão pagas dentro do período."
        )
    if intel["n_atrasados"] > 0:
        st.info(
            f"🕐 **{intel['n_atrasados']} contas já estavam atrasadas** "
            f"e foram reagendadas para o primeiro dia com saldo disponível."
        )
    if len(intel["nao_cobertos"]) > 0:
        crit_nc = sum(1 for n in intel["nao_cobertos"] if n["prio"]==0)
        if crit_nc > 0:
            st.error(
                f"🚨 **{crit_nc} contas CRÍTICAS** não cabem no caixa projetado — "
                f"ação imediata necessária!"
            )

    st.markdown("---")

    # ── Gráfico de saldo projetado inteligente ──
    st.markdown("#### 📈 Projeção de Caixa com Agendamento Otimizado")
    tl = intel["timeline"]
    tl_datas   = [t["data_str"] for t in tl]
    tl_saldo   = [t["saldo_fim"] for t in tl]
    tl_ent     = [t["entradas"] for t in tl]
    tl_pag     = [t["pagamentos"] for t in tl]

    fig_intel = go.Figure()
    fig_intel.add_trace(go.Bar(
        name="📥 Entradas", x=tl_datas, y=tl_ent,
        marker_color="#22A85A", opacity=0.75
    ))
    fig_intel.add_trace(go.Bar(
        name="💸 Pagamentos agendados", x=tl_datas, y=tl_pag,
        marker_color="#F05A22", opacity=0.75
    ))
    fig_intel.add_trace(go.Scatter(
        name="💵 Saldo projetado", x=tl_datas, y=tl_saldo,
        mode="lines+markers",
        line=dict(color="#FFD600", width=2.5),
        marker=dict(size=7, color=[
            "#FF4444" if s<0 else "#FF9800" if s<500 else "#FFD600" if s<5000 else "#4CAF50"
            for s in tl_saldo
        ])
    ))
    # Linha de zero
    fig_intel.add_hline(y=0, line_dash="dash", line_color="#555", annotation_text="R$ 0")
    fig_intel.update_layout(
        barmode="group", height=340,
        plot_bgcolor="#111", paper_bgcolor="#111", font_color="#CCC",
        xaxis=dict(gridcolor="#222"), yaxis=dict(gridcolor="#222", tickprefix="R$ "),
        legend=dict(bgcolor="#1A1A1A", bordercolor="#333", x=0, y=1.12, orientation="h"),
        margin=dict(t=30,b=30,l=70,r=20),
    )
    st.plotly_chart(fig_intel, use_container_width=True)

    # ── Cronograma de pagamentos ──
    st.markdown("---")
    st.markdown("#### 🗓️ Cronograma Otimizado de Pagamentos")

    # Filtros
    cf1, cf2, cf3 = st.columns([2,2,2])
    with cf1:
        filt_tipo = st.selectbox("Status:", ["Todos","normal","adiado","atrasado"], key="intel_tipo")
    with cf2:
        filt_crit_i = st.selectbox("Criticidade:", ["Todas","🔴 CRÍTICO","🟠 ALTA","🟡 MÉDIA","🟢 BAIXA"], key="intel_crit")
    with cf3:
        busca_i = st.text_input("🔍 Buscar fornecedor:", key="intel_busca")

    agenda_show = intel["agendamento"]
    if filt_tipo != "Todos":    agenda_show = [a for a in agenda_show if a["tipo"]==filt_tipo]
    if filt_crit_i != "Todas":  agenda_show = [a for a in agenda_show if a["crit"]==filt_crit_i]
    if busca_i:                 agenda_show = [a for a in agenda_show if busca_i.lower() in a["forn"].lower()]

    if agenda_show:
        tipo_emoji = {"normal":"✅","adiado":"⏳","atrasado":"🕐"}
        df_ag_show = pd.DataFrame([{
            "Status":        tipo_emoji.get(a["tipo"],"✅") + " " + a["tipo"].capitalize(),
            "Dia Pagamento": a["dia_str"] + " " + a["dow"][:3],
            "Vencimento":    a["venc_str"],
            "Dias Dif.":     f"+{a['dias_dif']}d" if a["dias_dif"]>0 else ("ATRASADO" if a["dias_dif"]<0 else "no prazo"),
            "Criticidade":   a["crit"],
            "Fornecedor":    a["forn"][:42],
            "Categoria":     a["cat"],
            "Valor":         brl(a["val"]),
            "Saldo Após":    brl(a["saldo_apos"]),
            "Motivo":        a["motivo"],
        } for a in agenda_show])
        st.dataframe(df_ag_show, use_container_width=True, hide_index=True, height=460)
        st.markdown(
            f"**{len(agenda_show)} contas** · Total: **{brl(sum(a['val'] for a in agenda_show))}**"
        )
    else:
        st.info("Nenhuma conta no filtro selecionado.")

    # ── Não cobertos ──
    if intel["nao_cobertos"]:
        st.markdown("---")
        st.markdown(f"#### ⚠️ Não Cobertos — {len(intel['nao_cobertos'])} contas · {brl(intel['total_nc'])}")
        nc_rows = pd.DataFrame([{
            "Criticidade":       n["crit"],
            "Fornecedor":        n["forn"][:42],
            "Categoria":         n["cat"],
            "Vencimento":        n["venc_str"],
            "Valor":             brl(n["val"]),
            "Ação Recomendada":  n["acao"],
        } for n in intel["nao_cobertos"]])
        st.dataframe(nc_rows, use_container_width=True, hide_index=True, height=300)

    # ── Análise Maxwell ──
    st.markdown("---")
    st.markdown("#### 🤖 Análise da Inteligência Financeira por Maxwell")
    if not api_key:
        st.info("🔑 Configure a chave API Anthropic na barra lateral para ativar o Maxwell.")
    else:
        col_ai1, col_ai2 = st.columns(2)
        with col_ai1:
            if st.button("🧠 Analisar agendamento inteligente", type="primary", use_container_width=True):
                n_atras = intel["n_atrasados"]
                n_adi   = intel["n_adiados"]
                nc_crit = [n for n in intel["nao_cobertos"] if n["prio"]==0]
                dias_ct = intel["dias_crit"]
                d1 = data_ini_ts.strftime("%d/%m")
                d2 = intel["data_fim"].strftime("%d/%m/%Y")
                nc_nm = ", ".join(n["forn"][:25] for n in nc_crit[:5]) or "nenhum"
                prompt_intel = (
                    "AGENDAMENTO INTELIGENTE Grupo Jet\n"
                    + f"Periodo: {d1} a {d2}\n"
                    + f"Caixa: {brl(caixa_ini)}\n"
                    + f"A pagar: {brl(intel['total_pagar'])} | Agendado: {brl(intel['total_agendado'])} ({intel['pct_coberto']}%)\n"
                    + f"Nao coberto: {brl(intel['total_nc'])} (15 contas) | Adiados: {n_adi}\n"
                    + f"Saldo final: {brl(intel['saldo_final'])} | Dias criticos: {dias_ct}\n"
                    + f"Criticos: {nc_nm}\n"
                    + "Analise: 1)Liquidez 2)Negociar 3)Caixa 4)Cobranca 5)Riscos"
                )
                with st.spinner("Maxwell analisando agendamento..."):
                    resp = maxwell(prompt_intel, api_key, max_tokens=1400)
                st.markdown(f'<div class="insight">{resp.replace(chr(10),"<br>")}</div>', unsafe_allow_html=True)

        with col_ai2:
            if st.button("💡 Simular cenário otimista (+20% recebimentos)", use_container_width=True):
                with st.spinner("Simulando..."):
                    intel_otim = agendar_inteligente(
                        pag_df, rec_df, rec_df_recebidos,
                        caixa_ini, data_ini_ts, int(dias_hor),
                        perc_inadimplencia=0.10,
                        usar_recebidos=True,
                    )
                    diff_ag  = intel_otim["total_agendado"] - intel["total_agendado"]
                    diff_nc  = intel_otim["total_nc"]       - intel["total_nc"]
                    st.success(
                        f"**Cenário otimista (10% inadimplência):**\n\n"
                        f"✅ Agendado: {brl(intel_otim['total_agendado'])} "
                        f"({'+'  if diff_ag>=0 else ''}{brl(diff_ag)} vs atual)\n"
                        f"❌ Não coberto: {brl(intel_otim['total_nc'])} "
                        f"({'+'  if diff_nc>=0 else ''}{brl(diff_nc)})\n"
                        f"💵 Saldo final: {brl(intel_otim['saldo_final'])}"
                    )


# ══════════════════════════════════════════════════════════════════════
# TAB RECEBIDOS — JÁ RECEBIDOS
# ══════════════════════════════════════════════════════════════════════
with tab_recebidos:
    st.markdown("### ✅ Contas Já Recebidas")

    if rec_df_recebidos.empty:
        st.info(
            "📥 **Importe os pagamentos já recebidos** na barra lateral (campo "
            "*✅ Já Recebidos*).\n\n"
            "Formatos aceitos:\n"
            "- **Extrato OFX** do banco (BTG, Itaú, BB, Sicoob…)\n"
            "- **Planilha xlsx/csv** com colunas: `pagante`, `valor`, `data`"
        )
    else:
        rdf = rec_df_recebidos.copy()
        total_rec = float(rdf["__val"].sum())
        n_rec     = len(rdf)

        # ── KPIs ──
        fat_hub = rec_df["__val"].sum() if not rec_df.empty else 0
        pct_rec = round(total_rec / max(fat_hub, 1) * 100, 1)
        a_rec_val = max(fat_hub - total_rec, 0)
        kr1, kr2, kr3, kr4 = st.columns(4)
        kr1.metric("✅ Total recebido",   brl(total_rec),  f"{n_rec} pagamentos")
        kr2.metric("📋 Faturado (hub)",   brl(fat_hub),    f"{len(rec_df) if not rec_df.empty else 0} cobranças")
        kr3.metric("📊 Adimplência",      f"{pct_rec}%",   "do faturado")
        kr4.metric("🔵 Ainda a receber",  brl(a_rec_val))

        st.markdown("---")

        # ── Entrada manual adicional ──
        with st.expander("➕ Registrar recebimento manualmente", expanded=False):
            st.markdown("Adicione um pagamento avulso não constante no arquivo importado.")
            c_m1, c_m2, c_m3, c_m4 = st.columns([3,2,2,1])
            with c_m1: nome_man  = st.text_input("Pagante / Cliente", key="man_nome")
            with c_m2: val_man   = st.number_input("Valor (R$)", min_value=0.01, step=100.0, format="%.2f", key="man_val")
            with c_m3: data_man  = st.date_input("Data recebimento", key="man_data")
            with c_m4:
                st.markdown("<br>", unsafe_allow_html=True)
                if st.button("✚ Adicionar", key="btn_add_rec", use_container_width=True):
                    if nome_man.strip() and val_man > 0:
                        nova = pd.DataFrame([{
                            "__pagante": nome_man.strip(),
                            "__val":     float(val_man),
                            "__data":    pd.Timestamp(data_man),
                            "__memo":    nome_man.strip(),
                        }])
                        rec_df_recebidos = pd.concat([rec_df_recebidos, nova], ignore_index=True)
                        rdf = rec_df_recebidos.copy()
                        total_rec = float(rdf["__val"].sum())
                        n_rec = len(rdf)
                        st.success(f"✅ Recebimento de {brl(val_man)} de {nome_man} adicionado!")
                        st.rerun()

        st.markdown("---")

        # ── Filtros ──
        fb1, fb2, fb3 = st.columns([3,2,2])
        with fb1: busca_r = st.text_input("🔍 Buscar pagante", key="busca_rec")
        with fb2:
            if rdf["__data"].notna().any():
                datas_disp = sorted(rdf["__data"].dropna().dt.date.unique())
                data_filt  = st.selectbox("📅 Filtrar data",
                    ["Todas"] + [d.strftime("%d/%m/%Y") for d in datas_disp], key="data_rec")
            else:
                data_filt = "Todas"
        with fb3:
            ord_rec = st.selectbox("Ordenar por",
                ["Valor ↓","Data ↓","Pagante ↑"], key="ord_rec")

        rdf_show = rdf.copy()
        if busca_r:
            rdf_show = rdf_show[rdf_show["__pagante"].str.lower().str.contains(busca_r.lower(), na=False)]
        if data_filt != "Todas":
            rdf_show = rdf_show[rdf_show["__data"].dt.strftime("%d/%m/%Y") == data_filt]
        if ord_rec == "Valor ↓":       rdf_show = rdf_show.sort_values("__val", ascending=False)
        elif ord_rec == "Data ↓":      rdf_show = rdf_show.sort_values("__data", ascending=False)
        elif ord_rec == "Pagante ↑":   rdf_show = rdf_show.sort_values("__pagante")

        st.markdown(f"**{len(rdf_show)} pagamentos** · Total filtrado: **{brl(rdf_show['__val'].sum())}**")

        # Tabela principal
        disp_r = pd.DataFrame({
            "#":        range(1, len(rdf_show)+1),
            "Pagante":  rdf_show["__pagante"].str[:50],
            "Valor":    rdf_show["__val"].apply(brl),
            "Data":     rdf_show["__data"].apply(
                            lambda d: d.strftime("%d/%m/%Y") if pd.notna(d) else "—"),
            "Descrição":rdf_show["__memo"].str[:60],
        })
        st.dataframe(disp_r, use_container_width=True, hide_index=True, height=420)

        st.markdown("---")

        # ── Resumo por data ──
        if rdf["__data"].notna().any():
            st.markdown("#### 📅 Recebimentos por Dia")
            por_dia = (
                rdf.groupby(rdf["__data"].dt.normalize())["__val"]
                .agg(["sum","count"])
                .reset_index()
                .sort_values("__data", ascending=False)
            )
            por_dia.columns = ["Data","Total Recebido","Qtd Pagamentos"]
            por_dia["Data"] = por_dia["Data"].dt.strftime("%d/%m/%Y")
            por_dia["Total Recebido"] = por_dia["Total Recebido"].apply(brl)
            st.dataframe(por_dia, use_container_width=True, hide_index=True, height=280)

        # ── Top pagantes ──
        st.markdown("#### 👥 Top Pagantes")
        top_pag = (
            rdf.groupby("__pagante")["__val"]
            .sum()
            .nlargest(15)
            .reset_index()
        )
        top_pag.columns = ["Pagante","Total Recebido"]
        top_pag["Total Recebido"] = top_pag["Total Recebido"].apply(brl)
        top_pag["#"] = range(1, len(top_pag)+1)
        st.dataframe(top_pag[["#","Pagante","Total Recebido"]],
                     use_container_width=True, hide_index=True, height=min(38*len(top_pag)+42, 420))


# ══════════════════════════════════════════════════════════════════════
# TAB 1 — AGENDA DETALHADA
# ══════════════════════════════════════════════════════════════════════
with tab_agenda:
    for dia in a["dias"]:
        dow   = dia["dow"].upper()
        fds   = "  ⏸️ FIM DE SEMANA" if dia["fim_semana"] else ""
        sf    = dia["saldo_fim"]
        cor_sf= "#4CAF50" if sf>5000 else "#FF9800" if sf>500 else "#FF4444"

        if dia["fim_semana"]:
            st.markdown(f"""
            <div class='dia-header-fds'>
                <span style='color:#888;font-weight:700'>📅 {dia['data_str']} — {dow}{fds}</span>
                &nbsp;&nbsp;
                <span style='color:#555;font-size:12px'>Saldo Fim: <b style='color:#666'>{brl(sf)}</b></span>
            </div>""", unsafe_allow_html=True)
            st.caption(
                f"💰 Início: {brl(dia['saldo_inicio'])}  |  "
                f"📥 Entradas: {brl(dia['entradas'])} ({dia['n_recebimentos']} rec.)  |  "
                f"💸 Pagamentos: {brl(dia['pagamentos'])} (0 contas)  |  "
                f"📊 Líquido: {brl(dia['liquido'])}"
            )
        else:
            st.markdown(f"""
            <div class='dia-header'>
                <span style='color:#FFF;font-weight:700;font-size:15px'>📅 {dia['data_str']} — {dow}</span>
                &nbsp;&nbsp;
                <span style='font-size:12px;color:#AAA'>
                    Saldo Fim: <b style='color:{cor_sf}'>{brl(sf)}</b>
                    &nbsp;·&nbsp; {dia['status_dia']}
                </span>
            </div>""", unsafe_allow_html=True)
            st.caption(
                f"💰 Início: {brl(dia['saldo_inicio'])}  |  "
                f"📥 Entradas: {brl(dia['entradas'])} ({dia['n_recebimentos']} rec.)  |  "
                f"💸 Pagamentos: {brl(dia['pagamentos'])} ({dia['n_contas']} contas)  |  "
                f"📊 Líquido: {brl(dia['liquido'])}"
            )

        if dia["itens"]:
            rows = []
            for it in dia["itens"]:
                rows.append({
                    "#":           it["seq"],
                    "Fornecedor":  it["forn"][:45],
                    "Categoria":   it["cat"],
                    "Criticidade": it["crit"],
                    "Status":      it["status"],
                    "Vencim.":     it["venc_str"],
                    "Dias Atr.":   it["dias_atr"] if it["dias_atr"] > 0 else "—",
                    "Motivo":      it["motivo"],
                    "Valor (R$)":  brl(it["val"]),
                    "Saldo Após":  brl(it["saldo_apos"]),
                })
            st.dataframe(
                pd.DataFrame(rows),
                use_container_width=True,
                hide_index=True,
                height=min(38 * len(dia["itens"]) + 42, 340)
            )
        elif not dia["fim_semana"]:
            st.caption("— sem pagamentos programados neste dia —")

# ══════════════════════════════════════════════════════════════════════
# TAB CRUZAMENTO CLIENTES
# ══════════════════════════════════════════════════════════════════════
with tab_crz:
    st.markdown("### 📊 Cruzamento Cliente a Cliente")
    st.markdown(
        "Cada cobrança do Hubsoft cruzada com o extrato bancário. "
        "Mostra exatamente o que cada cliente pagou, o que está atrasado e o que ainda vai vencer."
    )

    cli_df   = crz.get("cli", pd.DataFrame())
    rec_aug  = crz.get("rec_aug", pd.DataFrame())
    ofx_cas  = crz.get("ofx_casado", 0.0)
    ofx_nc   = crz.get("ofx_nc", 0.0)
    n_match  = crz.get("n_matches", 0)

    if cli_df.empty:
        st.info("📥 Importe o **Faturamento** e os **Já Recebidos** (OFX ou planilha) para ver o cruzamento.")
    else:
        t_fat = float(cli_df["faturado"].sum())
        t_rec = float(cli_df["recebido"].sum())
        t_atr = float(cli_df["atrasado"].sum())
        t_av  = float(cli_df["a_vencer"].sum())
        n_cli = len(cli_df)
        n_ina = int((cli_df["n_atr"] > 0).sum())

        # ── KPIs ──
        ck1,ck2,ck3,ck4,ck5 = st.columns(5)
        ck1.metric("📋 Faturado",     brl(t_fat), f"{n_cli} clientes")
        ck2.metric("✅ Recebido",     brl(t_rec), f"{n_match} cobranças casadas")
        ck3.metric("🔴 Atrasado",     brl(t_atr), f"{n_ina} clientes inadimplentes",
                   delta_color="inverse")
        ck4.metric("🔵 A Vencer",     brl(t_av))
        ck5.metric("🔗 OFX não casado", brl(ofx_nc),
                   "cobranças de outros meses", delta_color="off")

        # Validação interna
        check = abs(t_rec + t_atr + t_av - t_fat)
        if check < 1:
            st.success(f"✅ Rec ({brl(t_rec)}) + Atrasado ({brl(t_atr)}) + A Vencer ({brl(t_av)}) = Faturado ({brl(t_fat)})")
        else:
            st.warning(f"⚠️ Diferença de {brl(check)} — verificar dados")

        # Nota explicativa sobre OFX não casado
        if ofx_nc > 0:
            st.info(
                f"ℹ️ O extrato tem **{brl(ofx_nc)} não casados** com cobranças de maio. "
                f"Esses são pagamentos de **meses anteriores** recebidos este mês — "
                f"contam no saldo bancário mas não em cobranças de maio."
            )

        st.markdown("---")

        # ── Gráfico barras por cliente (top 15) ──
        st.markdown("#### 📊 Top 15 Clientes por Faturamento")
        top15 = cli_df.head(15)
        fig_crz = go.Figure()
        fig_crz.add_trace(go.Bar(name="✅ Recebido", x=top15["cliente"].str[:30],
            y=top15["recebido"], marker_color="#22A85A"))
        fig_crz.add_trace(go.Bar(name="🔴 Atrasado", x=top15["cliente"].str[:30],
            y=top15["atrasado"], marker_color="#D93025"))
        fig_crz.add_trace(go.Bar(name="🔵 A Vencer", x=top15["cliente"].str[:30],
            y=top15["a_vencer"], marker_color="#1976D2"))
        fig_crz.update_layout(
            barmode="stack", height=380,
            plot_bgcolor="#111", paper_bgcolor="#111", font_color="#CCC",
            xaxis=dict(gridcolor="#222", tickangle=-35, tickfont=dict(size=10)),
            yaxis=dict(gridcolor="#222", tickprefix="R$ "),
            legend=dict(bgcolor="#1A1A1A", x=0, y=1.12, orientation="h"),
            margin=dict(t=30,b=100,l=80,r=20),
        )
        st.plotly_chart(fig_crz, use_container_width=True)

        st.markdown("---")

        # ── Filtros ──
        cf1,cf2,cf3 = st.columns([3,2,2])
        with cf1: busca_crz = st.text_input("🔍 Buscar cliente:", key="busca_crz")
        with cf2:
            filtro_sit = st.selectbox("Situação:", 
                ["Todos","Com Atrasado","Sem Pagamento","Totalmente Pago"], key="sit_crz")
        with cf3:
            ord_crz = st.selectbox("Ordenar:", 
                ["Faturado ↓","Atrasado ↓","A Vencer ↓","Recebido ↓"], key="ord_crz")

        df_show = cli_df.copy()
        if busca_crz:
            df_show = df_show[df_show["cliente"].str.lower().str.contains(busca_crz.lower(), na=False)]
        if filtro_sit == "Com Atrasado":      df_show = df_show[df_show["atrasado"] > 0]
        elif filtro_sit == "Sem Pagamento":   df_show = df_show[df_show["recebido"] == 0]
        elif filtro_sit == "Totalmente Pago": df_show = df_show[df_show["a_vencer"] == 0]
        if ord_crz == "Faturado ↓":   df_show = df_show.sort_values("faturado", ascending=False)
        elif ord_crz == "Atrasado ↓": df_show = df_show.sort_values("atrasado", ascending=False)
        elif ord_crz == "A Vencer ↓": df_show = df_show.sort_values("a_vencer", ascending=False)
        elif ord_crz == "Recebido ↓": df_show = df_show.sort_values("recebido", ascending=False)

        st.markdown(f"**{len(df_show)} clientes** · Total: {brl(df_show['faturado'].sum())}")

        # Tabela formatada
        def pct(rec, fat): return f"{round(rec/fat*100,1)}%" if fat>0 else "0%"
        def sit(row):
            if row["atrasado"] > 0 and row["recebido"] == 0: return "🔴 Inadimplente"
            if row["atrasado"] > 0: return "🟠 Parcial"
            if row["recebido"] > 0 and row["a_vencer"] == 0: return "✅ Pago"
            if row["recebido"] > 0: return "🟡 Parcial+OK"
            return "🔵 A Vencer"

        tab_rows = pd.DataFrame({
            "Cliente":     df_show["cliente"].str[:45],
            "Situação":    df_show.apply(sit, axis=1),
            "Faturado":    df_show["faturado"].apply(brl),
            "Recebido":    df_show["recebido"].apply(brl),
            "% Rec":       df_show.apply(lambda r: pct(r["recebido"],r["faturado"]), axis=1),
            "Atrasado":    df_show["atrasado"].apply(brl),
            "A Vencer":    df_show["a_vencer"].apply(brl),
            "Cobranças":   df_show["n_cob"].astype(int),
        })
        st.dataframe(tab_rows, use_container_width=True, hide_index=True,
                     height=min(38*len(df_show)+42, 540))

        st.markdown("---")

        # ── Seção Inadimplentes ──
        inad = cli_df[cli_df["atrasado"] > 0].sort_values("atrasado", ascending=False)
        if not inad.empty:
            st.markdown(f"#### 🚨 Inadimplentes — {len(inad)} clientes · {brl(inad['atrasado'].sum())}")
            inad_tab = pd.DataFrame({
                "#":           range(1, len(inad)+1),
                "Cliente":     inad["cliente"].str[:45],
                "Faturado":    inad["faturado"].apply(brl),
                "Atrasado":    inad["atrasado"].apply(brl),
                "Recebido":    inad["recebido"].apply(brl),
                "A Vencer":    inad["a_vencer"].apply(brl),
                "% Atraso":    inad.apply(lambda r: pct(r["atrasado"],r["faturado"]), axis=1),
            })
            st.dataframe(inad_tab, use_container_width=True, hide_index=True,
                        height=min(38*len(inad)+42, 420))

        # ── Seção A Vencer (maiores) ──
        st.markdown("---")
        av_tab = cli_df[cli_df["a_vencer"] > 0].sort_values("a_vencer", ascending=False).head(20)
        st.markdown(f"#### 🔵 Top 20 A Vencer — {brl(cli_df['a_vencer'].sum())}")
        av_rows = pd.DataFrame({
            "#":         range(1, len(av_tab)+1),
            "Cliente":   av_tab["cliente"].str[:45],
            "A Vencer":  av_tab["a_vencer"].apply(brl),
            "Faturado":  av_tab["faturado"].apply(brl),
            "Recebido":  av_tab["recebido"].apply(brl),
            "Cobranças": av_tab["n_av"].astype(int),
        })
        st.dataframe(av_rows, use_container_width=True, hide_index=True,
                     height=min(38*len(av_rows)+42, 420))


# ══════════════════════════════════════════════════════════════════════
# TAB 2 — POR CATEGORIA
# ══════════════════════════════════════════════════════════════════════
with tab_categ:
    st.markdown("### 📂 Contas a Pagar por Categoria")
    st.markdown("Visão consolidada de todos os compromissos agrupados por categoria, criticidade e status de pagamento.")

    # Monta dataset por categoria
    cat_rows = []
    for _, row in pag_df.iterrows():
        cat_rows.append({
            "__cat":    row["__cat"],
            "__crit":   row["__crit"],
            "__prio":   int(row["__prio"]),
            "__apagar": float(row["__apagar"]),
            "__forn":   row["__forn"],
            "__venc":   row["__venc"],
            "__status": row["__status_venc"],
        })
    df_cat = pd.DataFrame(cat_rows)

    # Agrupado por categoria
    grp = (
        df_cat.groupby(["__cat","__crit","__prio"])
        .agg(
            n=("__apagar","count"),
            total=("__apagar","sum"),
        )
        .reset_index()
        .sort_values(["__prio","total"], ascending=[True, False])
    )
    total_geral = df_cat["__apagar"].sum()

    # ── KPIs por criticidade ──
    crit_vals = df_cat.groupby("__prio")["__apagar"].sum()
    crit_n    = df_cat.groupby("__prio")["__apagar"].count()
    ck0,ck1,ck2,ck3 = st.columns(4)
    ck0.metric("🔴 CRÍTICO",  brl(crit_vals.get(0,0)),  f"{int(crit_n.get(0,0))} contas")
    ck1.metric("🟠 ALTA",     brl(crit_vals.get(1,0)),  f"{int(crit_n.get(1,0))} contas")
    ck2.metric("🟡 MÉDIA",    brl(crit_vals.get(2,0)),  f"{int(crit_n.get(2,0))} contas")
    ck3.metric("🟢 BAIXA",    brl(crit_vals.get(3,0)),  f"{int(crit_n.get(3,0))} contas")

    st.markdown("---")

    # ── Gráfico de barras horizontais por categoria ──
    grp_chart = grp.sort_values("total", ascending=True).tail(20)
    colors = grp_chart["__prio"].map({0:"#D93025",1:"#F05A22",2:"#D4A017",3:"#4CAF50"}).fillna("#888")

    fig_cat = go.Figure(go.Bar(
        y=grp_chart["__cat"],
        x=grp_chart["total"],
        orientation="h",
        marker_color=list(colors),
        text=[brl(v) for v in grp_chart["total"]],
        textposition="outside",
        textfont=dict(size=11, color="#CCC"),
    ))
    fig_cat.update_layout(
        height=max(320, len(grp_chart)*28),
        plot_bgcolor="#111", paper_bgcolor="#111",
        font_color="#CCC",
        xaxis=dict(gridcolor="#222", tickprefix="R$ ", title=""),
        yaxis=dict(gridcolor="#222", title=""),
        margin=dict(t=20,b=20,l=220,r=100),
        showlegend=False,
    )
    st.plotly_chart(fig_cat, use_container_width=True)

    # ── Pizza de distribuição ──
    st.markdown("#### 🥧 Distribuição por Criticidade")
    pizza_labels = ["🔴 CRÍTICO","🟠 ALTA","🟡 MÉDIA","🟢 BAIXA"]
    pizza_values = [float(crit_vals.get(i,0)) for i in range(4)]
    pizza_colors = ["#D93025","#F05A22","#D4A017","#4CAF50"]

    fig_pizza = go.Figure(go.Pie(
        labels=pizza_labels,
        values=pizza_values,
        marker_colors=pizza_colors,
        hole=0.55,
        textinfo="percent+label",
        textfont=dict(size=12),
    ))
    fig_pizza.update_layout(
        height=300,
        plot_bgcolor="#111", paper_bgcolor="#111",
        font_color="#CCC",
        margin=dict(t=20,b=20,l=20,r=20),
        showlegend=False,
        annotations=[dict(
            text=f"<b>{brl(total_geral)}</b>",
            x=0.5, y=0.5, font_size=13,
            font_color="#FFF", showarrow=False
        )]
    )
    st.plotly_chart(fig_pizza, use_container_width=True)

    # ── Tabela por categoria com expandir ──
    st.markdown("---")
    st.markdown("#### 📋 Detalhe por Categoria")

    # Filtro de criticidade
    filtro_crit = st.selectbox(
        "Filtrar por criticidade:",
        ["Todas","🔴 CRÍTICO","🟠 ALTA","🟡 MÉDIA","🟢 BAIXA"],
        key="filt_cat_crit"
    )
    filtro_prio = {"🔴 CRÍTICO":0,"🟠 ALTA":1,"🟡 MÉDIA":2,"🟢 BAIXA":3}.get(filtro_crit)

    grp_show = grp if filtro_prio is None else grp[grp["__prio"]==filtro_prio]

    for _, r in grp_show.iterrows():
        cat   = r["__cat"]
        crit  = r["__crit"]
        total = r["total"]
        n     = int(r["n"])
        pct   = round(total / total_geral * 100, 1)

        # Pega os detalhes desta categoria
        detalhes = df_cat[df_cat["__cat"]==cat].copy()
        atras = detalhes[detalhes["__status"]=="ATRASADO"]["__apagar"].sum()
        avenc = detalhes[detalhes["__status"]=="A VENCER"]["__apagar"].sum()

        with st.expander(
            f"{crit}  **{cat}**  ·  {brl(total)}  ·  {n} fornecedor{'es' if n>1 else ''}  ·  {pct}% do total",
            expanded=(r["__prio"]==0)  # CRÍTICO vem aberto
        ):
            # Mini KPIs dentro do expander
            ec1,ec2,ec3 = st.columns(3)
            ec1.metric("💸 A Pagar total",  brl(total))
            ec2.metric("🔴 Em atraso",      brl(atras))
            ec3.metric("⏳ A vencer",       brl(avenc))

            # Fornecedores desta categoria
            forn_grp = (
                pag_df[pag_df["__cat"]==cat]
                [["__forn","__apagar","__status_venc","__venc_str","__dias_atr","__motivo"]]
                .sort_values("__apagar", ascending=False)
                .copy()
            )
            forn_grp.columns = ["Fornecedor","A Pagar","Status","Vencimento","Dias Atr.","Motivo"]
            forn_grp["A Pagar"] = forn_grp["A Pagar"].apply(brl)
            forn_grp["Dias Atr."] = forn_grp["Dias Atr."].apply(lambda d: d if d>0 else "—")
            st.dataframe(
                forn_grp, use_container_width=True,
                hide_index=True,
                height=min(38*len(forn_grp)+42, 280)
            )

    st.markdown("---")
    # Tabela resumo completa
    st.markdown("#### 📊 Resumo Consolidado")
    resumo = pd.DataFrame({
        "Criticidade":    grp["__crit"],
        "Categoria":      grp["__cat"],
        "Fornecedores":   grp["n"].astype(int),
        "A Pagar":        grp["total"].apply(brl),
        "% do Total":     grp["total"].apply(lambda v: f"{round(v/total_geral*100,1)}%"),
    })
    st.dataframe(resumo, use_container_width=True, hide_index=True, height=600)


# ══════════════════════════════════════════════════════════════════════
# TAB 3 — LISTA COMPLETA
# ══════════════════════════════════════════════════════════════════════
with tab_lista:
    todos = []
    seq = 1
    for dia in a["dias"]:
        for it in dia["itens"]:
            todos.append({
                "#":            seq,
                "Status Pgto":  "✅ PAGO",
                "Data Prog.":   dia["data_str"],
                "Dia":          dia["dow_abr"],
                "Fornecedor":   it["forn"][:45],
                "Categoria":    it["cat"],
                "Criticidade":  it["crit"],
                "Status":       it["status"],
                "Vencim.":      it["venc_str"],
                "Dias Atr.":    it["dias_atr"] if it["dias_atr"] > 0 else "—",
                "Motivo":       it["motivo"],
                "Valor":        brl(it["val"]),
            })
            seq += 1
    for nc in a["nao_cobertos"]:
        todos.append({
            "#":            seq,
            "Status Pgto":  "❌ NÃO PAGO",
            "Data Prog.":   "—",
            "Dia":          "—",
            "Fornecedor":   nc["forn"][:45],
            "Categoria":    nc["cat"],
            "Criticidade":  nc["crit"],
            "Status":       nc["status"],
            "Vencim.":      nc["venc_str"],
            "Dias Atr.":    "—",
            "Motivo":       nc["motivo"],
            "Valor":        brl(nc["val"]),
        })
        seq += 1

    df_todos = pd.DataFrame(todos)
    n_pagos  = sum(1 for t in todos if t["Status Pgto"] == "✅ PAGO")
    n_npagos = len(todos) - n_pagos
    val_pago = sum(pv(t["Valor"]) for t in todos if t["Status Pgto"] == "✅ PAGO")
    val_np   = sum(pv(t["Valor"]) for t in todos if t["Status Pgto"] != "✅ PAGO")

    st.markdown(
        f"**Total: {len(todos)} contas — {brl(a['total_pagar'])}**  |  "
        f"Pagos: **{n_pagos}** ({brl(val_pago)})  |  "
        f"Não Pagos: **{n_npagos}** ({brl(val_np)})"
    )

    # Filtros
    f1, f2, f3 = st.columns(3)
    with f1: f_pgto = st.selectbox("Status Pgto", ["Todos","✅ PAGO","❌ NÃO PAGO"], key="f_pgto")
    with f2: f_crit = st.selectbox("Criticidade", ["Todos","🔴 CRÍTICO","🟠 ALTA","🟡 MÉDIA","🟢 BAIXA"], key="f_crit")
    with f3: f_busca= st.text_input("🔍 Buscar fornecedor", key="f_busca")

    df_show = df_todos.copy()
    if f_pgto != "Todos":  df_show = df_show[df_show["Status Pgto"] == f_pgto]
    if f_crit != "Todos":  df_show = df_show[df_show["Criticidade"] == f_crit]
    if f_busca:            df_show = df_show[df_show["Fornecedor"].str.lower().str.contains(f_busca.lower(), na=False)]

    st.dataframe(df_show, use_container_width=True, hide_index=True, height=540)

# ══════════════════════════════════════════════════════════════════════
# TAB 3 — NÃO COBERTOS
# ══════════════════════════════════════════════════════════════════════
with tab_nc:
    if not a["nao_cobertos"]:
        st.success("🎉 Todos os compromissos do período estão cobertos pelo caixa previsto!")
    else:
        st.error(
            f"**{a['n_nc']} contas** totalizando **{brl(a['total_nc'])}** "
            f"não cabem no caixa — precisam ser renegociadas."
        )

        nc_list = a["nao_cobertos"]
        nc_by_prio = {0:[], 1:[], 2:[], 3:[]}
        for nc in nc_list:
            nc_by_prio[nc["prio"]].append(nc)

        # KPIs por criticidade
        cp1,cp2,cp3,cp4 = st.columns(4)
        def _nc_sum(lst): return sum(n["val"] for n in lst)
        cp1.metric("🔴 CRÍTICO",  brl(_nc_sum(nc_by_prio[0])), f"{len(nc_by_prio[0])} contas", delta_color="inverse")
        cp2.metric("🟠 ALTA",     brl(_nc_sum(nc_by_prio[1])), f"{len(nc_by_prio[1])} contas", delta_color="inverse")
        cp3.metric("🟡 MÉDIA",    brl(_nc_sum(nc_by_prio[2])), f"{len(nc_by_prio[2])} contas", delta_color="off")
        cp4.metric("🟢 BAIXA",    brl(_nc_sum(nc_by_prio[3])), f"{len(nc_by_prio[3])} contas", delta_color="off")

        st.markdown("")

        # Tabela completa
        nc_rows = []
        for i, nc in enumerate(nc_list, 1):
            nc_rows.append({
                "#":                  i,
                "Fornecedor":         nc["forn"][:45],
                "Categoria":          nc["cat"],
                "Vencimento":         nc["venc_str"],
                "Status":             nc["status"],
                "Criticidade":        nc["crit"],
                "Valor":              brl(nc["val"]),
                "Ação Recomendada":   nc["acao"],
            })
        st.dataframe(pd.DataFrame(nc_rows), use_container_width=True,
                     hide_index=True, height=500)

        # Seção por criticidade
        if nc_by_prio[0]:
            st.markdown("#### 🔴 CRÍTICOS — AÇÃO IMEDIATA")
            for nc in nc_by_prio[0]:
                st.markdown(
                    f"- **{nc['forn']}** · {nc['cat']} · {brl(nc['val'])} · "
                    f"Venc. {nc['venc_str']} · {nc['acao']}"
                )

# ══════════════════════════════════════════════════════════════════════
# TAB HUBSOFT — INTEGRAÇÃO AO VIVO
# ══════════════════════════════════════════════════════════════════════
# ── Diagnóstico embutido (fallback quando hubsoft_api.py antigo) ─────
def _diagnostico_embutido(hub_url, cid, csec, user, pwd, mes="2026-05"):
    import requests as _rq2
    resultado = {"auth": {}, "rest": [], "graphql": {}}
    body = {"grant_type":"password","client_id":cid,"client_secret":csec,
            "username":user,"password":pwd}
    tok = None
    base = hub_url.rstrip("/")
    for path in ["/oauth/token","/api/oauth/token"]:
        try:
            r = _rq2.post(f"{base}{path}", data=body,
                          headers={"Content-Type":"application/x-www-form-urlencoded",
                                   "Accept":"application/json"}, timeout=10)
            if r.status_code == 200 and "access_token" in r.text:
                tok = r.json().get("access_token","")
                resultado["auth"] = {"ok":True,"path":path,"base":base,"token":tok[:20]+"..."}
                break
        except: pass
    if not tok:
        resultado["auth"] = {"ok":False,"erro":"falha de autenticação"}
        return resultado

    s2 = _rq2.Session()
    s2.headers.update({"Authorization":f"Bearer {tok}","Accept":"application/json"})
    d_ini, d_fim = f"{mes}-01", f"{mes}-31"
    eps = [
        ("/api/v1/integracao/financeiro/fatura","venc",
         {"pagina":0,"itens_por_pagina":1,"data_vencimento_ini":d_ini,"data_vencimento_fim":d_fim}),
        ("/api/v1/integracao/financeiro","venc",
         {"pagina":0,"itens_por_pagina":1,"data_vencimento_ini":d_ini,"data_vencimento_fim":d_fim}),
        ("/api/v1/integracao/cliente/financeiro","venc",
         {"pagina":0,"itens_por_pagina":1,"data_vencimento_ini":d_ini,"data_vencimento_fim":d_fim}),
        ("/api/v1/integracao/cliente/financeiro","inicio/fim",
         {"pagina":0,"itens_por_pagina":1,"data_inicio":d_ini,"data_fim":d_fim}),
        ("/api/v1/integracao/cliente/financeiro","de/ate",
         {"pagina":0,"itens_por_pagina":1,"de":d_ini,"ate":d_fim}),
        ("/api/v1/integracao/cliente/financeiro","sem_data",
         {"pagina":0,"itens_por_pagina":1}),
        ("/api/v1/integracao/cliente","sem_data",{"pagina":0,"itens_por_pagina":1}),
    ]
    for ep, plabel, params in eps:
        try:
            r2 = s2.get(f"{base}{ep}", params=params, timeout=10)
            total=""; keys=""
            try:
                d2 = r2.json()
                pag = d2.get("paginacao",{})
                total = str(pag.get("total_registros","—"))
                keys  = str(list(d2.keys()))[:70]
            except: keys = r2.text[:50]
            resultado["rest"].append({"Endpoint":ep,"Params":plabel,
                "Status":r2.status_code,"Total":total,"Keys":keys,"OK":r2.status_code==200})
        except Exception as ex:
            resultado["rest"].append({"Endpoint":ep,"Params":plabel,
                "Status":"Err","Total":"","Keys":str(ex)[:50],"OK":False})

    # GraphQL
    try:
        rg = s2.post(f"{base}/graphql/v1", json={"query":"""{
          __schema {
            queryType{fields{name args{name}}}
            types{name fields{name}}
          }
        }"""}, timeout=15)
        if rg.status_code == 200:
            sch = rg.json().get("data",{}).get("__schema",{})
            if sch:
                all_q = [f["name"] for f in sch.get("queryType",{}).get("fields",[])]
                fin_q = {f["name"]:[a["name"] for a in f.get("args",[])]
                         for f in sch.get("queryType",{}).get("fields",[])
                         if any(x in f["name"].lower() for x in ["cobran","fatura","financ"])}
                cob_t = {t["name"]:[f["name"] for f in t.get("fields",[])]
                         for t in sch.get("types",[])
                         if any(x in t["name"].lower() for x in ["cobran","fatura"])
                         and not t["name"].startswith("_") and t.get("fields")}
                resultado["graphql"] = {"ok":True,"all_queries":all_q,
                                        "fin_queries":fin_q,"types":cob_t}
            else:
                resultado["graphql"] = {"ok":False,"resp":str(rg.json())[:200]}
        else:
            resultado["graphql"] = {"ok":False,"status":rg.status_code}
    except Exception as ge:
        resultado["graphql"] = {"ok":False,"erro":str(ge)}
    return resultado


with tab_hub:
    st.markdown("### 🔗 Integração Hubsoft — Dados ao Vivo")

    if not _HAS_HUB:
        st.warning("⚠️ Módulo `hubsoft_api.py` não encontrado no repositório.")
        st.code("Coloque hubsoft_api.py no mesmo diretório do app.py", language="bash")
    else:
        def _gs(k, d=""):
            try: return st.secrets.get(k, d)
            except: return d

        hub_url  = _gs("HUBSOFT_URL",           "https://api.jettelecom.hubsoft.com.br")
        hub_cid  = _gs("HUBSOFT_CLIENT_ID",     "147")
        hub_csec = _gs("HUBSOFT_CLIENT_SECRET", "")
        hub_user = _gs("HUBSOFT_USERNAME",      "")
        hub_pass = _gs("HUBSOFT_PASSWORD",      "")

        # Mostra erro de auto-load se existir
        if st.session_state.get("hub_erro"):
            st.error("❌ Erro na conexão com o Hubsoft:")
            st.code(st.session_state["hub_erro"], language="text")
            st.markdown("""
**Possíveis causas e soluções:**

| Erro | Causa | Solução |
|---|---|---|
| `405 Not Allowed` | Formato de auth errado | Atualizar `hubsoft_api.py` |
| `401 Unauthorized` | Credenciais inválidas | Verificar senha/client_secret |
| `404 Not Found` | URL ou endpoint errado | Verificar `HUBSOFT_URL` |
| `ConnectionError` | Servidor bloqueando IP | Contatar suporte Hubsoft |
| `SSL Error` | Certificado inválido | Adicionar `verify=False` |
""")

        # Credenciais
        cred_ok = all([hub_url, hub_cid, hub_csec, hub_user, hub_pass])
        if not cred_ok:
            with st.expander("⚙️ Configurar credenciais", expanded=True):
                c1, c2 = st.columns(2)
                with c1:
                    hub_url  = st.text_input("URL", value=hub_url or "https://api.jettelecom.hubsoft.com.br", key="h_url")
                    hub_cid  = st.text_input("Client ID", value=hub_cid, key="h_cid")
                    hub_csec = st.text_input("Client Secret", value="", type="password", key="h_csec")
                with c2:
                    hub_user = st.text_input("Usuário (e-mail)", value="", key="h_user")
                    hub_pass = st.text_input("Senha", value="", type="password", key="h_pass")
            cred_ok = all([hub_url, hub_cid, hub_csec, hub_user, hub_pass])

        from datetime import datetime as _dt
        hub_mes = st.text_input("📅 Mês (YYYY-MM):",
                                value=_dt.now().strftime("%Y-%m"), key="hub_mes")

        hb1, hb2, hb3 = st.columns(3)
        with hb1: btn_hub   = st.button("🔄 Buscar dados", type="primary", key="btn_hub")
        with hb2: btn_diag  = st.button("🔍 Diagnóstico de conexão", key="btn_diag")
        with hb3:
            if st.button("🗑️ Limpar cache", key="btn_hub_clear"):
                st.cache_data.clear()
                for k in ["hub_erro","hub_dados"]:
                    st.session_state.pop(k, None)
                st.rerun()

        # DIAGNÓSTICO COMPLETO
        if btn_diag and cred_ok:
            st.markdown("#### 🔍 Diagnóstico Completo de Conexão")
            with st.spinner("Testando todos os endpoints..."):
                try:
                    import importlib, hubsoft_api as _hub_mod
                    importlib.reload(_hub_mod)
                    if hasattr(_hub_mod, "diagnosticar"):
                        diag = _hub_mod.diagnosticar(hub_url, hub_cid, hub_csec,
                                                      hub_user, hub_pass, hub_mes)
                    else:
                        # Fallback: diagnóstico embutido
                        diag = _diagnostico_embutido(
                            hub_url, hub_cid, hub_csec, hub_user, hub_pass, hub_mes)
                except Exception as de:
                    st.warning(f"Módulo antigo — usando diagnóstico embutido: {de!s:.80}")
                    diag = _diagnostico_embutido(
                        hub_url, hub_cid, hub_csec, hub_user, hub_pass, hub_mes)

            # Auth
            auth = diag.get("auth",{})
            if auth.get("ok"):
                st.success(f"✅ Autenticado via `{auth.get('path')}` — base: `{auth.get('base')}`")
            else:
                st.error(f"❌ Falha: {auth.get('erro','')}")

            # REST
            rest = diag.get("rest",[])
            if rest:
                import pandas as _pd2
                df_rest = _pd2.DataFrame(rest)
                st.markdown("**Endpoints REST:**")
                st.dataframe(df_rest, use_container_width=True, hide_index=True, height=450)
                ok_rest = [r for r in rest if r["OK"]]
                if ok_rest:
                    st.success(f"✅ {len(ok_rest)} endpoints disponíveis:")
                    for r in ok_rest:
                        st.code(f"{r['Endpoint']}  →  total={r['Total']}")

            # GraphQL
            gql = diag.get("graphql",{})
            st.markdown("**API GraphQL:**")
            if gql.get("ok"):
                st.success("✅ GraphQL disponível!")
                fin_q = gql.get("fin_queries",{})
                if fin_q:
                    st.markdown("**Queries financeiras e argumentos:**")
                    for qname, qargs in fin_q.items():
                        st.code(f"{qname}({', '.join(qargs)})")
                else:
                    st.markdown("**Todas as queries:**")
                    st.code(str(gql.get("all_queries",[])))
                types = gql.get("types",{})
                for tname, tfields in types.items():
                    st.markdown(f"**Tipo `{tname}` — campos:**")
                    st.code(str(tfields))
            else:
                st.warning(f"GraphQL: {gql.get('erro') or gql.get('resp') or gql.get('status','indisponível')}")


        if not cred_ok:
            st.warning("Preencha as credenciais acima.")
        elif btn_hub or st.session_state.get("hub_dados"):
            @st.cache_data(ttl=300, show_spinner=False)
            def _hub_fetch(url, cid, csec, user, pwd, mes):
                hub = HubsoftAPI(url, cid, csec, user, pwd)
                hub.autenticar()
                return hub.importar_tudo(mes), hub.cruzamento_clientes(mes=mes)

            with st.spinner("🔄 Conectando ao Hubsoft..."):
                try:
                    _hub_resultado, cli_df = _hub_fetch(
                        hub_url, hub_cid, hub_csec, hub_user, hub_pass, hub_mes
                    )
                    st.session_state["hub_dados"] = True
                    st.session_state.pop("hub_erro", None)
                    st.success(f"✅ Hubsoft conectado — {hub_mes}")
                    fin = _hub_resultado
                except Exception as e:
                    st.error(f"❌ Erro: {e}")
                    st.code(str(e), language="text")
                    st.session_state["hub_erro"] = str(e)
                    fin, cli_df = {}, pd.DataFrame()

            totais = fin.get("totais", {})
            if totais:
                # KPIs
                hk1,hk2,hk3,hk4,hk5 = st.columns(5)
                hk1.metric("📋 Faturado",  brl(totais["faturado"]),   f"{totais['n_cobrancas']} cobranças")
                hk2.metric("✅ Recebido",  brl(totais["recebido"]),   f"{totais['adimplencia']}% adimplência")
                hk3.metric("🔴 Atrasado",  brl(totais["atrasado"]),   f"{totais['n_atrasadas']} cobranças", delta_color="inverse")
                hk4.metric("🔵 A Vencer",  brl(totais["a_vencer"]),   f"{totais['n_a_vencer']} cobranças")
                hk5.metric("📈 A Receber", brl(totais["atrasado"]+totais["a_vencer"]))

                st.markdown("---")

                ht1,ht2,ht3,ht4 = st.tabs([
                    f"👥 Clientes ({len(cli_df)})",
                    f"✅ Pagas ({totais['n_pagas']})",
                    f"🔴 Atrasadas ({totais['n_atrasadas']})",
                    f"🔵 A Vencer ({totais['n_a_vencer']})",
                ])

                with ht1:
                    if not cli_df.empty:
                        hb1,hb2 = st.columns([3,2])
                        with hb1: hbusca = st.text_input("🔍 Buscar:", key="hub_busca")
                        with hb2: hfilt  = st.selectbox("Filtrar:", ["Todos","Com Atrasado","Sem Pagamento"], key="hub_filt")
                        df_s = cli_df.copy()
                        if hbusca: df_s = df_s[df_s["nome_cliente"].str.lower().str.contains(hbusca.lower(),na=False)]
                        if hfilt=="Com Atrasado":    df_s = df_s[df_s["atrasado"]>0]
                        elif hfilt=="Sem Pagamento": df_s = df_s[df_s["recebido"]==0]
                        st.dataframe(pd.DataFrame({
                            "Cliente":   df_s["nome_cliente"].str[:45],
                            "Faturado":  df_s["faturado"].apply(brl),
                            "Recebido":  df_s["recebido"].apply(brl),
                            "Atrasado":  df_s["atrasado"].apply(brl),
                            "A Vencer":  df_s["a_vencer"].apply(brl),
                            "Adimpl.%":  df_s["adimplencia_pct"].apply(lambda v:f"{v:.1f}%"),
                            "Cobranças": df_s["n_cob"].astype(int),
                        }), use_container_width=True, hide_index=True, height=500)

                def _render_df_cobrancas(df_c, key_sfx):
                    if df_c.empty: return
                    cols=[c for c in ["nome_cliente","valor","data_vencimento","data_pagamento","dias_atraso","descricao"] if c in df_c.columns]
                    d2=df_c[cols].copy()
                    for dc in ["data_vencimento","data_pagamento"]:
                        if dc in d2.columns: d2[dc]=d2[dc].dt.strftime("%d/%m/%Y")
                    if "valor" in d2.columns: d2["valor"]=df_c["valor"].apply(brl)
                    st.dataframe(d2, use_container_width=True, hide_index=True, height=460)

                with ht2: _render_df_cobrancas(fin.get("pagas",pd.DataFrame()), "p")
                with ht3: _render_df_cobrancas(fin.get("atrasadas",pd.DataFrame()).sort_values("dias_atraso",ascending=False) if "dias_atraso" in fin.get("atrasadas",pd.DataFrame()).columns else fin.get("atrasadas",pd.DataFrame()), "a")
                with ht4: _render_df_cobrancas(fin.get("a_vencer",pd.DataFrame()), "v")

                # Exportar
                st.markdown("---")
                cobrancas_all = fin.get("cobrancas", pd.DataFrame())
                if not cobrancas_all.empty:
                    import io as _io
                    buf = _io.BytesIO()
                    with pd.ExcelWriter(buf, engine="xlsxwriter") as wr:
                        cobrancas_all.to_excel(wr, sheet_name="Cobranças", index=False)
                        if not cli_df.empty: cli_df.to_excel(wr, sheet_name="Clientes", index=False)
                    buf.seek(0)
                    st.download_button("📥 Exportar Excel", buf,
                        f"hubsoft_{hub_mes}.xlsx",
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True, key="hub_export")


# ══════════════════════════════════════════════════════════════════════
# TAB 4 — MAXWELL CFO IA
# ══════════════════════════════════════════════════════════════════════
with tab_maxwell:
    st.markdown("### 🤖 Maxwell — CFO Inteligente")
    st.markdown("Análise automática do fluxo de caixa com recomendações estratégicas.")

    if not api_key:
        st.info("🔑 Insira sua chave API Anthropic na barra lateral para ativar o Maxwell.")
    else:
        col_m1, col_m2 = st.columns(2)
        with col_m1:
            if st.button("📊 Análise Completa do Caixa", type="primary", use_container_width=True):
                nc_criticos = [n for n in a["nao_cobertos"] if n["prio"] == 0]
                dias_crit_str = ", ".join(
                    d["data_str"] for d in a["dias"]
                    if d["status_dia"] in ("🔴 CRÍTICO","🚨 NEGATIVO") and not d["fim_semana"]
                )
                with st.spinner("Maxwell analisando..."):
                    resp = maxwell(
                        f"AGENDA DE CAIXA GRUPO JET — {data_ini_ts.strftime('%d/%m')} a {data_fim_ts.strftime('%d/%m/%Y')}\n"
                        f"Caixa inicial: {brl(caixa_ini)} | "
                        f"Entradas esperadas: {brl(a['total_rec_esp'])} | "
                        f"Compromissos: {brl(a['total_pagar'])} ({a['n_pend']} contas)\n"
                        f"GAP: {brl(abs(a['gap']))} ({'DÉFICIT' if a['gap']<0 else 'SUPERÁVIT'})\n"
                        f"Cobertos: {brl(a['total_coberto'])} ({a['n_cobertos']} contas — {a['pct_coberto']}%) | "
                        f"Não cobertos: {brl(a['total_nc'])} ({a['n_nc']} contas)\n"
                        f"Saldo final: {brl(a['saldo_final'])} | "
                        f"Dias críticos: {a['n_dias_crit']} ({dias_crit_str})\n"
                        f"CRÍTICOS não cobertos: {', '.join(n['forn'][:30] for n in nc_criticos[:5]) or 'nenhum'}\n"
                        "Faça diagnóstico completo, estratégia de cobrança e ações para cobrir o déficit.",
                        api_key, max_tokens=1200
                    )
                st.markdown(f'<div class="insight">{resp.replace(chr(10),"<br>")}</div>', unsafe_allow_html=True)

        with col_m2:
            if st.button("🚨 Estratégia para Não Cobertos", use_container_width=True):
                nc_str = "\n".join(
                    f"- {n['forn'][:35]} | {n['cat']} | {brl(n['val'])} | {n['crit']}"
                    for n in a["nao_cobertos"][:15]
                )
                with st.spinner("Analisando não cobertos..."):
                    resp = maxwell(
                        f"Tenho {a['n_nc']} contas NÃO COBERTAS pelo caixa — {brl(a['total_nc'])}:\n{nc_str}\n"
                        f"Déficit total: {brl(abs(a['gap']))}\n"
                        "Crie estratégia detalhada: quais renegociar, como abordar, prazos sugeridos, "
                        "fontes alternativas de caixa.",
                        api_key, max_tokens=1000
                    )
                st.markdown(f'<div class="insight">{resp.replace(chr(10),"<br>")}</div>', unsafe_allow_html=True)

        # Chat livre
        st.markdown("---")
        st.markdown("#### 💬 Pergunta livre ao Maxwell")
        pergunta = st.text_area("Digite sua pergunta sobre o fluxo de caixa:", height=100)
        if st.button("Enviar", key="btn_chat"):
            if pergunta.strip():
                ctx = (
                    f"Contexto da agenda: Caixa {brl(caixa_ini)}, "
                    f"Compromissos {brl(a['total_pagar'])}, "
                    f"Entradas esperadas {brl(a['total_rec_esp'])}, "
                    f"GAP {brl(abs(a['gap']))} {'déficit' if a['gap']<0 else 'superávit'}, "
                    f"Saldo final {brl(a['saldo_final'])}. "
                    f"Pergunta: {pergunta}"
                )
                with st.spinner("Maxwell respondendo..."):
                    resp = maxwell(ctx, api_key)
                st.markdown(f'<div class="insight">{resp.replace(chr(10),"<br>")}</div>', unsafe_allow_html=True)