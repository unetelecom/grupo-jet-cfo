"""
INTEGRAÇÃO HUBSOFT — Componente Streamlit
Adiciona a aba 🔗 Hubsoft ao Agenda de Caixa com dados ao vivo.
"""
import streamlit as st
import pandas as pd
from datetime import datetime

# Importa o cliente (mesmo diretório)
try:
    from hubsoft_api import HubsoftAPI
    _HAS_HUB = True
except ImportError:
    _HAS_HUB = False


def brl(v):
    try:
        n = abs(float(v))
        s = f"{n:,.2f}".replace(".", "\x00").replace(",", ".").replace("\x00", ",")
        return f"R$ {s}"
    except:
        return "R$ —"


@st.cache_data(ttl=300, show_spinner=False)
def _buscar_hubsoft(base_url, client_id, client_secret, username, password, mes):
    """Cache de 5 min para não sobrecarregar a API."""
    hub = HubsoftAPI(base_url, client_id, client_secret, username, password)
    hub.autenticar()
    fin = hub.get_financeiro_consolidado(mes)
    clientes = hub.get_cruzamento_clientes(mes)
    return fin, clientes


def render_tab_hubsoft():
    """Renderiza a aba completa de integração Hubsoft."""
    st.markdown("### 🔗 Integração Hubsoft — Dados ao Vivo")

    if not _HAS_HUB:
        st.error("Módulo `hubsoft_api` não encontrado.")
        return

    # ── Configurações ──────────────────────────────────────────────
    with st.expander("⚙️ Configurar credenciais Hubsoft", expanded=True):
        st.markdown("Preencha as credenciais da API (ou configure nos Streamlit Secrets).")

        # Tenta carregar dos secrets
        def get_secret(k, default=""):
            try: return st.secrets.get(k, default)
            except: return default

        col1, col2 = st.columns(2)
        with col1:
            base_url = st.text_input(
                "🌐 URL da API",
                value=get_secret("HUBSOFT_URL", "https://jettelecom.hubsoft.com.br"),
                key="hub_url"
            )
            client_id = st.text_input(
                "🔑 Client ID",
                value=get_secret("HUBSOFT_CLIENT_ID", ""),
                key="hub_client_id"
            )
            client_secret = st.text_input(
                "🔐 Client Secret",
                value=get_secret("HUBSOFT_CLIENT_SECRET", ""),
                type="password", key="hub_secret"
            )
        with col2:
            username = st.text_input(
                "👤 Usuário (e-mail)",
                value=get_secret("HUBSOFT_USERNAME", ""),
                key="hub_user"
            )
            password = st.text_input(
                "🔒 Senha",
                value=get_secret("HUBSOFT_PASSWORD", ""),
                type="password", key="hub_pass"
            )
            mes_sel = st.text_input(
                "📅 Mês (YYYY-MM)",
                value=datetime.now().strftime("%Y-%m"),
                key="hub_mes",
                help="Ex: 2026-05"
            )

        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            btn_buscar = st.button("🔄 Buscar dados do Hubsoft", type="primary",
                                   use_container_width=True, key="btn_hub")
        with col_btn2:
            btn_limpar = st.button("🗑️ Limpar cache", use_container_width=True,
                                   key="btn_hub_clear")
            if btn_limpar:
                _buscar_hubsoft.clear()
                st.success("Cache limpo!")

    if not btn_buscar:
        st.info(
            "👆 Preencha as credenciais acima e clique em **Buscar dados** para carregar "
            "cobranças, clientes e faturas diretamente do Hubsoft."
        )
        st.markdown("""
        **O que será importado:**
        - 👥 **Clientes** — cadastro completo
        - ✅ **Cobranças pagas** — com valor e data de pagamento
        - 🔴 **Cobranças atrasadas** — vencidas e não pagas
        - 🔵 **A vencer** — próximos 30/60/90 dias
        - 📊 **Cruzamento cliente × financeiro** — faturado × recebido × atrasado
        """)
        return

    if not all([base_url, client_id, client_secret, username, password]):
        st.error("❌ Preencha todas as credenciais antes de buscar.")
        return

    # ── Busca dados ─────────────────────────────────────────────────
    with st.spinner("🔄 Conectando ao Hubsoft..."):
        try:
            fin, cli_df = _buscar_hubsoft(
                base_url, client_id, client_secret, username, password, mes_sel
            )
            st.success(f"✅ Conectado ao Hubsoft — dados de **{mes_sel}**")
        except Exception as e:
            st.error(f"❌ Erro ao conectar: {e}")
            st.code(str(e))
            return

    totais = fin.get("totais", {})
    if not totais:
        st.warning("Nenhuma cobrança encontrada para o período.")
        return

    # ── KPIs ────────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown(f"#### 📊 Resumo Financeiro — {mes_sel}")
    k1,k2,k3,k4,k5 = st.columns(5)
    k1.metric("📋 Faturado",    brl(totais["faturado"]),
              f"{totais['n_cobrancas']} cobranças")
    k2.metric("✅ Recebido",    brl(totais["recebido"]),
              f"{totais['n_pagas']} pagas · {totais['adimplencia']}%")
    k3.metric("🔴 Atrasado",    brl(totais["atrasado"]),
              f"{totais['n_atrasadas']} cobranças", delta_color="inverse")
    k4.metric("🔵 A Vencer",    brl(totais["a_vencer"]),
              f"{totais['n_a_vencer']} cobranças")
    a_receber = totais["atrasado"] + totais["a_vencer"]
    k5.metric("📈 A Receber",   brl(a_receber))

    st.markdown("---")

    # ── Tabs por status ─────────────────────────────────────────────
    t1, t2, t3, t4 = st.tabs([
        f"📊 Clientes ({len(cli_df)})",
        f"✅ Pagas ({totais['n_pagas']})",
        f"🔴 Atrasadas ({totais['n_atrasadas']})",
        f"🔵 A Vencer ({totais['n_a_vencer']})",
    ])

    # ── ABA CLIENTES ────────────────────────────────────────────────
    with t1:
        st.markdown("#### 👥 Cruzamento por Cliente — Faturado × Recebido × Atrasado × A Vencer")
        if cli_df.empty:
            st.info("Sem dados de clientes.")
        else:
            # Filtros
            cf1, cf2 = st.columns([3, 2])
            with cf1: busca = st.text_input("🔍 Buscar cliente:", key="hub_busca_cli")
            with cf2:
                filt = st.selectbox("Situação:", [
                    "Todos","Com Atrasado","Sem Pagamento","Totalmente Pago"
                ], key="hub_filt_cli")

            df_s = cli_df.copy()
            if busca:
                df_s = df_s[df_s["nome_cliente"].str.lower().str.contains(busca.lower(), na=False)]
            if filt == "Com Atrasado":      df_s = df_s[df_s["atrasado"] > 0]
            elif filt == "Sem Pagamento":   df_s = df_s[df_s["recebido"] == 0]
            elif filt == "Totalmente Pago": df_s = df_s[df_s["a_vencer"] + df_s["atrasado"] == 0]

            disp = pd.DataFrame({
                "Cliente":       df_s["nome_cliente"].str[:45],
                "Faturado":      df_s["faturado"].apply(brl),
                "Recebido":      df_s["recebido"].apply(brl),
                "Atrasado":      df_s["atrasado"].apply(brl),
                "A Vencer":      df_s["a_vencer"].apply(brl),
                "Adimpl. %":     df_s["adimplencia_pct"].apply(lambda v: f"{v:.1f}%"),
                "Cobranças":     df_s["n_cob"].astype(int),
            })
            st.dataframe(disp, use_container_width=True, hide_index=True,
                         height=min(38*len(disp)+42, 540))

    # ── ABA PAGAS ───────────────────────────────────────────────────
    with t2:
        st.markdown("#### ✅ Cobranças Pagas")
        df_p = fin.get("pagas", pd.DataFrame())
        if df_p.empty:
            st.info("Nenhuma cobrança paga no período.")
        else:
            cols = ["nome_cliente","valor","data_vencimento","data_pagamento","descricao"]
            cols = [c for c in cols if c in df_p.columns]
            disp_p = df_p[cols].copy()
            for dc in ["data_vencimento","data_pagamento"]:
                if dc in disp_p.columns:
                    disp_p[dc] = disp_p[dc].dt.strftime("%d/%m/%Y")
            disp_p["valor"] = df_p["valor"].apply(brl)
            st.metric("Total Recebido", brl(df_p["valor"].sum()), f"{len(df_p)} cobranças")
            st.dataframe(disp_p, use_container_width=True, hide_index=True, height=460)

    # ── ABA ATRASADAS ────────────────────────────────────────────────
    with t3:
        st.markdown("#### 🔴 Cobranças Atrasadas (Inadimplentes)")
        df_a = fin.get("atrasadas", pd.DataFrame())
        if df_a.empty:
            st.success("🎉 Nenhuma cobrança atrasada!")
        else:
            cols = ["nome_cliente","valor","data_vencimento","dias_atraso","descricao"]
            cols = [c for c in cols if c in df_a.columns]
            disp_a = df_a[cols].sort_values("dias_atraso" if "dias_atraso" in cols else cols[0],
                                            ascending=False).copy()
            if "data_vencimento" in disp_a.columns:
                disp_a["data_vencimento"] = disp_a["data_vencimento"].dt.strftime("%d/%m/%Y")
            if "valor" in disp_a.columns:
                disp_a["valor"] = df_a["valor"].apply(brl)
            st.metric("Total Atrasado", brl(df_a["valor"].sum()),
                      f"{len(df_a)} cobranças", delta_color="inverse")
            st.dataframe(disp_a, use_container_width=True, hide_index=True, height=460)

    # ── ABA A VENCER ─────────────────────────────────────────────────
    with t4:
        st.markdown("#### 🔵 Cobranças a Vencer")
        df_v = fin.get("a_vencer", pd.DataFrame())
        if df_v.empty:
            st.info("Nenhuma cobrança a vencer no período.")
        else:
            cols = ["nome_cliente","valor","data_vencimento","descricao"]
            cols = [c for c in cols if c in df_v.columns]
            disp_v = df_v[cols].sort_values("data_vencimento" if "data_vencimento" in cols else cols[0]).copy()
            if "data_vencimento" in disp_v.columns:
                disp_v["data_vencimento"] = disp_v["data_vencimento"].dt.strftime("%d/%m/%Y")
            if "valor" in disp_v.columns:
                disp_v["valor"] = df_v["valor"].apply(brl)
            st.metric("Total a Vencer", brl(df_v["valor"].sum()),
                      f"{len(df_v)} cobranças")
            st.dataframe(disp_v, use_container_width=True, hide_index=True, height=460)

    # ── EXPORTAR ──────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("#### 💾 Exportar Dados")
    ec1, ec2, ec3 = st.columns(3)
    cobrancas_all = fin.get("cobrancas", pd.DataFrame())

    if not cobrancas_all.empty:
        import io
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
            cobrancas_all.to_excel(writer, sheet_name="Cobranças", index=False)
            cli_df.to_excel(writer, sheet_name="Clientes", index=False)
            fin.get("pagas", pd.DataFrame()).to_excel(writer, sheet_name="Pagas", index=False)
            fin.get("atrasadas", pd.DataFrame()).to_excel(writer, sheet_name="Atrasadas", index=False)
            fin.get("a_vencer", pd.DataFrame()).to_excel(writer, sheet_name="A Vencer", index=False)
        buf.seek(0)
        with ec1:
            st.download_button(
                "📥 Baixar Excel completo",
                data=buf,
                file_name=f"hubsoft_{mes_sel}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )
