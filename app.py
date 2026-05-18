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
    """Parse de valor monetário (aceita BR e US)."""
    if v is None: return 0.0
    if isinstance(v, (int, float)): return abs(float(v))
    s = str(v).strip().replace("R$","").replace("$","").replace(" ","")
    if s in ("","-","nan","None","null","—"): return 0.0
    try:
        hd = "." in s; hc = "," in s
        if hd and hc:
            s = s.replace(",","") if s.rfind(".")>s.rfind(",") else s.replace(".","").replace(",",".")
        elif hc and not hd:
            p = s.split(",")
            s = s.replace(",",".") if len(p)==2 and len(p[1])<=2 else s.replace(",","")
        elif hd and not hc:
            p = s.split(".")
            if not (len(p)==2 and len(p[1])<=2): s = s.replace(".","")
        return abs(float(s))
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

    return df[(df["__val"] > 0) & (~df["__pago"]) & df["__venc"].notna()].copy()


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
            for enc in ["utf-8","latin-1","cp1252"]:
                try: df = pd.read_csv(uploaded, dtype=str, encoding=enc); break
                except: uploaded.seek(0)
        else:
            df = pd.read_excel(uploaded, dtype=str)
    except Exception as e:
        st.error(f"Erro ao ler arquivo: {e}"); return pd.DataFrame()

    if df.empty: return pd.DataFrame()

    col_pag  = dcol(df,"pagante","cliente","nome","razao","pagador","payer","description","memo","descricao")
    col_val  = dcol(df,"valor","value","amount","recebido","credito","entrada")
    col_data = dcol(df,"data","date","data_pagamento","datapagamento","dt","when")

    if not col_val: return pd.DataFrame()

    df["__pagante"] = df[col_pag].fillna("").astype(str).str.strip() if col_pag else "Não identificado"
    df["__val"]     = df[col_val].apply(pv)
    df["__data"]    = parse_date(df[col_data]) if col_data else pd.NaT
    df["__memo"]    = df["__pagante"]

    return df[df["__val"] > 0].copy()


# ══════════════════════════════════════════════════════════════════════
# ALGORITMO DE AGENDA
# ══════════════════════════════════════════════════════════════════════
def gerar_agenda(pag_df: pd.DataFrame, rec_df: pd.DataFrame,
                 caixa_inicial: float, data_ini: pd.Timestamp,
                 dias_horizonte: int) -> dict:
    """
    Algoritmo principal: distribui pagamentos dia a dia conforme entradas.
    Retorna dict com resultado_dias, nao_cobertos, totais.
    """
    data_fim = data_ini + pd.Timedelta(days=dias_horizonte - 1)
    hoje     = pd.Timestamp.now().normalize()

    # Recebimentos por dia
    rec_por_dia = {}
    n_rec_dia   = {}
    if not rec_df.empty:
        rec_periodo = rec_df[
            (rec_df["__venc"] >= data_ini) &
            (rec_df["__venc"] <= data_fim)
        ]
        for _, r in rec_periodo.iterrows():
            d = r["__venc"].normalize()
            rec_por_dia[d] = rec_por_dia.get(d, 0.0) + r["__val"]
            n_rec_dia[d]   = n_rec_dia.get(d, 0)    + 1

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
    try:
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model="claude-opus-4-5",
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
        return f"Erro na IA: {e}"


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
    up_receber = st.file_uploader(
        "📥 Faturamento / A Receber (xlsx/csv)",
        type=["xlsx","xls","csv"],
        key="up_receber",
        help="Planilha Hubsoft com nome_razaosocial, valor, data_vencimento"
    )

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
        min_value=0.0, value=0.0, step=500.0, format="%.2f"
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
    api_key = st.text_input("Chave API Anthropic", type="password", key="api_key")

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

data_ini_ts = pd.Timestamp(data_ini_input)

if not pag_df.empty:
    with st.spinner("Calculando agenda de caixa..."):
        agenda = gerar_agenda(pag_df, rec_df, caixa_ini, data_ini_ts, int(dias_hor))

# ══════════════════════════════════════════════════════════════════════
# TELA INICIAL — sem dados
# ══════════════════════════════════════════════════════════════════════
if pag_df.empty:
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
    st.info("👈 **Comece importando a planilha de Contas a Pagar** na barra lateral.")
    st.stop()

# ══════════════════════════════════════════════════════════════════════
# STATUS DAS PLANILHAS
# ══════════════════════════════════════════════════════════════════════
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

# Linha 1 — visão geral
k1,k2,k3,k4,k5 = st.columns(5)
rec_total  = rec_df["__val"].sum() if not rec_df.empty else 0
rec_pago   = rec_df.loc[rec_df["__pago"], "__val"].sum() if not rec_df.empty else 0 if "__pago" in rec_df.columns else 0
rec_arec   = rec_total - rec_pago

k1.metric("💰 Faturado",   brl(rec_total))
k2.metric("✅ Recebido",   brl(rec_pago))
k3.metric("📊 A Receber",  brl(a["total_rec_esp"]))
k4.metric("💸 A Pagar",    brl(pag_df["__apagar"].sum()))
k5.metric("💵 Caixa Hoje", brl(caixa_ini))

st.markdown("---")

# Detalhamento A Pagar / A Receber
col_det1, col_det2 = st.columns(2)
with col_det1:
    st.markdown(f"**💸 Detalhamento A Pagar — {brl(pag_df['__apagar'].sum())}**")
    hoje_ts = pd.Timestamp.now().normalize()
    atras_pag = pag_df[pag_df["__status_venc"]=="ATRASADO"]["__apagar"].sum()
    avent_pag = pag_df[pag_df["__status_venc"]=="A VENCER"]["__apagar"].sum()
    da1,da2 = st.columns(2)
    da1.metric("🔴 Em Atraso",        brl(atras_pag))
    da2.metric("⏳ A Vencer (período)", brl(avent_pag))

with col_det2:
    st.markdown(f"**📥 Detalhamento A Receber — {brl(a['total_rec_esp'])}**")
    if not rec_df.empty:
        rec_inad = rec_df[
            rec_df["__venc"].apply(lambda d: pd.notna(d) and d < hoje_ts)
        ]["__val"].sum() if "__venc" in rec_df.columns else 0
        rec_normal = a["total_rec_esp"] - rec_inad
        db1,db2 = st.columns(2)
        db1.metric("🚨 Inadimplentes", brl(rec_inad))
        db2.metric("⏳ A Vencer",      brl(rec_normal))
    else:
        st.info("Sem planilha de recebimentos")

st.markdown("---")

# Análise dos próximos N dias
st.markdown(f"#### 📌 Análise dos Próximos {int(dias_hor)} Dias")
an1,an2,an3 = st.columns(3)
an1.metric("💸 Compromissos do período",   brl(a["total_pagar"]),    f"{a['n_pend']} contas")
an2.metric("📥 Entradas esperadas",        brl(a["total_rec_esp"]),  "Vencimentos 100%")
an3.metric("⚖️ GAP (Entradas − Compromissos)",
           brl(abs(a["gap"])),
           "DÉFICIT" if a["gap"] < 0 else "SUPERÁVIT",
           delta_color="inverse" if a["gap"] < 0 else "normal")

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
- Caixa atual: **{brl(caixa_ini)}**
- A pagar TOTAL: **{brl(pag_df['__apagar'].sum())}**
- A receber TOTAL: **{brl(a['total_rec_esp'])}**

**📊 NESTES {int(dias_hor)} DIAS:**
- Compromissos do período: **{brl(a['total_pagar'])}** ({a['n_pend']} contas)
- Entradas esperadas: **{brl(a['total_rec_esp'])}**
- GAP: **{brl(abs(a['gap']))}** ({'DÉFICIT 🔴' if a['gap']<0 else 'SUPERÁVIT ✅'})

**✅ RESULTADO DA AGENDA:**
- Pagamentos COBERTOS: **{brl(a['total_coberto'])}** ({a['n_cobertos']} contas — {a['pct_coberto']}%)
- Pagamentos NÃO COBERTOS: **{brl(a['total_nc'])}** ({a['n_nc']} contas — {round(a['n_nc']/max(a['n_pend'],1)*100,1)}%)
- Saldo final: **{brl(a['saldo_final'])}**

**🚨 AÇÕES OBRIGATÓRIAS:**
1. RENEGOCIAR prazo de **{a['n_nc']} contas** que não cabem no caixa *(ver aba ⚠️ Não Cobertos)*
2. COBRANÇA ATIVA dos inadimplentes para cobrir o gap de **{brl(abs(a['gap']))}**
3. Primeira semana é {'CRÍTICA ⚠️' if a['n_dias_crit']>3 else 'monitorada'} — **{a['n_dias_crit']} dias** com saldo < R$ 500
""")

# ══════════════════════════════════════════════════════════════════════
# TABS — as 3 abas restantes da planilha
# ══════════════════════════════════════════════════════════════════════
st.markdown("---")
_n_rec = len(rec_df_recebidos) if not rec_df_recebidos.empty else 0
_v_rec = rec_df_recebidos["__val"].sum() if not rec_df_recebidos.empty else 0.0
tab_agenda, tab_recebidos, tab_categ, tab_lista, tab_nc, tab_maxwell = st.tabs([
    "📅 Agenda Detalhada",
    f"✅ Já Recebidos ({_n_rec}) — {brl(_v_rec)}",
    "📂 Por Categoria",
    f"📋 Lista Completa ({a['n_pend']})",
    f"⚠️ Não Cobertos ({a['n_nc']}) — {brl(a['total_nc'])}",
    "🤖 Maxwell CFO",
])

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
        kr1, kr2, kr3, kr4 = st.columns(4)
        kr1.metric("✅ Total recebido",   brl(total_rec), f"{n_rec} pagamentos")
        kr2.metric("📋 Faturado (hub)",   brl(rec_df["__val"].sum() if not rec_df.empty else 0))
        pct_rec = round(total_rec / max(rec_df["__val"].sum() if not rec_df.empty else 1, 1) * 100, 1)
        kr3.metric("📊 Adimplência",      f"{pct_rec}%", "do faturado")
        a_receber = max((rec_df["__val"].sum() if not rec_df.empty else 0) - total_rec, 0)
        kr4.metric("🔵 Ainda a receber",  brl(a_receber))

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
