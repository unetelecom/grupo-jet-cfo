"""
HUBSOFT API — Grupo Jet Telecom
Auto-importação: clientes, cobranças pagas, abertas, atrasadas, a vencer.
Documentação: https://docs.hubsoft.com.br
"""
import requests
import pandas as pd
from datetime import datetime, timedelta
import calendar, time, re

IC_NOMES = {"RDMI", "RRD TELECOM", "GRUPO JET", "JET TELECOM", "RD TELECOM"}

OAUTH_PATHS = [
    "/oauth/token",
    "/api/oauth/token",
    "/oauth/access-token",
    "/api/v1/oauth/token",
    "/api/v1/auth/token",
    "/login",
    "/api/login",
]


def _base_urls(base):
    """
    Gera variações da base URL para tentar na autenticação.
    A URL exata fornecida é sempre a primeira tentativa.
    """
    urls = [base.rstrip("/")]
    # Tenta sem trailing /api (caso o usuário tenha colocado /api extra)
    clean = re.sub(r"/api/?$", "", base.rstrip("/"))
    if clean not in urls:
        urls.append(clean)
    # Tenta com /api appended
    no_api = clean
    if not no_api.endswith("/api"):
        candidate = no_api + "/api"
        if candidate not in urls:
            urls.append(candidate)
    return urls


def autenticar_hubsoft(base_url, client_id, client_secret, username, password):
    """
    Descobre automaticamente o endpoint OAuth correto do Hubsoft.
    Testa form-urlencoded e JSON em múltiplos paths e base URLs.
    Retorna (token, base_url_funcionou, path_funcionou) ou lança ConnectionError.
    """
    body = {
        "grant_type":    "password",
        "client_id":     str(client_id),
        "client_secret": client_secret,
        "username":      username,
        "password":      password,
    }
    errors = []
    s = requests.Session()
    s.headers["Accept"] = "application/json"

    for base in _base_urls(base_url):
        for path in OAUTH_PATHS:
            url = f"{base}{path}"
            for ct_name, ct_header, kw in [
                ("form", "application/x-www-form-urlencoded", {"data":  body}),
                ("json", "application/json",                  {"json":  body}),
            ]:
                try:
                    s.headers["Content-Type"] = ct_header
                    r = s.post(url, timeout=15, **kw)
                    if r.status_code == 404:
                        errors.append(f"404 {base}{path}")
                        break   # endpoint não existe, vai para próximo path
                    if r.status_code == 405:
                        errors.append(f"405 {base}{path} ({ct_name})")
                        continue
                    if r.status_code not in (200, 201):
                        errors.append(
                            f"{r.status_code} {base}{path} ({ct_name}): "
                            f"{r.text[:60].replace(chr(10),' ')}"
                        )
                        continue
                    data = r.json()
                    tok = data.get("access_token") or data.get("token")
                    if not tok:
                        errors.append(f"sem_token {base}{path}: {str(data)[:60]}")
                        continue
                    # Sucesso!
                    return tok, base, path
                except requests.exceptions.ConnectionError as ce:
                    errors.append(f"conn_err {base}: {str(ce)[:60]}")
                    break   # não tem rede para este base, tenta próximo base
                except Exception as ex:
                    errors.append(f"err {base}{path}: {type(ex).__name__}:{str(ex)[:60]}")

    raise ConnectionError(
        "Hubsoft: falha em todos os endpoints testados.\n"
        + "\n".join(f"  {e}" for e in errors[:20])
    )


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
        self._base_ativo   = base_url
        self.s             = requests.Session()
        self.s.headers["Accept"] = "application/json"

    def autenticar(self):
        tok, base, path = autenticar_hubsoft(
            self.base_url, self.client_id,
            self.client_secret, self.username, self.password
        )
        self.token        = tok
        self._base_ativo  = base
        self.token_expiry = datetime.now() + timedelta(seconds=3540)
        self.s.headers["Authorization"] = f"Bearer {self.token}"
        return self.token

    def _ok_token(self):
        if not self.token or datetime.now() >= (self.token_expiry or datetime.min):
            self.autenticar()

    # Variações de prefixo de endpoint para tentar em caso de 404
    ENDPOINT_PREFIXES = ["", "/api", "/v1", "/api/v1"]

    def _get(self, endpoint, params=None, tentativas=3):
        self._ok_token()
        # Remove /api/v1 prefix se o servidor já tem isso na base
        url = f"{self._base_ativo}{endpoint}"
        for t in range(tentativas):
            try:
                r = self.s.get(url, params=params or {}, timeout=30)
                if r.status_code == 401:
                    self.autenticar()
                    r = self.s.get(url, params=params or {}, timeout=30)
                if r.status_code == 404:
                    # Tenta variações do prefixo
                    ep_clean = endpoint.lstrip("/")
                    # Remove prefixos comuns e tenta de novo
                    for strip in ["api/v1/integracao/","api/v1/","v1/integracao/","v1/"]:
                        if ep_clean.startswith(strip):
                            alt_ep = "/" + ep_clean[len(strip):]
                            alt_url = f"{self._base_ativo}{alt_ep}"
                            r2 = self.s.get(alt_url, params=params or {}, timeout=30)
                            if r2.status_code != 404:
                                print(f"  → usando endpoint alternativo: {alt_ep}")
                                r2.raise_for_status()
                                return r2.json()
                r.raise_for_status()
                return r.json()
            except requests.exceptions.Timeout:
                if t == tentativas - 1:
                    raise
                time.sleep(2 ** t)

    def _paginar(self, endpoint, params=None, limit=100, max_pag=200):
        p = dict(params or {})
        p["pagina"]          = 0
        p["itens_por_pagina"]= limit   # Hubsoft usa itens_por_pagina, não limit
        dados = []
        for _ in range(max_pag):
            resp  = self._get(endpoint, p)
            bloco = (resp.get("dados") or resp.get("data") or
                     resp.get("clientes") or resp.get("contratos") or
                     resp.get("faturas") or resp.get("cobrancas") or [])
            if isinstance(bloco, list):
                dados.extend(bloco)
            elif isinstance(bloco, dict) and bloco:
                dados.append(bloco)
            pag    = resp.get("paginacao") or {}
            ultima = pag.get("ultima_pagina",  0)
            atual  = pag.get("pagina_atual",   p["pagina"])
            if not bloco or atual >= ultima:
                break
            p["pagina"] = atual + 1
        return dados

    def descobrir_endpoints(self):
        """
        Testa os endpoints mais comuns e retorna quais respondem 200.
        Use para diagnosticar qual versão/configuração do Hubsoft está ativa.
        """
        self._ok_token()
        candidatos = [
            "/api/v1/integracao/financeiro/fatura",
            "/api/v1/integracao/financeiro/cobranca",
            "/api/v1/integracao/cliente/financeiro",
            "/api/v1/integracao/cliente",
            "/api/v1/integracao/contrato",
            "/api/v1/integracao/plano",
            "/api/v1/integracao/financeiro",
            "/api/v1/integracao",
            "/api/v1",
        ]
        resultado = {}
        for ep in candidatos:
            url = f"{self._base_ativo}{ep}"
            try:
                r = self.s.get(url, params={"pagina":0,"itens_por_pagina":1}, timeout=10)
                resultado[ep] = r.status_code
            except Exception as e:
                resultado[ep] = str(e)[:40]
        return resultado

    # ── CLIENTES ─────────────────────────────────────────────────────
    CLIENTE_ENDPOINTS = [
        "/api/v1/integracao/cliente",
        "/api/v1/cliente",
        "/cliente",
    ]

    def get_clientes(self, status="ativo"):
        params = {} if status == "todos" else {"status": status}
        for ep in self.CLIENTE_ENDPOINTS:
            try:
                dados = self._paginar(ep, params)
                if dados:
                    break
            except Exception as e:
                if "404" in str(e) or "Not Found" in str(e):
                    continue
                raise
        else:
            return pd.DataFrame()
        if not dados:
            return pd.DataFrame()
        df = pd.json_normalize(dados)
        rename = {
            "id":               "id_cliente",
            "nome_razaosocial": "nome",
            "cpf_cnpj":         "cpf_cnpj",
            "email":            "email",
            "telefone":         "telefone",
            "status":           "status",
            "data_cadastro":    "data_cadastro",
            "endereco.cidade":  "cidade",
            "endereco.estado":  "estado",
        }
        return df.rename(columns={k:v for k,v in rename.items() if k in df.columns})

    # ── COBRANÇAS ─────────────────────────────────────────────────────
    # Endpoints alternativos de cobranças/faturas (tenta em ordem)
    COBRANCA_ENDPOINTS = [
        "/api/v1/integracao/financeiro/fatura",      # ← funciona neste servidor
        "/api/v1/integracao/financeiro/cobranca",
        "/api/v1/integracao/cliente/financeiro",
        "/financeiro/fatura",
        "/financeiro/cobranca",
    ]

    def get_cobrancas(self, data_ini, data_fim,
                      tipo_data="vencimento", pago=None):
        params = {
            f"data_{tipo_data}_ini": data_ini,
            f"data_{tipo_data}_fim": data_fim,
        }
        if pago is not None:
            params["pago"] = int(pago)

        # Tenta cada endpoint até achar um que funcione
        last_err = None
        for ep in self.COBRANCA_ENDPOINTS:
            try:
                dados = self._paginar(ep, params)
                if dados:
                    print(f"  ✅ Cobranças via: {ep} ({len(dados)} registros)")
                    return self._norm_cobrancas(pd.json_normalize(dados))
            except Exception as e:
                last_err = e
                if "404" in str(e) or "Not Found" in str(e):
                    continue  # tenta próximo endpoint
                raise  # outro erro — propaga

        if last_err:
            raise last_err
        return pd.DataFrame()

    FATURA_ENDPOINTS = [
        "/api/v1/integracao/financeiro/fatura",
        "/api/v1/integracao/financeiro/cobranca",
        "/api/v1/integracao/cliente/financeiro",
        "/financeiro/fatura",
    ]

    def get_faturas(self, data_ini, data_fim, status_pag=None):
        params = {
            "data_vencimento_ini": data_ini,
            "data_vencimento_fim": data_fim,
        }
        if status_pag:
            params["status_pagamento"] = status_pag
        for ep in self.FATURA_ENDPOINTS:
            try:
                dados = self._paginar(ep, params)
                if dados:
                    df = pd.json_normalize(dados)
                    for dc in ["data_vencimento","data_pagamento"]:
                        if dc in df.columns:
                            df[dc] = pd.to_datetime(df[dc], errors="coerce")
                    for vc in ["valor_total","valor_pago"]:
                        if vc in df.columns:
                            df[vc] = pd.to_numeric(df[vc], errors="coerce").fillna(0).abs()
                    return df
            except Exception as e:
                if "404" in str(e) or "Not Found" in str(e):
                    continue
                raise
        return pd.DataFrame()

    # ── Normaliza cobranças ───────────────────────────────────────────
    @staticmethod
    def _norm_cobrancas(df):
        if df.empty:
            return df
        today = pd.Timestamp.now().normalize()
        rename = {
            "id":                       "id_cobranca",
            "id_cliente":               "id_cliente",
            "nome_razaosocial":         "nome_cliente",
            "cliente.nome_razaosocial": "nome_cliente",
            "cliente.nome":             "nome_cliente",
            "valor":                    "valor",
            "valor_pago":               "valor_pago",
            "data_vencimento":          "data_vencimento",
            "data_pagamento":           "data_pagamento",
            "data_lancamento":          "data_lancamento",
            "status":                   "status_raw",
            "descricao":                "descricao",
            "servico":                  "servico",
            "forma_pagamento":          "forma_pagamento",
        }
        df = df.rename(columns={k:v for k,v in rename.items() if k in df.columns})
        for c in ["id_cobranca","nome_cliente","valor","data_vencimento","status_raw"]:
            if c not in df.columns:
                df[c] = None
        for dc in ["data_vencimento","data_pagamento","data_lancamento"]:
            if dc in df.columns:
                df[dc] = pd.to_datetime(df[dc], errors="coerce")
        for vc in ["valor","valor_pago"]:
            if vc in df.columns:
                df[vc] = pd.to_numeric(df[vc], errors="coerce").fillna(0).abs()
        PAGO = {"pago","baixado_banco","baixado_pix","baixado_manual",
                "baixado_parcial","quitado","recebido","baixado_faturamento"}
        def _st(row):
            s = str(row.get("status_raw","")).lower().strip()
            if s in PAGO: return "PAGO"
            d = row.get("data_vencimento")
            if pd.notna(d) and pd.Timestamp(d) < today: return "ATRASADO"
            return "A_VENCER"
        df["status"]         = df.apply(_st, axis=1)
        df["dias_atraso"]    = df["data_vencimento"].apply(
            lambda d: max(0,(today - pd.Timestamp(d)).days) if pd.notna(d) else 0)
        df["valor_pendente"] = df.apply(
            lambda r: 0.0 if r["status"]=="PAGO" else float(r.get("valor",0)), axis=1)
        if "nome_cliente" in df.columns:
            mask = df["nome_cliente"].fillna("").str.upper().apply(
                lambda n: any(ic in n for ic in IC_NOMES))
            df = df[~mask]
        return df.reset_index(drop=True)

    # ── IMPORTAR TUDO ─────────────────────────────────────────────────
    def importar_tudo(self, mes=None):
        if not mes:
            mes = datetime.now().strftime("%Y-%m")
        ano, m   = map(int, mes.split("-"))
        ult_dia  = calendar.monthrange(ano, m)[1]
        d_ini    = f"{mes}-01"
        d_fim    = f"{mes}-{ult_dia:02d}"

        # Busca TODAS as cobranças do mês (pagas + abertas + atrasadas)
        # Sem filtro de status para pegar tudo
        cob_mes = self.get_cobrancas(d_ini, d_fim, tipo_data="vencimento")

        # Busca também recebimentos do mês por data de pagamento
        # (captura pagamentos de cobranças de meses anteriores)
        cob_rec = self.get_cobrancas(d_ini, d_fim, tipo_data="pagamento", pago=True)

        # Se cob_mes retornou vazio, tenta sem filtro de data de vencimento
        # usando data de lançamento
        if cob_mes.empty:
            cob_mes = self.get_cobrancas(d_ini, d_fim, tipo_data="lancamento")
        try:    clientes = self.get_clientes("ativo")
        except: clientes = pd.DataFrame()

        pagas     = cob_mes[cob_mes["status"]=="PAGO"]     if not cob_mes.empty else pd.DataFrame()
        atrasadas = cob_mes[cob_mes["status"]=="ATRASADO"] if not cob_mes.empty else pd.DataFrame()
        a_vencer  = cob_mes[cob_mes["status"]=="A_VENCER"] if not cob_mes.empty else pd.DataFrame()

        rec_df = pd.DataFrame()
        if not cob_mes.empty:
            rec_df = cob_mes.rename(columns={"nome_cliente":"nome_razaosocial"}).copy()
            rec_df["__val"]    = pd.to_numeric(rec_df.get("valor",0), errors="coerce").fillna(0)
            rec_df["__venc"]   = rec_df.get("data_vencimento")
            rec_df["__nome"]   = rec_df.get("nome_razaosocial","").fillna("").astype(str)
            rec_df["__pago"]   = rec_df["status"] == "PAGO"
            rec_df["__nome_c"] = rec_df["__nome"]

        rec_recebidos = pd.DataFrame()
        if not cob_rec.empty:
            rec_recebidos = pd.DataFrame({
                "__pagante": cob_rec.get("nome_cliente", pd.Series(dtype=str)).fillna(""),
                "__val":     pd.to_numeric(cob_rec.get("valor",0), errors="coerce").fillna(0),
                "__data":    cob_rec.get("data_pagamento", pd.Series(dtype="datetime64[ns]")),
                "__memo":    cob_rec.get("descricao", pd.Series(dtype=str)).fillna(""),
            })
            rec_recebidos = rec_recebidos[rec_recebidos["__val"] > 0]

        totais = {
            "faturado":     float(cob_mes["valor"].sum()) if not cob_mes.empty else 0.0,
            "recebido":     float(rec_recebidos["__val"].sum()) if not rec_recebidos.empty else 0.0,
            "atrasado":     float(atrasadas["valor"].sum()) if not atrasadas.empty else 0.0,
            "a_vencer":     float(a_vencer["valor"].sum()) if not a_vencer.empty else 0.0,
            "n_cobrancas":  len(cob_mes),
            "n_pagas":      len(pagas),
            "n_atrasadas":  len(atrasadas),
            "n_a_vencer":   len(a_vencer),
            "n_clientes":   len(clientes),
            "adimplencia":  round(len(pagas)/max(len(cob_mes),1)*100,1),
            "mes":          mes,
            "fonte":        "hubsoft_api",
            "atualizado_em":datetime.now().strftime("%d/%m/%Y %H:%M"),
        }
        return {
            "rec_df":        rec_df,
            "rec_recebidos": rec_recebidos,
            "clientes":      clientes,
            "cob_mes":       cob_mes,
            "pagas":         pagas,
            "atrasadas":     atrasadas,
            "a_vencer":      a_vencer,
            "totais":        totais,
        }

    def cruzamento_clientes(self, cob_df=None, mes=None):
        if cob_df is None or (hasattr(cob_df,"empty") and cob_df.empty):
            cob_df = self.importar_tudo(mes)["cob_mes"]
        if cob_df.empty:
            return pd.DataFrame()
        g = cob_df.groupby("nome_cliente")
        cli = g.agg(
            faturado =("valor","sum"),
            recebido =("valor", lambda x: x[cob_df.loc[x.index,"status"]=="PAGO"].sum()),
            atrasado =("valor", lambda x: x[cob_df.loc[x.index,"status"]=="ATRASADO"].sum()),
            a_vencer =("valor", lambda x: x[cob_df.loc[x.index,"status"]=="A_VENCER"].sum()),
            n_cob    =("valor","count"),
            n_pagas  =("status",lambda x:(x=="PAGO").sum()),
            n_atr    =("status",lambda x:(x=="ATRASADO").sum()),
        ).reset_index()
        cli["adimplencia_pct"] = (cli["recebido"]/cli["faturado"].replace(0,1)*100).round(1)
        return cli.sort_values("faturado",ascending=False)

