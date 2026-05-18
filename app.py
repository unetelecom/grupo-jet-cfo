import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import anthropic
import json
import io
from datetime import datetime, date, timedelta

# ── PAGE CONFIG ──
st.set_page_config(
    page_title="CFO IA · Grupo Jet",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── GLOBAL STYLE ──
st.markdown("""
<style>
@import url('https://cdn.jsdelivr.net/npm/@tabler/icons-webfont@2.47.0/tabler-icons.min.css');

/* Oculta menu padrão do Streamlit */
#MainMenu, footer, header {visibility: hidden;}
.block-container {padding-top: 1.2rem; padding-bottom: 1rem;}

/* Topbar logo */
.jet-header {
    background: linear-gradient(90deg, #141414 0%, #1E1E1E 100%);
    border-radius: 12px;
    padding: 14px 22px;
    display: flex;
    align-items: center;
    gap: 14px;
    margin-bottom: 18px;
    border: 0.5px solid #2A2A2A;
}
.jet-logo-box {
    width: 38px; height: 38px;
    background: #F05A22;
    border-radius: 9px;
    display: flex; align-items: center; justify-content: center;
    font-size: 20px; font-weight: 900; color: white;
    flex-shrink: 0;
}
.jet-header-title { color: #fff; font-size: 16px; font-weight: 700; margin: 0; }
.jet-header-sub { color: #666; font-size: 11px; margin: 0; }
.jet-header-right { margin-left: auto; display: flex; gap: 10px; align-items: center; }
.online-dot {
    width: 8px; height: 8px; border-radius: 50%;
    background: #22A85A; display: inline-block;
    animation: pulse 2s infinite;
}
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.4} }
.hs-badge {
    background: #1a3a0a; color: #22A85A;
    border: 0.5px solid #2a6a1a;
    border-radius: 20px; padding: 4px 12px;
    font-size: 11px; font-weight: 600;
    display: inline-flex; align-items: center; gap: 5px;
}

/* KPI cards */
.kpi-card {
    background: white;
    border-radius: 10px;
    border: 0.5px solid #E5E1DC;
    padding: 14px 16px;
    text-align: left;
}
.kpi-label { font-size: 10px; color: #6E6E6E; text-transform: uppercase; letter-spacing: .05em; margin-bottom: 6px; }
.kpi-value { font-size: 24px; font-weight: 800; color: #141414; line-height: 1.1; }
.kpi-delta { font-size: 11px; margin-top: 5px; }
.kpi-delta.pos { color: #22A85A; }
.kpi-delta.neg { color: #D93025; }
.kpi-delta.warn { color: #D97706; }

/* Pill badges */
.pill { display: inline-block; padding: 2px 10px; border-radius: 20px; font-size: 11px; font-weight: 600; }
.pill-ok  { background: #E5F7ED; color: #0A5C2E; }
.pill-er  { background: #FDECEB; color: #8B1A1A; }
.pill-wa  { background: #FEF3CD; color: #7A4F00; }
.pill-bl  { background: #E6F2FB; color: #1A3F8A; }
.pill-gr  { background: #F0EDE8; color: #555555; }

/* Insight box */
.insight-box {
    border-left: 3px solid #F05A22;
    background: #FFF5F0;
    padding: 12px 16px;
    border-radius: 0 8px 8px 0;
    font-size: 13px;
    line-height: 1.75;
    color: #141414;
    margin: 10px 0;
}

/* Chat bubbles */
.chat-user {
    background: #F05A22; color: white;
    border-radius: 12px 4px 12px 12px;
    padding: 10px 14px; font-size: 13px; line-height: 1.6;
    max-width: 80%; margin-left: auto;
    margin-bottom: 8px;
}
.chat-ai {
    background: white; color: #141414;
    border: 0.5px solid #E5E1DC;
    border-radius: 4px 12px 12px 12px;
    padding: 10px 14px; font-size: 13px; line-height: 1.6;
    max-width: 85%;
    margin-bottom: 8px;
}
.chat-label-ai { font-size: 10px; color: #6E6E6E; margin-bottom: 3px; font-weight: 600; }
.chat-label-user { font-size: 10px; color: #F05A22; margin-bottom: 3px; font-weight: 600; text-align: right; }

/* Upload area custom */
.upload-info {
    background: #FAFAF8;
    border: 1.5px dashed #CCC8C2;
    border-radius: 10px;
    padding: 18px;
    text-align: center;
    font-size: 12px;
    color: #6E6E6E;
}
.upload-info.has-file {
    border-color: #A8DEB8;
    background: #F0FAF4;
}

/* Section headers */
.sec-title {
    font-size: 18px; font-weight: 800; color: #141414;
    margin-bottom: 4px;
}
.sec-sub { font-size: 12px; color: #6E6E6E; margin-bottom: 16px; }

/* Priority items */
.prio-row {
    display: flex; align-items: center; gap: 10px;
    background: #F6F4F1; border-radius: 8px;
    padding: 10px 12px; margin-bottom: 6px;
}
.prio-dot { width: 9px; height: 9px; border-radius: 50%; flex-shrink: 0; }

/* Notice */
.notice-box {
    background: #FDECEB; border: 0.5px solid #F5BCBC;
    border-radius: 8px; padding: 10px 14px;
    font-size: 12px; color: #8B1A1A;
    margin-bottom: 14px;
    display: flex; align-items: center; gap: 8px;
}

div[data-testid="stSidebar"] {
    background: #141414 !important;
}
div[data-testid="stSidebar"] * { color: #AAA !important; }
div[data-testid="stSidebar"] .stRadio label { color: #AAA !important; }

/* Esconde label do file_uploader */
.uploadedFile { font-size: 12px !important; }
</style>
""", unsafe_allow_html=True)

# ── SESSION STATE ──
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "hub_df" not in st.session_state:
    st.session_state.hub_df = None
if "pag_df" not in st.session_state:
    st.session_state.pag_df = None
if "ext_files" not in st.session_state:
    st.session_state.ext_files = []

# ── HELPERS ──
def fmt_brl(v):
    try:
        return f"R$ {float(v):_.2f}".replace("_", ".").replace(",", "X").replace(".", ",").replace("X", ".")
    except:
        return "R$ —"

def pill(status, text=None):
    t = text or str(status)
    s = str(status).lower()
    cls = "pill-ok" if any(x in s for x in ["ativ","pago","recebid","ok","em dia"]) \
        else "pill-er" if any(x in s for x in ["inad","vencid","atraso","cancel","danger","critico","urgente"]) \
        else "pill-wa" if any(x in s for x in ["suspen","penden","warn","a vencer","hoje","médio"]) \
        else "pill-bl" if any(x in s for x in ["baixo","info","normal"]) \
        else "pill-gr"
    return f'<span class="pill {cls}">{t}</span>'

def get_anthropic_client():
    try:
        key = st.secrets.get("ANTHROPIC_API_KEY", "")
        if key:
            return anthropic.Anthropic(api_key=key)
    except:
        pass
    key = st.session_state.get("api_key", "")
    if key:
        return anthropic.Anthropic(api_key=key)
    return None

def call_cfo(prompt, system=None, max_tokens=1024):
    client = get_anthropic_client()
    if not client:
        return "⚠️ Configure a chave da API Anthropic na sidebar para ativar o CFO IA."
    sys = system or (
        "Você é Maxwell, Diretor Financeiro (CFO) IA do Grupo Jet / Jet Telecom, "
        "empresa brasileira de logística, transporte e telecomunicações. "
        "Forneça análises ESTRATÉGICAS e PRÁTICAS em português do Brasil. "
        "Use emojis estratégicos, seja objetivo e estruture em tópicos com números. "
        "Máximo 350 palavras."
    )
    try:
        msgs = st.session_state.chat_history[-20:] + [{"role": "user", "content": prompt}]
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=max_tokens,
            system=sys,
            messages=msgs,
        )
        return response.content[0].text
    except Exception as e:
        return f"❌ Erro: {str(e)}"

def smart_read(file):
    name = file.name.lower()
    if name.endswith(".csv"):
        for enc in ["utf-8","latin-1","cp1252"]:
            try:
                file.seek(0)
                return pd.read_csv(file, encoding=enc)
            except:
                pass
    elif name.endswith((".xlsx",".xls")):
        file.seek(0)
        xl = pd.ExcelFile(file)
        if len(xl.sheet_names) == 1:
            return pd.read_excel(file, sheet_name=0)
        sheet = st.selectbox("Selecionar aba:", xl.sheet_names, key=f"sheet_{file.name}")
        return pd.read_excel(file, sheet_name=sheet)
    return None

def detect_col(df, *terms):
    norm = lambda s: s.lower().replace(" ","").replace("_","").replace("-","").replace("/","")
    for col in df.columns:
        for t in terms:
            if norm(t) in norm(col) or norm(col) in norm(t):
                return col
    return None

def parse_val(v):
    if v is None: return 0.0
    try: return float(v)
    except:
        s = str(v).replace("R$","").replace(" ","").replace(".","").replace(",",".")
        try: return float(s)
        except: return 0.0

# ── SIDEBAR ──
with st.sidebar:
    st.markdown("""
    <div style='padding:14px 4px 10px;border-bottom:1px solid #2A2A2A;margin-bottom:8px'>
        <div style='display:flex;align-items:center;gap:8px'>
            <div style='width:30px;height:30px;background:#F05A22;border-radius:7px;
                        display:flex;align-items:center;justify-content:center;
                        font-weight:900;color:white;font-size:16px'>J</div>
            <div>
                <div style='color:#fff;font-size:14px;font-weight:700'>Grupo Jet</div>
                <div style='color:#555;font-size:10px;text-transform:uppercase;letter-spacing:.07em'>CFO Inteligente</div>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    page = st.radio("", [
        "📊  Dashboard",
        "👥  Clientes",
        "🏦  Extratos Bancários",
        "📥  Importar Planilhas",
        "📋  Contas a Pagar",
        "📈  Previsão Estratégica",
        "🤝  Negociação",
        "🤖  Diretor CFO IA",
    ], label_visibility="collapsed")

    st.markdown("<div style='margin-top:16px;border-top:1px solid #2A2A2A;padding-top:14px'></div>", unsafe_allow_html=True)

    with st.expander("🔑 Chave API Anthropic"):
        api_key_input = st.text_input(
            "Chave API (sk-ant-...)",
            type="password",
            value=st.session_state.get("api_key",""),
            placeholder="sk-ant-...",
            label_visibility="collapsed"
        )
        if api_key_input:
            st.session_state.api_key = api_key_input
            st.success("✅ Chave salva")
        st.caption("Obtenha em console.anthropic.com → API Keys")

    st.markdown("""
    <div style='background:linear-gradient(135deg,#F05A22,#FF8040);border-radius:10px;
                padding:10px 12px;cursor:pointer;margin-top:8px'>
        <div style='color:#fff;font-size:12px;font-weight:700'>
            <span style='width:7px;height:7px;border-radius:50%;background:#fff;
                        display:inline-block;margin-right:5px'></span>
            Maxwell CFO · Online
        </div>
        <div style='color:rgba(255,255,255,.7);font-size:10px;margin-top:2px'>
            Análise em tempo real
        </div>
    </div>
    """, unsafe_allow_html=True)

# ── HEADER ──
now = datetime.now().strftime("%A, %d de %B de %Y")
st.markdown(f"""
<div class="jet-header">
    <div class="jet-logo-box">J</div>
    <div>
        <div class="jet-header-title">Grupo Jet · Plataforma CFO IA</div>
        <div class="jet-header-sub">{now}</div>
    </div>
    <div class="jet-header-right">
        <span class="hs-badge"><span class="online-dot"></span> Maxwell CFO ativo</span>
    </div>
</div>
""", unsafe_allow_html=True)


# ════════════════════════════════════════
# DASHBOARD
# ════════════════════════════════════════
if "Dashboard" in page:
    st.markdown('<div class="sec-title">Dashboard Financeiro</div>', unsafe_allow_html=True)
    st.markdown('<div class="sec-sub">Visão consolidada · Grupo Jet</div>', unsafe_allow_html=True)

    c1,c2,c3,c4 = st.columns(4)
    with c1:
        st.markdown("""<div class="kpi-card"><div class="kpi-label">Faturamento Mensal</div>
        <div class="kpi-value">R$ 4,2M</div>
        <div class="kpi-delta pos">▲ +12,4% vs mês anterior</div></div>""", unsafe_allow_html=True)
    with c2:
        st.markdown("""<div class="kpi-card"><div class="kpi-label">Contas a Receber</div>
        <div class="kpi-value">R$ 1,8M</div>
        <div class="kpi-delta warn">⏱ 34 títulos em aberto</div></div>""", unsafe_allow_html=True)
    with c3:
        st.markdown("""<div class="kpi-card"><div class="kpi-label">Contas a Pagar</div>
        <div class="kpi-value">R$ 980K</div>
        <div class="kpi-delta neg">⚠ 8 vencem esta semana</div></div>""", unsafe_allow_html=True)
    with c4:
        st.markdown("""<div class="kpi-card"><div class="kpi-label">Margem Líquida</div>
        <div class="kpi-value">18,7%</div>
        <div class="kpi-delta pos">▲ +2,1pp acima da meta</div></div>""", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    col_chart, col_prior = st.columns([1.6, 1])

    with col_chart:
        meses = ["Dez","Jan","Fev","Mar","Abr","Mai"]
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=meses, y=[3800,3600,4100,3900,4200,4200],
            name="Receitas", line=dict(color="#F05A22",width=2.5), fill="tozeroy",
            fillcolor="rgba(240,90,34,.07)", mode="lines+markers", marker=dict(size=5)))
        fig.add_trace(go.Scatter(x=meses, y=[3100,3300,3500,3200,3400,3500],
            name="Despesas", line=dict(color="#999",width=1.5,dash="dot"),
            fill="tozeroy", fillcolor="rgba(153,153,153,.04)",
            mode="lines+markers", marker=dict(size=4)))
        fig.update_layout(title="Fluxo de Caixa — 6 meses",
            height=240, margin=dict(t=36,b=0,l=0,r=0),
            plot_bgcolor="white", paper_bgcolor="white",
            legend=dict(orientation="h",y=-0.15),
            yaxis=dict(tickformat=",.0f", gridcolor="#F0EDE8"),
            xaxis=dict(gridcolor="#F0EDE8"))
        st.plotly_chart(fig, use_container_width=True)

    with col_prior:
        st.markdown("**Prioridades Imediatas**")
        st.markdown("""
        <div class="prio-row">
            <div class="prio-dot" style="background:#D93025"></div>
            <div style="flex:1"><div style="font-size:12px;font-weight:600">Logística S.A.</div>
            <div style="font-size:10px;color:#6E6E6E">Vence hoje</div></div>
            <div><div style="font-weight:700;color:#D93025">R$ 85K</div>
            <span class="pill pill-er">Urgente</span></div>
        </div>
        <div class="prio-row">
            <div class="prio-dot" style="background:#D97706"></div>
            <div style="flex:1"><div style="font-size:12px;font-weight:600">Folha de Pagamento</div>
            <div style="font-size:10px;color:#6E6E6E">Em 3 dias</div></div>
            <div><div style="font-weight:700;color:#D97706">R$ 320K</div>
            <span class="pill pill-wa">Atenção</span></div>
        </div>
        <div class="prio-row">
            <div class="prio-dot" style="background:#22A85A"></div>
            <div style="flex:1"><div style="font-size:12px;font-weight:600">ABC — Recebimento</div>
            <div style="font-size:10px;color:#6E6E6E">Em 5 dias</div></div>
            <div><div style="font-weight:700;color:#22A85A">R$ 210K</div>
            <span class="pill pill-ok">Confirmado</span></div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    col_donut, col_insight = st.columns(2)
    with col_donut:
        fig2 = go.Figure(go.Pie(
            labels=["Frete Nacional","Frete Interestadual","Armazenagem","Serviços"],
            values=[52,24,16,8],
            marker_colors=["#F05A22","#888","#BBB","#DDD"],
            hole=0.65, textinfo="percent+label", textfont_size=11))
        fig2.update_layout(title="Composição de Receita",
            height=220, margin=dict(t=36,b=0,l=0,r=0),
            showlegend=False, paper_bgcolor="white")
        st.plotly_chart(fig2, use_container_width=True)

    with col_insight:
        st.markdown("""<div class="insight-box">
        💡 <strong>Atenção crítica:</strong> A inadimplência subiu 2,3pp no trimestre.
        Recomendo renegociação preventiva com os 5 maiores devedores antes do fechamento.
        Janela positiva de caixa entre dias 15–22 — ideal para antecipar recebíveis e
        reduzir custo financeiro.
        </div>""", unsafe_allow_html=True)
        if st.button("🤖 Consultar CFO completo", use_container_width=True, type="primary"):
            st.session_state.goto_cfo = "Faça uma análise completa da saúde financeira do Grupo Jet com recomendações estratégicas imediatas"


# ════════════════════════════════════════
# CLIENTES
# ════════════════════════════════════════
elif "Clientes" in page:
    st.markdown('<div class="sec-title">Clientes & Carteira</div>', unsafe_allow_html=True)
    st.markdown('<div class="sec-sub">Importado via planilha Hubsoft</div>', unsafe_allow_html=True)

    df = st.session_state.hub_df
    if df is not None and len(df) > 0:
        c1,c2,c3,c4 = st.columns(4)
        totFat = df.get("mensalidade", pd.Series([0])).apply(parse_val).sum()
        inad_mask = df.apply(lambda r: any(str(v).lower() in ["inadimplente","inad","delinquent"]
                   for v in r.values), axis=1)
        inad_df = df[inad_mask]
        c1.metric("Total Clientes", len(df))
        c2.metric("Faturamento", fmt_brl(totFat))
        c3.metric("Inadimplentes", len(inad_df))
        c4.metric("Ativos", len(df[df.apply(lambda r: any("ativ" in str(v).lower() for v in r.values), axis=1)]))
        st.markdown("<br>", unsafe_allow_html=True)

        busca = st.text_input("🔍 Buscar cliente, CPF/CNPJ...", key="cli_busca")
        if busca:
            mask = df.apply(lambda r: busca.lower() in " ".join(r.astype(str).str.lower()), axis=1)
            df_show = df[mask]
        else:
            df_show = df
        st.dataframe(df_show.head(500), use_container_width=True, height=380)

        col_a, col_b = st.columns(2)
        with col_a:
            if st.button("🤖 Analisar inadimplência com CFO IA", use_container_width=True, type="primary"):
                with st.spinner("Maxwell analisando..."):
                    resp = call_cfo(
                        f"Analise a carteira de {len(df)} clientes da Jet Telecom. "
                        f"Faturamento: {fmt_brl(totFat)}. "
                        f"Inadimplentes: {len(inad_df)}. "
                        "Gere estratégia de cobrança e retenção."
                    )
                st.markdown(f'<div class="insight-box">{resp}</div>', unsafe_allow_html=True)
    else:
        st.info("📥 Importe a planilha Hubsoft em **Importar Planilhas** para carregar os clientes.")
        st.markdown("""
        <div class="upload-info">
            <div style="font-size:28px;margin-bottom:8px">📋</div>
            <div style="font-size:13px;font-weight:600;color:#141414">Sem dados de clientes</div>
            <div>Vá em <strong>Importar Planilhas</strong> e envie a exportação do Hubsoft</div>
        </div>
        """, unsafe_allow_html=True)


# ════════════════════════════════════════
# EXTRATOS
# ════════════════════════════════════════
elif "Extratos" in page:
    st.markdown('<div class="sec-title">Extratos Bancários</div>', unsafe_allow_html=True)
    st.markdown('<div class="sec-sub">Upload de extrato · Análise pelo CFO IA</div>', unsafe_allow_html=True)

    col_form, col_result = st.columns([1, 1.1])
    with col_form:
        st.markdown("**🏦 Banco de origem**")
        bancos = {
            "BTG Pactual": "🔵",
            "Caixa Econômica Federal": "💙",
            "C6 Bank": "⚫",
            "Banco Safra": "🔴",
            "Banco do Brasil": "🟡",
        }
        banco_sel = st.radio("Banco", list(bancos.keys()),
            format_func=lambda b: f"{bancos[b]} {b}",
            label_visibility="collapsed")

        st.markdown("**📅 Período de referência**")
        c1, c2 = st.columns(2)
        with c1:
            dt_i = st.date_input("De", value=date.today().replace(day=1), label_visibility="collapsed")
        with c2:
            dt_f = st.date_input("Até", value=date.today(), label_visibility="collapsed")

        empresa = st.text_input("Empresa", value="Grupo Jet")
        tipo_analise = st.selectbox("Tipo de análise", [
            "Análise completa", "Fluxo de caixa",
            "Receitas e despesas", "Inadimplência", "Planejamento"
        ])

        st.markdown("**📎 Enviar extrato**")
        uploaded = st.file_uploader(
            "Extrato", type=["pdf","csv","ofx","txt","xlsx","xls"],
            accept_multiple_files=True, label_visibility="collapsed"
        )

        if uploaded:
            for f in uploaded:
                st.markdown(f"""
                <div class="upload-info has-file">
                    ✅ <strong>{f.name}</strong> · {f.size//1024} KB
                </div>
                """, unsafe_allow_html=True)

            if st.button("🤖 Analisar com CFO IA", type="primary", use_container_width=True):
                with st.spinner("Maxwell lendo o extrato..."):
                    conteudo = ""
                    for f in uploaded:
                        try:
                            if f.name.lower().endswith((".csv",".txt",".ofx")):
                                f.seek(0)
                                for enc in ["utf-8","latin-1","cp1252"]:
                                    try:
                                        conteudo += f"\n--- {f.name} ---\n" + f.read().decode(enc)[:4000]
                                        break
                                    except: pass
                            elif f.name.lower().endswith((".xlsx",".xls")):
                                f.seek(0)
                                df_ext = pd.read_excel(f)
                                conteudo += f"\n--- {f.name} ---\n" + df_ext.head(100).to_string()
                        except: pass

                    prompt = f"""Analise o extrato bancário da empresa {empresa}, banco {banco_sel}, período {dt_i} a {dt_f}. Tipo: {tipo_analise}.

Conteúdo do arquivo:
{conteudo[:5000] if conteudo else "Arquivo PDF ou não legível diretamente."}

Responda em JSON com esta estrutura exata (sem markdown):
{{"resumo":{{"entradas":"R$ X","saidas":"R$ X","saldo":"R$ X","transacoes":0}},"insights":["..."],"alertas":[{{"tipo":"danger|warn|success","texto":"..."}}],"recomendacoes":["..."],"transacoes_destaque":[{{"desc":"...","valor":"R$ X","tipo":"entrada|saida","data":"DD/MM"}}],"parecer":"3 frases executivas."}}"""

                    sys = "Você é Maxwell, CFO IA do Grupo Jet. Analise extratos bancários e responda APENAS JSON válido sem markdown."
                    resp_raw = call_cfo(prompt, system=sys, max_tokens=1000)
                    try:
                        clean = resp_raw.replace("```json","").replace("```","").strip()
                        j = json.loads(clean)
                        st.session_state.ext_result = j
                    except:
                        st.session_state.ext_result = {"erro": resp_raw}

    with col_result:
        st.markdown("**🧠 Análise do Diretor Financeiro**")
        res = st.session_state.get("ext_result")
        if res:
            if "erro" in res:
                st.warning(res["erro"])
            else:
                r = res.get("resumo", {})
                c1,c2 = st.columns(2)
                c1.metric("Entradas", r.get("entradas","—"))
                c2.metric("Saídas", r.get("saidas","—"))
                c1.metric("Saldo do período", r.get("saldo","—"))
                c2.metric("Transações", r.get("transacoes","—"))

                st.markdown(f'<div class="insight-box">{res.get("parecer","")}</div>', unsafe_allow_html=True)

                alertas = res.get("alertas",[])
                for a in alertas:
                    tipo = a.get("tipo","warn")
                    txt = a.get("texto","")
                    if tipo == "danger": st.error(txt)
                    elif tipo == "success": st.success(txt)
                    else: st.warning(txt)

                trans = res.get("transacoes_destaque",[])
                if trans:
                    st.markdown("**📌 Transações em destaque**")
                    for t in trans[:5]:
                        icon = "↙️" if t.get("tipo") == "entrada" else "↗️"
                        col = "#22A85A" if t.get("tipo") == "entrada" else "#D93025"
                        st.markdown(f"""
                        <div class="prio-row">
                            <span style="font-size:16px">{icon}</span>
                            <div style="flex:1;font-size:12px;font-weight:600">{t.get("desc","")}</div>
                            <div style="font-size:11px;color:#6E6E6E">{t.get("data","")}</div>
                            <div style="font-weight:700;color:{col}">{t.get("valor","")}</div>
                        </div>
                        """, unsafe_allow_html=True)

                recs = res.get("recomendacoes",[])
                if recs:
                    st.markdown("**🎯 Recomendações CFO**")
                    for i, r in enumerate(recs, 1):
                        st.markdown(f"**{i}.** {r}")
        else:
            st.markdown("""
            <div class="upload-info" style="padding:40px 20px;margin-top:20px">
                <div style="font-size:36px;margin-bottom:10px">📊</div>
                <div style="font-size:13px;font-weight:600;color:#141414">Aguardando extrato</div>
                <div>Selecione o banco, período e<br>envie o arquivo para análise</div>
            </div>
            """, unsafe_allow_html=True)


# ════════════════════════════════════════
# IMPORTAR PLANILHAS
# ════════════════════════════════════════
elif "Importar" in page:
    st.markdown('<div class="sec-title">Importar Planilhas</div>', unsafe_allow_html=True)
    st.markdown('<div class="sec-sub">Hubsoft Export + Contas a Pagar · Análise automática CFO IA</div>', unsafe_allow_html=True)

    col_hub, col_pag = st.columns(2)

    with col_hub:
        st.markdown("#### 🏪 Planilha Hubsoft")
        st.caption("Exporte de: Relatórios → Clientes / Faturamento / Inadimplência")
        hub_file = st.file_uploader("Hubsoft", type=["xlsx","xls","csv"], label_visibility="collapsed", key="hub_up")
        if hub_file:
            try:
                df_h = smart_read(hub_file)
                if df_h is not None:
                    st.success(f"✅ {hub_file.name} · {len(df_h)} linhas · {len(df_h.columns)} colunas")
                    st.session_state.hub_df = df_h
                    with st.expander("👁️ Prévia dos dados"):
                        st.dataframe(df_h.head(20), use_container_width=True)
            except Exception as e:
                st.error(f"Erro ao ler arquivo: {e}")

        if st.session_state.hub_df is not None:
            df_h = st.session_state.hub_df
            st.markdown("---")
            st.markdown(f"**✅ Planilha carregada:** {len(df_h)} registros")
            totFat = sum(parse_val(v) for v in df_h.get(
                detect_col(df_h,"mensalidade","valor","amount") or df_h.columns[0], []))
            st.metric("Faturamento estimado", fmt_brl(totFat))

    with col_pag:
        st.markdown("#### 📋 Contas a Pagar")
        st.caption("Vencidas e a vencer — qualquer formato de planilha")
        pag_file = st.file_uploader("Contas a Pagar", type=["xlsx","xls","csv"], label_visibility="collapsed", key="pag_up")
        if pag_file:
            try:
                df_p = smart_read(pag_file)
                if df_p is not None:
                    st.success(f"✅ {pag_file.name} · {len(df_p)} linhas")
                    st.session_state.pag_df = df_p
                    with st.expander("👁️ Prévia dos dados"):
                        st.dataframe(df_p.head(20), use_container_width=True)
            except Exception as e:
                st.error(f"Erro ao ler arquivo: {e}")

        if st.session_state.pag_df is not None:
            df_p = st.session_state.pag_df
            st.markdown("---")
            col_val = detect_col(df_p,"valor","value","amount","total")
            totPag = sum(parse_val(v) for v in df_p[col_val]) if col_val else 0
            st.markdown(f"**✅ Planilha carregada:** {len(df_p)} contas")
            st.metric("Total a pagar", fmt_brl(totPag))

    st.markdown("---")

    # ANÁLISE COMBINADA
    has_data = st.session_state.hub_df is not None or st.session_state.pag_df is not None
    if has_data:
        tab1, tab2, tab3, tab4 = st.tabs(["👥 Clientes Hubsoft", "⚠️ Inadimplência", "📋 Contas a Pagar", "🤖 Análise CFO"])

        with tab1:
            if st.session_state.hub_df is not None:
                st.dataframe(st.session_state.hub_df, use_container_width=True, height=320)
            else:
                st.info("Importe a planilha Hubsoft.")

        with tab2:
            if st.session_state.hub_df is not None:
                df_h = st.session_state.hub_df
                dias_col = detect_col(df_h,"diasatraso","dias","atraso","days")
                val_col = detect_col(df_h,"valoraberto","aberto","debito","saldo","balance")
                status_col = detect_col(df_h,"status","situacao","estado")
                if status_col:
                    inad = df_h[df_h[status_col].astype(str).str.lower().str.contains("inad|suspen|atraso|vencid")]
                elif dias_col:
                    inad = df_h[df_h[dias_col].apply(parse_val) > 0]
                else:
                    inad = df_h.head(0)
                st.metric("Inadimplentes", len(inad))
                if len(inad) > 0:
                    st.dataframe(inad, use_container_width=True, height=300)
                else:
                    st.success("✅ Nenhuma inadimplência identificada.")
            else:
                st.info("Importe a planilha Hubsoft.")

        with tab3:
            if st.session_state.pag_df is not None:
                df_p = st.session_state.pag_df
                venc_col = detect_col(df_p,"vencimento","vencto","duedate","prazo")
                if venc_col:
                    hoje = pd.Timestamp.now().normalize()
                    df_p2 = df_p.copy()
                    try:
                        df_p2["_venc"] = pd.to_datetime(df_p2[venc_col], dayfirst=True, errors="coerce")
                        df_p2["_dias"] = (df_p2["_venc"] - hoje).dt.days
                        df_p2["_status"] = df_p2["_dias"].apply(
                            lambda d: "🔴 Vencida" if d < 0 else "🔴 Vence hoje" if d == 0
                            else "🟡 A vencer" if d <= 7 else "🟢 Em dia"
                            if not pd.isna(d) else "—"
                        )
                        df_show = df_p2.sort_values("_dias", na_position="last")
                        st.dataframe(df_show.drop(columns=["_venc","_dias"]), use_container_width=True, height=300)
                    except:
                        st.dataframe(df_p, use_container_width=True, height=300)
                else:
                    st.dataframe(df_p, use_container_width=True, height=300)
            else:
                st.info("Importe a planilha de contas a pagar.")

        with tab4:
            df_h = st.session_state.hub_df
            df_p = st.session_state.pag_df
            totFat, totInad, totPag, totVenc = 0, 0, 0, 0
            n_cli, n_inad, n_pag = 0, 0, 0
            if df_h is not None:
                n_cli = len(df_h)
                mc = detect_col(df_h,"mensalidade","valor","amount")
                if mc: totFat = sum(parse_val(v) for v in df_h[mc])
                sc = detect_col(df_h,"status","situacao")
                if sc: n_inad = len(df_h[df_h[sc].astype(str).str.lower().str.contains("inad")])
            if df_p is not None:
                n_pag = len(df_p)
                vc = detect_col(df_p,"valor","value","amount")
                if vc: totPag = sum(parse_val(v) for v in df_p[vc])
                venc_c = detect_col(df_p,"vencimento","vencto")
                if venc_c:
                    hoje = pd.Timestamp.now().normalize()
                    try:
                        vdatas = pd.to_datetime(df_p[venc_c], dayfirst=True, errors="coerce")
                        v_mask = vdatas < hoje
                        vc2 = detect_col(df_p,"valor","value")
                        if vc2: totVenc = sum(parse_val(v) for v in df_p[v_mask][vc2]) if vc2 else 0
                    except: pass

            if st.button("🤖 Gerar Análise CFO Completa", type="primary", use_container_width=True):
                with st.spinner("Maxwell analisando planilhas..."):
                    prompt = f"""Analise as planilhas importadas da Jet Telecom:

HUBSOFT: {n_cli} clientes, faturamento {fmt_brl(totFat)}, {n_inad} inadimplentes.
CONTAS A PAGAR: {n_pag} contas, total {fmt_brl(totPag)}, vencidas: {fmt_brl(totVenc)}.

Gere relatório executivo CFO com:
1. Diagnóstico financeiro e risco de liquidez
2. Prioridade de pagamentos (ordem e justificativa)
3. Estratégia de cobrança dos inadimplentes
4. Alertas críticos e ações imediatas
5. Projeção 30 dias com recomendações

Use emojis e estruture bem a resposta."""
                    resp = call_cfo(prompt, max_tokens=1200)
                    st.markdown(f'<div class="insight-box">{resp.replace(chr(10), "<br>").replace("**", "<strong>", 1).replace("**", "</strong>", 1)}</div>', unsafe_allow_html=True)


# ════════════════════════════════════════
# CONTAS A PAGAR
# ════════════════════════════════════════
elif "Contas" in page:
    st.markdown('<div class="sec-title">Contas a Pagar</div>', unsafe_allow_html=True)
    st.markdown('<div class="sec-sub">Scoring de prioridade e estratégia de pagamento</div>', unsafe_allow_html=True)

    c1,c2,c3,c4 = st.columns(4)
    c1.metric("Total a Pagar", "R$ 983K", "Este mês")
    c2.metric("Vencidas", "R$ 85K", "-2 fornecedores", delta_color="inverse")
    c3.metric("Vence 7 dias", "R$ 362K", "3 contas", delta_color="inverse")
    c4.metric("Em dia", "R$ 536K", "No prazo")

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("**🎯 Fila de Pagamentos · Scoring IA**")

    pagamentos = [
        {"Fornecedor": "Folha de Pagamento", "Tipo": "Obrigação legal", "Valor": "R$ 320.000", "Vencimento": "25/05", "Score": 100, "Prioridade": "🔴 Crítico"},
        {"Fornecedor": "Logística S.A.", "Tipo": "Operação core", "Valor": "R$ 85.000", "Vencimento": "17/05", "Score": 95, "Prioridade": "🔴 Urgente"},
        {"Fornecedor": "Seguro Frota", "Tipo": "Proteção ativos", "Valor": "R$ 42.500", "Vencimento": "22/05", "Score": 82, "Prioridade": "🟡 Alto"},
        {"Fornecedor": "Manutenção Veículos", "Tipo": "Serviço recorrente", "Valor": "R$ 28.000", "Vencimento": "30/05", "Score": 60, "Prioridade": "🟡 Médio"},
        {"Fornecedor": "Software ERP", "Tipo": "Licença mensal", "Valor": "R$ 8.200", "Vencimento": "31/05", "Score": 40, "Prioridade": "🟢 Normal"},
    ]
    st.dataframe(pd.DataFrame(pagamentos), use_container_width=True, hide_index=True)

    if st.session_state.pag_df is not None:
        st.markdown("---")
        st.markdown("**📋 Dados importados da planilha**")
        st.dataframe(st.session_state.pag_df.head(200), use_container_width=True, height=300)

    if st.button("🤖 Estratégia de caixa pelo CFO IA", type="primary"):
        with st.spinner("Maxwell analisando..."):
            resp = call_cfo("Analise as contas a pagar do Grupo Jet (folha R$320K, logística R$85K vencida, seguro R$42,5K, manutenção R$28K, ERP R$8,2K) e gere plano de fluxo de caixa para cobrir todos os compromissos sem comprometer a operação.")
        st.markdown(f'<div class="insight-box">{resp}</div>', unsafe_allow_html=True)


# ════════════════════════════════════════
# PREVISÃO
# ════════════════════════════════════════
elif "Previsão" in page:
    st.markdown('<div class="sec-title">Previsão Estratégica</div>', unsafe_allow_html=True)

    c1,c2,c3,c4 = st.columns(4)
    c1.metric("Cenário Otimista", "R$ 5,8M", "+38%")
    c2.metric("Cenário Base", "R$ 4,9M", "Mais provável")
    c3.metric("Cenário Conservador", "R$ 4,1M", "Risco alto", delta_color="inverse")
    c4.metric("Break-even", "R$ 3,4M", "Mínimo operacional")

    meses = ["Jun","Jul","Ago","Set","Out","Nov","Dez","Jan","Fev","Mar","Abr","Mai"]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=meses, y=[4500,4700,4900,5100,5300,5500,5600,5700,5800,5850,5900,5800],
        name="Otimista", line=dict(color="#22A85A",width=1.5,dash="dot"), mode="lines+markers", marker=dict(size=4)))
    fig.add_trace(go.Scatter(x=meses, y=[4200,4300,4400,4600,4700,4800,4850,4900,4950,4900,4950,4900],
        name="Base", line=dict(color="#F05A22",width=2.5), mode="lines+markers", marker=dict(size=5)))
    fig.add_trace(go.Scatter(x=meses, y=[3900,3800,4000,4100,4100,4200,4100,4100,4200,4100,4150,4100],
        name="Conservador", line=dict(color="#D93025",width=1.5,dash="dot"), mode="lines+markers", marker=dict(size=4)))
    fig.update_layout(title="Projeção de Fluxo de Caixa — 12 meses",
        height=300, margin=dict(t=40,b=0,l=0,r=0),
        plot_bgcolor="white", paper_bgcolor="white",
        legend=dict(orientation="h",y=-0.15),
        yaxis=dict(tickformat=",.0f", gridcolor="#F0EDE8"),
        xaxis=dict(gridcolor="#F0EDE8"))
    st.plotly_chart(fig, use_container_width=True)

    col1, col2 = st.columns(2)
    with col1:
        if st.button("🤖 Projeção personalizada CFO IA", type="primary", use_container_width=True):
            with st.spinner("Maxwell projetando..."):
                resp = call_cfo("Com base no faturamento atual da Jet Telecom de R$4,2M/mês, crie projeção estratégica para os próximos 12 meses com ações prioritárias por trimestre.")
            st.markdown(f'<div class="insight-box">{resp}</div>', unsafe_allow_html=True)
    with col2:
        if st.button("🛡️ Análise de riscos", use_container_width=True):
            with st.spinner("Maxwell analisando riscos..."):
                resp = call_cfo("Quais são os principais riscos financeiros da Jet Telecom para os próximos 6 meses e como mitigá-los?")
            st.markdown(f'<div class="insight-box">{resp}</div>', unsafe_allow_html=True)


# ════════════════════════════════════════
# NEGOCIAÇÃO
# ════════════════════════════════════════
elif "Negociação" in page:
    st.markdown('<div class="sec-title">Negociação Estratégica</div>', unsafe_allow_html=True)

    col1, col2 = st.columns(2)
    with col1:
        st.metric("Potencial de Economia", "R$ 127K/mês", "4 contratos renegociáveis")
        if st.button("🤖 Estratégia de negociação completa", type="primary", use_container_width=True):
            with st.spinner("Maxwell estrategizando..."):
                resp = call_cfo("Elabore estratégia detalhada para reduzir R$ 127K mensais nos contratos do Grupo Jet, com argumentos e abordagem por fornecedor.")
            st.markdown(f'<div class="insight-box">{resp}</div>', unsafe_allow_html=True)

    with col2:
        st.markdown("**⚠️ Top Inadimplentes**")
        inadimplentes = [
            {"Cliente": "Distribuidora XYZ", "Em aberto": "R$ 184K", "Dias": "92d"},
            {"Cliente": "Transportes MG", "Em aberto": "R$ 96K", "Dias": "47d"},
            {"Cliente": "Armazéns Norte", "Em aberto": "R$ 52K", "Dias": "31d"},
        ]
        st.dataframe(pd.DataFrame(inadimplentes), use_container_width=True, hide_index=True)

    st.markdown("---")
    st.markdown("**📄 Contratos para Renegociar**")
    contratos = [
        {"Contrato": "Combustível — Posto Central", "Valor Atual": "R$ 210K/mês", "Meta": "-8% → R$ 193K", "Vencimento": "Jun/25", "Economia/mês": "R$ 17K"},
        {"Contrato": "Seguro Frota Completa", "Valor Atual": "R$ 42K/mês", "Meta": "-12% → R$ 37K", "Vencimento": "Ago/25", "Economia/mês": "R$ 5K"},
        {"Contrato": "Terceirização TI", "Valor Atual": "R$ 18K/mês", "Meta": "-15% → R$ 15K", "Vencimento": "Jul/25", "Economia/mês": "R$ 3K"},
    ]
    st.dataframe(pd.DataFrame(contratos), use_container_width=True, hide_index=True)

    contrato_sel = st.selectbox("Gerar proposta para:", [c["Contrato"] for c in contratos])
    if st.button("🤖 Gerar proposta de negociação", type="primary"):
        with st.spinner("Maxwell elaborando proposta..."):
            resp = call_cfo(f"Elabore uma proposta de negociação detalhada para renegociar o contrato '{contrato_sel}' do Grupo Jet, com argumentos sólidos, abordagem e contra-argumentos possíveis.")
        st.markdown(f'<div class="insight-box">{resp}</div>', unsafe_allow_html=True)


# ════════════════════════════════════════
# CFO IA — CHAT
# ════════════════════════════════════════
elif "CFO" in page:
    st.markdown('<div class="sec-title">Diretor CFO IA · Maxwell</div>', unsafe_allow_html=True)

    # Header do chat
    st.markdown("""
    <div style="background:white;border-radius:10px;border:0.5px solid #E5E1DC;
                padding:14px 18px;display:flex;align-items:center;gap:12px;margin-bottom:12px">
        <div style="width:44px;height:44px;border-radius:50%;background:#F05A22;
                    display:flex;align-items:center;justify-content:center;
                    font-size:22px;color:white;flex-shrink:0">🤖</div>
        <div>
            <div style="font-size:14px;font-weight:700">Maxwell CFO · IA Estratégica</div>
            <div style="font-size:12px;color:#6E6E6E">Diretor Financeiro Virtual · Grupo Jet</div>
        </div>
        <div style="margin-left:auto;display:flex;align-items:center;gap:5px;
                    font-size:11px;color:#22A85A;font-weight:600">
            <span style="width:7px;height:7px;border-radius:50%;background:#22A85A;
                        display:inline-block"></span> Online
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Quick chips
    st.markdown("**Atalhos rápidos:**")
    chips = st.columns(6)
    quick = [
        "Saúde financeira", "Priorizar pagamentos",
        "Melhorar margem", "Reduzir inadimplência",
        "Projeção 6 meses", "Riscos financeiros"
    ]
    prompts = [
        "Qual é a saúde financeira atual do Grupo Jet?",
        "Quais pagamentos devo priorizar esta semana?",
        "Como melhorar a margem líquida do Grupo Jet?",
        "Qual a estratégia para reduzir inadimplência?",
        "Quais os cenários de crescimento para os próximos 6 meses?",
        "Analise os riscos financeiros do Grupo Jet para os próximos 6 meses",
    ]
    for i, (col, chip, prompt) in enumerate(zip(chips, quick, prompts)):
        with col:
            if st.button(chip, key=f"chip_{i}", use_container_width=True):
                st.session_state.pending_prompt = prompt

    st.markdown("---")

    # Histórico do chat
    if not st.session_state.chat_history:
        st.markdown("""
        <div class="chat-ai">
            <div class="chat-label-ai">🤖 Maxwell CFO</div>
            Olá! Sou o <strong>Maxwell</strong>, seu Diretor Financeiro IA do Grupo Jet. 👋<br><br>
            Analiso suas finanças, crio estratégias de pagamento e negociação, e apoio decisões
            críticas com base no faturamento. Use os atalhos acima ou faça qualquer pergunta
            financeira. O que analisamos hoje?
        </div>
        """, unsafe_allow_html=True)

    for msg in st.session_state.chat_history:
        if msg["role"] == "user":
            st.markdown(f"""
            <div style="text-align:right">
                <div class="chat-label-user">Você</div>
                <div class="chat-user">{msg["content"]}</div>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.markdown(f"""
            <div class="chat-ai">
                <div class="chat-label-ai">🤖 Maxwell CFO</div>
                {msg["content"].replace(chr(10), "<br>")}
            </div>
            """, unsafe_allow_html=True)

    # Input
    st.markdown("<br>", unsafe_allow_html=True)
    col_inp, col_btn = st.columns([5, 1])
    with col_inp:
        user_input = st.text_area("Mensagem", placeholder="Faça uma pergunta financeira...",
                                   height=70, label_visibility="collapsed", key="chat_inp")
    with col_btn:
        st.markdown("<br>", unsafe_allow_html=True)
        send = st.button("Enviar ▶", type="primary", use_container_width=True)

    # Processar pending (chips)
    pending = st.session_state.pop("pending_prompt", None)
    if pending:
        with st.spinner("Maxwell analisando..."):
            st.session_state.chat_history.append({"role": "user", "content": pending})
            reply = call_cfo(pending)
            st.session_state.chat_history.append({"role": "assistant", "content": reply})
        st.rerun()

    if send and user_input.strip():
        with st.spinner("Maxwell analisando..."):
            st.session_state.chat_history.append({"role": "user", "content": user_input.strip()})
            reply = call_cfo(user_input.strip())
            st.session_state.chat_history.append({"role": "assistant", "content": reply})
        st.rerun()

    if st.session_state.chat_history:
        if st.button("🗑️ Limpar conversa"):
            st.session_state.chat_history = []
            st.rerun()

    # Goto CFO (vindo de outro módulo)
    goto = st.session_state.pop("goto_cfo", None)
    if goto:
        with st.spinner("Maxwell analisando..."):
            st.session_state.chat_history.append({"role": "user", "content": goto})
            reply = call_cfo(goto)
            st.session_state.chat_history.append({"role": "assistant", "content": reply})
        st.rerun()
