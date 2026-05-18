"""
HUBSOFT API CONNECTOR — Grupo Jet Telecom
Integração com a API oficial do Hubsoft para importar:
 - Clientes
 - Cobranças pagas
 - Cobranças em aberto (atrasadas + a vencer)
 - Faturas

Documentação: https://docs.hubsoft.com.br
Autenticação: OAuth2 (client_credentials)
"""

import requests
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional


# ══════════════════════════════════════════════════════════════════════
# CLIENTE HUBSOFT
# ══════════════════════════════════════════════════════════════════════
class HubsoftAPI:
    """
    Cliente da API Hubsoft.

    Uso:
        hub = HubsoftAPI(
            base_url  = "https://jettelecom.hubsoft.com.br",
            client_id = "89",
            client_secret = "ONe7Ns48Y30tB",
            username  = "api@grupojet.com",
            password  = "senha",
        )
        hub.autenticar()
        clientes  = hub.get_clientes()
        cobrancas = hub.get_cobrancas_periodo("2026-05-01", "2026-05-31")
    """

    def __init__(self, base_url: str, client_id: str, client_secret: str,
                 username: str, password: str):
        self.base_url      = base_url.rstrip("/")
        self.client_id     = client_id
        self.client_secret = client_secret
        self.username      = username
        self.password      = password
        self.token         = None
        self.token_expiry  = None
        self.session       = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json",
            "Accept":       "application/json",
        })

    # ─── AUTENTICAÇÃO ────────────────────────────────────────────────
    def autenticar(self) -> bool:
        """OAuth2 client_credentials — obtém Bearer token."""
        url = f"{self.base_url}/oauth/token"
        payload = {
            "grant_type":    "password",
            "client_id":     self.client_id,
            "client_secret": self.client_secret,
            "username":      self.username,
            "password":      self.password,
        }
        try:
            r = self.session.post(url, json=payload, timeout=30)
            r.raise_for_status()
            data = r.json()
            self.token = data.get("access_token") or data.get("token")
            expires_in = data.get("expires_in", 3600)
            self.token_expiry = datetime.now() + timedelta(seconds=expires_in - 60)
            self.session.headers["Authorization"] = f"Bearer {self.token}"
            return True
        except Exception as e:
            raise ConnectionError(f"Falha na autenticação Hubsoft: {e}")

    def _garantir_token(self):
        """Renova o token se expirado."""
        if not self.token or (self.token_expiry and datetime.now() >= self.token_expiry):
            self.autenticar()

    # ─── REQUEST GENÉRICO ────────────────────────────────────────────
    def _get(self, endpoint: str, params: dict = None) -> dict:
        self._garantir_token()
        url = f"{self.base_url}{endpoint}"
        r = self.session.get(url, params=params or {}, timeout=30)
        r.raise_for_status()
        return r.json()

    def _get_paginado(self, endpoint: str, params: dict = None,
                      max_paginas: int = 50) -> list:
        """Percorre todas as páginas e retorna lista consolidada."""
        dados = []
        p = dict(params or {})
        p.setdefault("pagina", 0)
        p.setdefault("limit",  100)

        for _ in range(max_paginas):
            resp = self._get(endpoint, p)
            registros = resp.get("dados") or resp.get("data") or resp.get("clientes") or []
            if isinstance(registros, list):
                dados.extend(registros)
            elif isinstance(registros, dict):
                dados.append(registros)

            pag = resp.get("paginacao") or {}
            ultima = pag.get("ultima_pagina", 0)
            atual  = pag.get("pagina_atual",  p["pagina"])
            if atual >= ultima:
                break
            p["pagina"] = atual + 1

        return dados

    # ══════════════════════════════════════════════════════════════════
    # CLIENTES
    # ══════════════════════════════════════════════════════════════════
    def get_clientes(self, status: str = "ativo") -> pd.DataFrame:
        """
        Lista todos os clientes.
        status: 'ativo' | 'inativo' | 'todos'
        """
        params = {}
        if status != "todos":
            params["status"] = status

        dados = self._get_paginado(
            "/api/v1/integracao/cliente",
            params=params
        )

        if not dados:
            return pd.DataFrame()

        df = pd.json_normalize(dados)

        # Padroniza colunas úteis
        rename = {
            "id":                     "id_cliente",
            "nome_razaosocial":       "nome",
            "cpf_cnpj":               "cpf_cnpj",
            "email":                  "email",
            "telefone":               "telefone",
            "status":                 "status",
            "data_cadastro":          "data_cadastro",
            "endereco.cidade":        "cidade",
            "endereco.estado":        "estado",
        }
        df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
        return df

    # ══════════════════════════════════════════════════════════════════
    # COBRANÇAS
    # ══════════════════════════════════════════════════════════════════
    def get_cobrancas_periodo(self, data_ini: str, data_fim: str,
                              status: str = None) -> pd.DataFrame:
        """
        Cobranças por período de vencimento.
        status: None=todos | 'aberto' | 'pago' | 'atrasado'
        data_ini / data_fim: 'YYYY-MM-DD'
        """
        params = {
            "data_vencimento_ini": data_ini,
            "data_vencimento_fim": data_fim,
        }
        if status:
            params["status"] = status

        dados = self._get_paginado(
            "/api/v1/integracao/financeiro/cobranca",
            params=params
        )

        if not dados:
            return pd.DataFrame()

        df = pd.json_normalize(dados)
        return self._normalizar_cobrancas(df)

    def get_cobrancas_pagas(self, data_ini: str, data_fim: str) -> pd.DataFrame:
        """Cobranças pagas no período."""
        return self.get_cobrancas_periodo(data_ini, data_fim, status="pago")

    def get_cobrancas_abertas(self) -> pd.DataFrame:
        """Cobranças em aberto (atrasadas + a vencer)."""
        hoje = datetime.now()
        data_ini = (hoje - timedelta(days=365)).strftime("%Y-%m-%d")
        data_fim = (hoje + timedelta(days=90)).strftime("%Y-%m-%d")

        # Busca atrasadas e a vencer separadamente
        params_base = {
            "data_vencimento_ini": data_ini,
            "data_vencimento_fim": data_fim,
        }
        dados = self._get_paginado(
            "/api/v1/integracao/financeiro/cobranca",
            params={**params_base, "status": "aberto"}
        )
        if not dados:
            return pd.DataFrame()
        df = pd.json_normalize(dados)
        return self._normalizar_cobrancas(df)

    def get_cobrancas_atrasadas(self) -> pd.DataFrame:
        """Cobranças vencidas e não pagas."""
        df = self.get_cobrancas_abertas()
        if df.empty:
            return df
        hoje = pd.Timestamp.now().normalize()
        return df[df["data_vencimento"] < hoje].copy()

    def get_cobrancas_a_vencer(self, dias: int = 30) -> pd.DataFrame:
        """Cobranças que vencem nos próximos N dias."""
        df = self.get_cobrancas_abertas()
        if df.empty:
            return df
        hoje  = pd.Timestamp.now().normalize()
        limit = hoje + pd.Timedelta(days=dias)
        return df[(df["data_vencimento"] >= hoje) & (df["data_vencimento"] <= limit)].copy()

    # ══════════════════════════════════════════════════════════════════
    # FATURAS
    # ══════════════════════════════════════════════════════════════════
    def get_faturas_periodo(self, data_ini: str, data_fim: str,
                            status_pagamento: str = None) -> pd.DataFrame:
        """
        Faturas por período.
        status_pagamento: None=todas | 'pago' | 'aberto'
        """
        params = {
            "data_vencimento_ini": data_ini,
            "data_vencimento_fim": data_fim,
        }
        if status_pagamento:
            params["status_pagamento"] = status_pagamento

        dados = self._get_paginado(
            "/api/v1/integracao/financeiro/fatura",
            params=params
        )

        if not dados:
            return pd.DataFrame()

        df = pd.json_normalize(dados)
        return self._normalizar_faturas(df)

    # ══════════════════════════════════════════════════════════════════
    # NORMALIZADORES
    # ══════════════════════════════════════════════════════════════════
    @staticmethod
    def _normalizar_cobrancas(df: pd.DataFrame) -> pd.DataFrame:
        """Padroniza o DataFrame de cobranças."""
        if df.empty:
            return df

        today = pd.Timestamp.now().normalize()

        # Renomeia campos comuns da API Hubsoft
        rename = {
            "id":                           "id_cobranca",
            "id_cliente":                   "id_cliente",
            "nome_razaosocial":             "nome_cliente",
            "cliente.nome_razaosocial":     "nome_cliente",
            "valor":                        "valor",
            "valor_pago":                   "valor_pago",
            "data_vencimento":              "data_vencimento",
            "data_pagamento":               "data_pagamento",
            "status":                       "status_raw",
            "descricao":                    "descricao",
            "servico":                      "servico",
        }
        df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})

        # Garante colunas essenciais
        for col in ["id_cobranca","nome_cliente","valor","data_vencimento","status_raw"]:
            if col not in df.columns:
                df[col] = None

        # Parse de datas
        for dcol in ["data_vencimento","data_pagamento"]:
            if dcol in df.columns:
                df[dcol] = pd.to_datetime(df[dcol], errors="coerce")

        # Parse de valores
        for vcol in ["valor","valor_pago"]:
            if vcol in df.columns:
                df[vcol] = pd.to_numeric(df[vcol], errors="coerce").fillna(0).abs()

        # Classificação de status
        STATUS_PAGO = {"pago","baixado_banco","baixado_pix","baixado_manual",
                       "baixado_parcial","quitado","recebido"}

        def classif(row):
            s = str(row.get("status_raw","")).lower()
            if s in STATUS_PAGO: return "PAGO"
            venc = row.get("data_vencimento")
            if pd.notna(venc) and pd.Timestamp(venc) < today: return "ATRASADO"
            return "A_VENCER"

        df["status"] = df.apply(classif, axis=1)
        df["dias_atraso"] = df["data_vencimento"].apply(
            lambda d: max(0, (today - pd.Timestamp(d)).days) if pd.notna(d) else 0
        )
        df["valor_pendente"] = df.apply(
            lambda r: 0.0 if r["status"]=="PAGO" else float(r.get("valor",0)),
            axis=1
        )

        return df

    @staticmethod
    def _normalizar_faturas(df: pd.DataFrame) -> pd.DataFrame:
        """Padroniza o DataFrame de faturas."""
        if df.empty: return df
        rename = {
            "id":                        "id_fatura",
            "id_cliente":                "id_cliente",
            "nome_razaosocial":          "nome_cliente",
            "cliente.nome_razaosocial":  "nome_cliente",
            "valor_total":               "valor_total",
            "valor_pago":                "valor_pago",
            "data_vencimento":           "data_vencimento",
            "data_pagamento":            "data_pagamento",
            "status_pagamento":          "status",
            "numero_fatura":             "numero_fatura",
        }
        df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
        for dcol in ["data_vencimento","data_pagamento"]:
            if dcol in df.columns:
                df[dcol] = pd.to_datetime(df[dcol], errors="coerce")
        for vcol in ["valor_total","valor_pago"]:
            if vcol in df.columns:
                df[vcol] = pd.to_numeric(df[vcol], errors="coerce").fillna(0).abs()
        return df

    # ══════════════════════════════════════════════════════════════════
    # CONSOLIDADO FINANCEIRO (pré-processado para o app)
    # ══════════════════════════════════════════════════════════════════
    def get_financeiro_consolidado(self, mes: str = None) -> dict:
        """
        Retorna tudo que o app precisa em uma chamada só.
        mes: 'YYYY-MM' (default = mês atual)
        """
        if not mes:
            mes = datetime.now().strftime("%Y-%m")
        ano, m = mes.split("-")
        import calendar
        ultimo_dia = calendar.monthrange(int(ano), int(m))[1]
        data_ini = f"{mes}-01"
        data_fim = f"{mes}-{ultimo_dia:02d}"

        cobrancas = self.get_cobrancas_periodo(data_ini, data_fim)

        if cobrancas.empty:
            return {
                "cobrancas": pd.DataFrame(),
                "pagas": pd.DataFrame(),
                "atrasadas": pd.DataFrame(),
                "a_vencer": pd.DataFrame(),
                "totais": {},
            }

        today = pd.Timestamp.now().normalize()
        pagas    = cobrancas[cobrancas["status"]=="PAGO"]
        atrasadas= cobrancas[cobrancas["status"]=="ATRASADO"]
        a_vencer = cobrancas[cobrancas["status"]=="A_VENCER"]

        totais = {
            "faturado":    float(cobrancas["valor"].sum()),
            "recebido":    float(pagas["valor"].sum()),
            "atrasado":    float(atrasadas["valor"].sum()),
            "a_vencer":    float(a_vencer["valor"].sum()),
            "n_cobrancas": len(cobrancas),
            "n_pagas":     len(pagas),
            "n_atrasadas": len(atrasadas),
            "n_a_vencer":  len(a_vencer),
            "adimplencia": round(len(pagas)/max(len(cobrancas),1)*100, 1),
        }

        return {
            "cobrancas": cobrancas,
            "pagas":     pagas,
            "atrasadas": atrasadas,
            "a_vencer":  a_vencer,
            "totais":    totais,
        }

    # ══════════════════════════════════════════════════════════════════
    # CRUZAMENTO CLIENTE × COBRANÇAS
    # ══════════════════════════════════════════════════════════════════
    def get_cruzamento_clientes(self, mes: str = None) -> pd.DataFrame:
        """
        Retorna DataFrame com cruzamento por cliente:
        nome | faturado | recebido | atrasado | a_vencer | adimplencia%
        """
        fin = self.get_financeiro_consolidado(mes)
        df  = fin.get("cobrancas", pd.DataFrame())
        if df.empty:
            return pd.DataFrame()

        grp = df.groupby("nome_cliente").agg(
            faturado  = ("valor",       "sum"),
            recebido  = ("valor",       lambda x: x[df.loc[x.index,"status"]=="PAGO"].sum()),
            atrasado  = ("valor",       lambda x: x[df.loc[x.index,"status"]=="ATRASADO"].sum()),
            a_vencer  = ("valor",       lambda x: x[df.loc[x.index,"status"]=="A_VENCER"].sum()),
            n_cob     = ("valor",       "count"),
            n_pagas   = ("status",      lambda x: (x=="PAGO").sum()),
            n_atr     = ("status",      lambda x: (x=="ATRASADO").sum()),
        ).reset_index()

        grp["adimplencia_pct"] = (grp["recebido"] / grp["faturado"].replace(0,1) * 100).round(1)
        return grp.sort_values("faturado", ascending=False)

