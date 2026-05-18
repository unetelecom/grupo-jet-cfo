"""
HUBSOFT API — Grupo Jet Telecom
Auto-importação completa: clientes, cobranças pagas, abertas, atrasadas, a vencer.
Documentação: https://docs.hubsoft.com.br
"""
import requests
import pandas as pd
from datetime import datetime, timedelta
import calendar
import time


IC_NOMES = {"RDMI", "RRD TELECOM", "GRUPO JET", "JET TELECOM", "RD TELECOM"}


# ══════════════════════════════════════════════════════════════════════
class HubsoftAPI:

    def __init__(self, base_url, client_id, client_secret, username, password):
        self.base_url      = base_url.rstrip("/")
        self.client_id     = str(client_id)
        self.client_secret = client_secret
        self.username      = username
        self.password      = password
        self.token         = None
        self.token_expiry  = None
        self.s             = requests.Session()
        self.s.headers.update({
            "Content-Type": "application/json",
            "Accept": "application/json",
        })

    # ── Auth ──────────────────────────────────────────────────────────
    def autenticar(self):
        url  = f"{self.base_url}/oauth/token"
        body = {
            "grant_type":    "password",
            "client_id":     self.client_id,
            "client_secret": self.client_secret,
            "username":      self.username,
            "password":      self.password,
        }
        r = self.s.post(url, json=body, timeout=30)
        if r.status_code != 200:
            raise ConnectionError(
                f"Hubsoft auth falhou ({r.status_code}): {r.text[:200]}"
            )
        data = r.json()
        self.token = data.get("access_token") or data.get("token")
        if not self.token:
            raise ConnectionError(f"Token não encontrado na resposta: {data}")
        exp = data.get("expires_in", 3600)
        self.token_expiry = datetime.now() + timedelta(seconds=exp - 60)
        self.s.headers["Authorization"] = f"Bearer {self.token}"
        return self.token

    def _ok_token(self):
        if not self.token or datetime.now() >= (self.token_expiry or datetime.min):
            self.autenticar()

    # ── GET com retry ─────────────────────────────────────────────────
    def _get(self, endpoint, params=None, tentativas=3):
        self._ok_token()
        url = f"{self.base_url}{endpoint}"
        for t in range(tentativas):
            try:
                r = self.s.get(url, params=params or {}, timeout=30)
                if r.status_code == 401:
                    self.autenticar()
                    r = self.s.get(url, params=params or {}, timeout=30)
                r.raise_for_status()
                return r.json()
            except requests.exceptions.Timeout:
                if t == tentativas - 1:
                    raise
                time.sleep(2)

    # ── Paginação automática ──────────────────────────────────────────
    def _paginar(self, endpoint, params=None, limit=100, max_pag=200):
        p = dict(params or {})
        p["pagina"] = 0
        p["limit"]  = limit
        dados = []
        for _ in range(max_pag):
            resp = self._get(endpoint, p)
            bloco = (resp.get("dados") or resp.get("data") or
                     resp.get("clientes") or resp.get("contratos") or [])
            if isinstance(bloco, list):
                dados.extend(bloco)
            elif isinstance(bloco, dict):
                dados.append(bloco)
            pag = resp.get("paginacao") or {}
            ultima  = pag.get("ultima_pagina", 0)
            atual   = pag.get("pagina_atual",  p["pagina"])
            if not bloco or atual >= ultima:
                break
            p["pagina"] = atual + 1
        return dados

    # ══════════════════════════════════════════════════════════════════
    # CLIENTES
    # ══════════════════════════════════════════════════════════════════
    def get_clientes(self, status="ativo"):
        params = {}
        if status != "todos":
            params["status"] = status
        dados = self._paginar("/api/v1/integracao/cliente", params)
        if not dados:
            return pd.DataFrame()
        df = pd.json_normalize(dados)
        rename = {
            "id":                   "id_cliente",
            "nome_razaosocial":     "nome",
            "cpf_cnpj":             "cpf_cnpj",
            "email":                "email",
            "telefone":             "telefone",
            "status":               "status",
            "data_cadastro":        "data_cadastro",
            "endereco.cidade":      "cidade",
            "endereco.estado":      "estado",
            "endereco.bairro":      "bairro",
        }
        return df.rename(columns={k: v for k, v in rename.items() if k in df.columns})

    # ══════════════════════════════════════════════════════════════════
    # COBRANÇAS
    # ══════════════════════════════════════════════════════════════════
    def get_cobrancas(self, data_ini, data_fim, tipo_data="vencimento",
                      status=None, pago=None):
        """
        tipo_data: 'vencimento' | 'pagamento' | 'lancamento'
        status:    None | 'aberto' | 'pago'
        pago:      None | 1 (pagas) | 0 (não pagas)
        """
        params = {
            f"data_{tipo_data}_ini": data_ini,
            f"data_{tipo_data}_fim": data_fim,
        }
        if status:  params["status"] = status
        if pago is not None: params["pago"] = pago

        dados = self._paginar(
            "/api/v1/integracao/financeiro/cobranca", params
        )
        if not dados:
            return pd.DataFrame()
        df = pd.json_normalize(dados)
        return self._norm_cobrancas(df)

    def get_faturas(self, data_ini, data_fim, status_pag=None):
        params = {
            "data_vencimento_ini": data_ini,
            "data_vencimento_fim": data_fim,
        }
        if status_pag:
            params["status_pagamento"] = status_pag
        dados = self._paginar("/api/v1/integracao/financeiro/fatura", params)
        if not dados:
            return pd.DataFrame()
        return pd.json_normalize(dados)

    # ── Normaliza cobranças ───────────────────────────────────────────
    @staticmethod
    def _norm_cobrancas(df):
        if df.empty:
            return df
        today = pd.Timestamp.now().normalize()
        rename = {
            "id":                           "id_cobranca",
            "id_cliente":                   "id_cliente",
            "nome_razaosocial":             "nome_cliente",
            "cliente.nome_razaosocial":     "nome_cliente",
            "cliente.nome":                 "nome_cliente",
            "valor":                        "valor",
            "valor_pago":                   "valor_pago",
            "data_vencimento":              "data_vencimento",
            "data_pagamento":               "data_pagamento",
            "data_lancamento":              "data_lancamento",
            "status":                       "status_raw",
            "descricao":                    "descricao",
            "servico":                      "servico",
            "forma_pagamento":              "forma_pagamento",
        }
        df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
        # Garante colunas
        for c in ["id_cobranca","nome_cliente","valor","data_vencimento","status_raw"]:
            if c not in df.columns:
                df[c] = None
        # Datas
        for dc in ["data_vencimento","data_pagamento","data_lancamento"]:
            if dc in df.columns:
                df[dc] = pd.to_datetime(df[dc], errors="coerce")
        # Valores
        for vc in ["valor","valor_pago"]:
            if vc in df.columns:
                df[vc] = pd.to_numeric(df[vc], errors="coerce").fillna(0).abs()
        # Status normalizado
        PAGO = {"pago","baixado_banco","baixado_pix","baixado_manual",
                "baixado_parcial","quitado","recebido","baixado_faturamento"}
        def _st(row):
            s = str(row.get("status_raw","")).lower().strip()
            if s in PAGO: return "PAGO"
            if pd.notna(row.get("data_vencimento")) and \
               pd.Timestamp(row["data_vencimento"]) < today: return "ATRASADO"
            return "A_VENCER"
        df["status"]       = df.apply(_st, axis=1)
        df["dias_atraso"]  = df["data_vencimento"].apply(
            lambda d: max(0, (today - pd.Timestamp(d)).days) if pd.notna(d) else 0)
        df["valor_pendente"]= df.apply(
            lambda r: 0.0 if r["status"]=="PAGO" else float(r.get("valor",0)), axis=1)
        # Remove intercompany
        if "nome_cliente" in df.columns:
            mask_ic = df["nome_cliente"].fillna("").str.upper().apply(
                lambda n: any(ic in n for ic in IC_NOMES))
            df = df[~mask_ic]
        return df.reset_index(drop=True)

    # ══════════════════════════════════════════════════════════════════
    # TUDO EM UMA CHAMADA — para o app
    # ══════════════════════════════════════════════════════════════════
    def importar_tudo(self, mes=None):
        """
        Importa TODOS os dados necessários para o app:
          - clientes
          - cobranças do mês (pagas + abertas + atrasadas + a vencer)
          - cobranças dos últimos 12 meses (para histórico de recebidos)
        Retorna dict com DataFrames prontos para uso no app.
        """
        if not mes:
            mes = datetime.now().strftime("%Y-%m")
        ano, m = map(int, mes.split("-"))
        ult_dia = calendar.monthrange(ano, m)[1]
        d_ini   = f"{mes}-01"
        d_fim   = f"{mes}-{ult_dia:02d}"

        # Cobranças do mês com vencimento
        cob_mes = self.get_cobrancas(d_ini, d_fim, tipo_data="vencimento")

        # Cobranças pagas no mês (por data de pagamento — captura pagamentos de meses anteriores)
        cob_rec = self.get_cobrancas(d_ini, d_fim, tipo_data="pagamento", pago=1)

        # Clientes ativos
        try:
            clientes = self.get_clientes("ativo")
        except Exception:
            clientes = pd.DataFrame()

        today = pd.Timestamp.now().normalize()

        # Separa cobranças do mês por status
        if not cob_mes.empty:
            pagas    = cob_mes[cob_mes["status"]=="PAGO"].copy()
            atrasadas= cob_mes[cob_mes["status"]=="ATRASADO"].copy()
            a_vencer = cob_mes[cob_mes["status"]=="A_VENCER"].copy()
        else:
            pagas = atrasadas = a_vencer = pd.DataFrame()

        # Monta rec_df (faturamento) — equivalente à planilha Hubsoft
        rec_df = cob_mes.copy() if not cob_mes.empty else pd.DataFrame()
        if not rec_df.empty:
            rec_df = rec_df.rename(columns={
                "nome_cliente": "nome_razaosocial",
                "id_cobranca":  "id_cobranca",
            })
            if "nome_razaosocial" not in rec_df.columns:
                rec_df["nome_razaosocial"] = "Cliente"
            rec_df["__val"]   = rec_df["valor"].fillna(0)
            rec_df["__venc"]  = rec_df["data_vencimento"]
            rec_df["__nome"]  = rec_df["nome_razaosocial"].fillna("").astype(str)
            rec_df["__pago"]  = rec_df["status"] == "PAGO"
            rec_df["__nome_c"]= rec_df["__nome"]

        # Monta rec_df_recebidos — equivalente ao extrato OFX
        # Usa cobranças pagas por data de pagamento (valor recebido real)
        rec_recebidos = pd.DataFrame()
        if not cob_rec.empty:
            rec_recebidos = pd.DataFrame({
                "__pagante": cob_rec.get("nome_cliente", pd.Series(dtype=str)).fillna("").astype(str),
                "__val":     cob_rec["valor"].fillna(0),
                "__data":    cob_rec.get("data_pagamento", pd.Series(dtype="datetime64[ns]")),
                "__memo":    cob_rec.get("descricao", pd.Series(dtype=str)).fillna(""),
            })
            rec_recebidos = rec_recebidos[rec_recebidos["__val"] > 0]

        # Totais
        faturado   = float(rec_df["__val"].sum()) if not rec_df.empty else 0.0
        recebido   = float(rec_recebidos["__val"].sum()) if not rec_recebidos.empty else 0.0
        atrasado_v = float(atrasadas["valor"].sum()) if not atrasadas.empty else 0.0
        a_vencer_v = float(a_vencer["valor"].sum()) if not a_vencer.empty else 0.0

        totais = {
            "faturado":      faturado,
            "recebido":      recebido,
            "atrasado":      atrasado_v,
            "a_vencer":      a_vencer_v,
            "n_cobrancas":   len(rec_df),
            "n_pagas":       len(pagas),
            "n_atrasadas":   len(atrasadas),
            "n_a_vencer":    len(a_vencer),
            "adimplencia":   round(len(pagas)/max(len(rec_df),1)*100,1) if not rec_df.empty else 0.0,
            "mes":           mes,
            "fonte":         "hubsoft_api",
            "atualizado_em": datetime.now().strftime("%d/%m/%Y %H:%M"),
        }

        return {
            # Para o app principal
            "rec_df":          rec_df,          # faturamento (como planilha Hubsoft)
            "rec_recebidos":   rec_recebidos,   # recebidos (como extrato)
            # Extras
            "clientes":        clientes,
            "cob_mes":         cob_mes,
            "pagas":           pagas,
            "atrasadas":       atrasadas,
            "a_vencer":        a_vencer,
            "totais":          totais,
        }

    # ══════════════════════════════════════════════════════════════════
    # CRUZAMENTO CLIENTE × FINANCEIRO
    # ══════════════════════════════════════════════════════════════════
    def cruzamento_clientes(self, cob_df=None, mes=None):
        if cob_df is None or cob_df.empty:
            data = self.importar_tudo(mes)
            cob_df = data["cob_mes"]
        if cob_df.empty:
            return pd.DataFrame()
        grp = cob_df.groupby("nome_cliente")
        cli = grp.agg(
            faturado   = ("valor",   "sum"),
            recebido   = ("valor",   lambda x: x[cob_df.loc[x.index,"status"]=="PAGO"].sum()),
            atrasado   = ("valor",   lambda x: x[cob_df.loc[x.index,"status"]=="ATRASADO"].sum()),
            a_vencer   = ("valor",   lambda x: x[cob_df.loc[x.index,"status"]=="A_VENCER"].sum()),
            n_cob      = ("valor",   "count"),
            n_pagas    = ("status",  lambda x: (x=="PAGO").sum()),
            n_atr      = ("status",  lambda x: (x=="ATRASADO").sum()),
            n_av       = ("status",  lambda x: (x=="A_VENCER").sum()),
        ).reset_index()
        cli["adimplencia_pct"] = (cli["recebido"]/cli["faturado"].replace(0,1)*100).round(1)
        return cli.sort_values("faturado", ascending=False)

