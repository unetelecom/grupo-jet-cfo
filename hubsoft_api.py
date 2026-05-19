"""
HUBSOFT API — Grupo Jet Telecom
Auto-importação: clientes, cobranças pagas, abertas, atrasadas, a vencer.
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
]


def _base_urls(base):
    urls = [base.rstrip("/")]
    clean = re.sub(r"/api/?$", "", base.rstrip("/"))
    if clean not in urls:
        urls.append(clean)
    if not clean.endswith("/api"):
        candidate = clean + "/api"
        if candidate not in urls:
            urls.append(candidate)
    return urls


def autenticar_hubsoft(base_url, client_id, client_secret, username, password):
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
                        break
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
                    return tok, base, path
                except requests.exceptions.ConnectionError as ce:
                    errors.append(f"conn_err {base}: {str(ce)[:60]}")
                    break
                except Exception as ex:
                    errors.append(f"err {base}{path}: {type(ex).__name__}:{str(ex)[:60]}")

    raise ConnectionError(
        "Hubsoft: falha em todos os endpoints testados.\n"
        + "\n".join(f"  {e}" for e in errors[:20])
    )


class HubsoftAPI:

    # Endpoints confirmados pelo diagnóstico:
    # /api/v1/integracao/financeiro        → 200, 190 registros, chave: "faturas"
    # /api/v1/integracao/financeiro/fatura → 200, 190 registros, chave: "dados"
    COBRANCA_ENDPOINTS = [
        "/api/v1/integracao/financeiro/fatura",   # ✅ confirmado
        "/api/v1/integracao/financeiro",          # ✅ confirmado (chave "faturas")
        "/api/v1/integracao/financeiro/cobranca", # 404 neste servidor
        "/api/v1/integracao/cliente/financeiro",  # 200 mas sem dados paginados
    ]

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

    def _get(self, endpoint, params=None, tentativas=3):
        self._ok_token()
        url = f"{self._base_ativo}{endpoint}"
        for t in range(tentativas):
            try:
                r = self.s.get(url, params=params or {}, timeout=30)
                if r.status_code == 401:
                    self.autenticar()
                    r = self.s.get(url, params=params or {}, timeout=30)
                if r.status_code == 404:
                    raise requests.exceptions.HTTPError(f"404 Not Found: {url}")
                r.raise_for_status()
                return r.json()
            except requests.exceptions.Timeout:
                if t == tentativas - 1:
                    raise
                time.sleep(2 ** t)

    def _paginar(self, endpoint, params=None, limit=100, max_pag=500):
        p = dict(params or {})
        p["pagina"]           = 0
        p["itens_por_pagina"] = limit
        dados          = []
        total_esperado = None

        for n_pag in range(max_pag):
            resp = self._get(endpoint, p)
            pag  = resp.get("paginacao") or {}

            # ── Extrai bloco de dados ──────────────────────────────────
            bloco = (
                resp.get("dados") or resp.get("data") or
                resp.get("clientes") or resp.get("contratos") or
                resp.get("faturas") or resp.get("cobrancas") or []
            )

            # Loga na primeira página
            if n_pag == 0:
                total_esperado = pag.get("total_registros", "?")
                ultima_pag     = pag.get("ultima_pagina", 0)
                print(f"  Resp keys: {list(resp.keys())}")
                print(f"  Paginacao: total={total_esperado} paginas={ultima_pag+1} itens/pag={limit}")
                if not bloco:
                    print(f"  ATENCAO bloco vazio: {str(resp)[:300]}")

            if isinstance(bloco, list):
                dados.extend(bloco)
            elif isinstance(bloco, dict) and bloco:
                dados.append(bloco)

            ultima = pag.get("ultima_pagina", 0)
            atual  = pag.get("pagina_atual",  p["pagina"])
            if not bloco or atual >= ultima:
                break
            p["pagina"] = atual + 1

        total_str = str(total_esperado) if total_esperado else "?"
        print(f"  Total carregado: {len(dados)}" +
              (f" de {total_str}" if total_str != "?" else ""))
        return dados

    # ── CLIENTES ─────────────────────────────────────────────────────
    def get_clientes(self, status="ativo"):
        params = {} if status == "todos" else {"status": status}
        for ep in ["/api/v1/integracao/cliente", "/api/v1/cliente"]:
            try:
                dados = self._paginar(ep, params)
                if dados:
                    df = pd.json_normalize(dados)
                    rename = {
                        "id": "id_cliente", "nome_razaosocial": "nome",
                        "cpf_cnpj": "cpf_cnpj", "email": "email",
                        "telefone": "telefone", "status": "status",
                        "data_cadastro": "data_cadastro",
                        "endereco.cidade": "cidade", "endereco.estado": "estado",
                    }
                    return df.rename(columns={k:v for k,v in rename.items() if k in df.columns})
            except Exception as e:
                if "404" in str(e): continue
                raise
        return pd.DataFrame()

    # ── COBRANÇAS ─────────────────────────────────────────────────────
    def get_cobrancas(self, data_ini, data_fim,
                      tipo_data="vencimento", pago=None, status_pag=None):
        # Monta params — tenta variações de nome de campo de data
        params_vencimento = {
            "data_vencimento_ini": data_ini,
            "data_vencimento_fim": data_fim,
        }
        params_lancamento = {
            "data_lancamento_ini": data_ini,
            "data_lancamento_fim": data_fim,
        }
        params_criacao = {
            "data_criacao_ini": data_ini,
            "data_criacao_fim": data_fim,
        }
        params_custom = {
            f"data_{tipo_data}_ini": data_ini,
            f"data_{tipo_data}_fim": data_fim,
        }
        if pago is not None:
            for p in [params_vencimento, params_lancamento, params_criacao, params_custom]:
                p["pago"] = int(pago)
        if status_pag:
            for p in [params_vencimento, params_lancamento, params_criacao, params_custom]:
                p["status_pagamento"] = status_pag

        # Lista de (endpoint, params) para tentar
        tentativas = []
        for ep in self.COBRANCA_ENDPOINTS:
            tentativas.append((ep, params_vencimento))
            if tipo_data != "vencimento":
                tentativas.append((ep, params_custom))
            tentativas.append((ep, params_lancamento))

        melhor = None
        for ep, params in tentativas:
            try:
                dados = self._paginar(ep, params)
                if dados:
                    df = self._norm_cobrancas(pd.json_normalize(dados))
                    print(f"  {ep} [{list(params.keys())[0]}] -> {len(df)} registros")
                    # Escolhe o que retornar mais registros
                    if melhor is None or len(df) > len(melhor):
                        melhor = df
                        # Se já tem um bom resultado com /fatura, tenta /cobranca tbm
                        if "fatura" in ep and len(df) < 500:
                            continue  # continua para ver se cobranca tem mais
                        else:
                            break
            except Exception as e:
                if "404" in str(e) or "Not Found" in str(e):
                    continue
                print(f"  Erro {ep}: {str(e)[:60]}")

        return melhor if melhor is not None else pd.DataFrame()

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
            "recebido":                 "recebido",
            "data_vencimento":          "data_vencimento",
            "data_pagamento":           "data_pagamento",
            "data_lancamento":          "data_lancamento",
            "status":                   "status_raw",
            "descricao":                "descricao",
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

        # Log para diagnóstico
        print(f"  Colunas API: {list(df.columns)}")
        if "status_raw" in df.columns:
            print(f"  Status valores: {df['status_raw'].fillna('VAZIO').astype(str).str.lower().unique()[:8].tolist()}")
        if "recebido" in df.columns:
            print(f"  Campo recebido sample: {df['recebido'].head(3).tolist()}")

        PAGO_STATUS = {
            "pago","pago_total","pago_parcial","recebido","recebido_total",
            "liquidado","liquidado_total","baixado_banco","baixado_pix",
            "baixado_manual","baixado_faturamento","quitado","sim","yes","true","1",
        }

        def _st(row):
            # 1. Campo recebido (booleano Hubsoft)
            rec = str(row.get("recebido","")).lower().strip()
            if rec in ("sim","yes","true","1","s"): return "PAGO"
            # 2. valor_pago > 0
            try:
                if float(row.get("valor_pago", 0) or 0) > 0: return "PAGO"
            except: pass
            # 3. data_pagamento preenchida
            dp = row.get("data_pagamento")
            if pd.notna(dp) and str(dp).strip() not in ("","None","NaT","nan"): return "PAGO"
            # 4. status_raw
            s = str(row.get("status_raw","")).lower().strip()
            if s in PAGO_STATUS: return "PAGO"
            # 5. por vencimento
            d = row.get("data_vencimento")
            if pd.notna(d) and pd.Timestamp(d) < today: return "ATRASADO"
            return "A_VENCER"

        df["status"] = df.apply(_st, axis=1)
        p = (df["status"]=="PAGO").sum()
        a = (df["status"]=="ATRASADO").sum()
        v = (df["status"]=="A_VENCER").sum()
        print(f"  Classificados: PAGO={p} ATRASADO={a} A_VENCER={v}")

        if "nome_cliente" in df.columns:
            mask = df["nome_cliente"].fillna("").str.upper().apply(
                lambda n: any(ic in n for ic in IC_NOMES))
            df = df[~mask]

        df["dias_atraso"] = df["data_vencimento"].apply(
            lambda d: max(0,(today - pd.Timestamp(d)).days) if pd.notna(d) else 0)
        df["valor_pendente"] = df.apply(
            lambda r: 0.0 if r["status"]=="PAGO" else float(r.get("valor",0)), axis=1)

        return df.reset_index(drop=True)

    # ── IMPORTAR TUDO ─────────────────────────────────────────────────
    def importar_tudo(self, mes=None):
        if not mes:
            mes = datetime.now().strftime("%Y-%m")
        ano, m   = map(int, mes.split("-"))
        ult_dia  = calendar.monthrange(ano, m)[1]
        d_ini    = f"{mes}-01"
        d_fim    = f"{mes}-{ult_dia:02d}"

        print(f"=== HUBSOFT importar_tudo({mes}) ===")
        print(f"  Buscando cobranças {d_ini} a {d_fim}...")

        # Tenta GraphQL primeiro (retorna TODAS as cobranças incl. PIX/débito)
        cob_mes = pd.DataFrame()
        try:
            cob_mes = self.get_cobrancas_graphql_all(d_ini, d_fim)
            print(f"  → GraphQL: {len(cob_mes)} cobranças")
        except Exception as gql_err:
            print(f"  GraphQL indisponível ({str(gql_err)[:60]}), usando REST...")

        # Fallback para REST se GraphQL falhar
        if cob_mes.empty:
            cob_mes = self.get_cobrancas(d_ini, d_fim, tipo_data="vencimento")
            print(f"  → REST: {len(cob_mes)} faturas")

        try:
            clientes = self.get_clientes("ativo")
        except Exception:
            clientes = pd.DataFrame()

        pagas     = cob_mes[cob_mes["status"]=="PAGO"]     if not cob_mes.empty else pd.DataFrame()
        atrasadas = cob_mes[cob_mes["status"]=="ATRASADO"] if not cob_mes.empty else pd.DataFrame()
        a_vencer  = cob_mes[cob_mes["status"]=="A_VENCER"] if not cob_mes.empty else pd.DataFrame()

        # rec_df para o app (faturamento)
        rec_df = pd.DataFrame()
        if not cob_mes.empty:
            rec_df = cob_mes.rename(columns={"nome_cliente":"nome_razaosocial"}).copy()
            rec_df["__val"]    = pd.to_numeric(rec_df.get("valor",0), errors="coerce").fillna(0)
            rec_df["__venc"]   = rec_df.get("data_vencimento")
            rec_df["__nome"]   = rec_df.get("nome_razaosocial","").fillna("").astype(str)
            # __pago: usa critério de status
            status_pago_mask = rec_df.get("status", pd.Series()) == "PAGO"
            if status_pago_mask.sum() == 0 and not pagas.empty:
                id_col = "id_cobranca"
                if id_col in rec_df.columns and id_col in pagas.columns:
                    ids_p = set(pagas[id_col].astype(str))
                    status_pago_mask = rec_df[id_col].astype(str).isin(ids_p)
            rec_df["__pago"]   = status_pago_mask
            rec_df["__nome_c"] = rec_df["__nome"]

        # rec_recebidos (equivale ao extrato)
        cob_rec = pagas if not pagas.empty else pd.DataFrame()
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
            "faturado":      float(cob_mes["valor"].sum()) if not cob_mes.empty else 0.0,
            "recebido":      float(rec_recebidos["__val"].sum()) if not rec_recebidos.empty else 0.0,
            "atrasado":      float(atrasadas["valor"].sum()) if not atrasadas.empty else 0.0,
            "a_vencer":      float(a_vencer["valor"].sum()) if not a_vencer.empty else 0.0,
            "n_cobrancas":   len(cob_mes),
            "n_pagas":       len(pagas),
            "n_atrasadas":   len(atrasadas),
            "n_a_vencer":    len(a_vencer),
            "n_clientes":    len(clientes),
            "adimplencia":   round(len(pagas)/max(len(cob_mes),1)*100,1),
            "mes":           mes,
            "fonte":         "hubsoft_api",
            "atualizado_em": (datetime.utcnow() - timedelta(hours=3)).strftime("%d/%m/%Y %H:%M"),
        }

        print(f"  Totais: fat={totais['faturado']:.2f} rec={totais['recebido']:.2f} "
              f"atr={totais['atrasado']:.2f} av={totais['a_vencer']:.2f}")

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

    # ══════════════════════════════════════════════════════════════════
    # API GRAPHQL — mais completa que REST
    # Endpoint: /graphql/v1
    # Permite buscar cobranças + faturas com todos os campos
    # ══════════════════════════════════════════════════════════════════
    def _graphql(self, query: str, variables: dict = None) -> dict:
        """Executa uma query GraphQL."""
        self._ok_token()
        url = f"{self._base_ativo}/graphql/v1"
        payload = {"query": query}
        if variables:
            payload["variables"] = variables
        r = self.s.post(url, json=payload, timeout=30)
        r.raise_for_status()
        return r.json()

    def get_cobrancas_graphql(self, data_ini: str, data_fim: str,
                              page: int = 1, per_page: int = 100) -> dict:
        """
        Busca cobranças via GraphQL — retorna TODAS incluindo PIX/débito.
        data_ini/data_fim: 'YYYY-MM-DD'
        """
        query = """
        query Cobrancas($page: Int, $first: Int, $de: String, $ate: String) {
            cobrancas(page: $page, first: $first,
                      de: $de, ate: $ate) {
                paginatorInfo {
                    currentPage
                    lastPage
                    total
                }
                data {
                    id_cobranca
                    id_cliente
                    nome_razaosocial
                    valor
                    valor_pago
                    recebido
                    data_vencimento
                    data_pagamento
                    status
                    descricao
                    forma_pagamento
                }
            }
        }
        """
        variables = {
            "page": page,
            "first": per_page,
            "de": data_ini,
            "ate": data_fim,
        }
        return self._graphql(query, variables)

    def get_cobrancas_graphql_all(self, data_ini: str, data_fim: str,
                                   per_page: int = 100) -> pd.DataFrame:
        """
        Busca TODAS as cobranças do período via GraphQL (com paginação automática).
        """
        all_data = []
        page = 1
        last_page = 1

        while page <= last_page:
            try:
                resp = self.get_cobrancas_graphql(data_ini, data_fim, page, per_page)
                result = resp.get("data", {}).get("cobrancas", {})
                pag_info = result.get("paginatorInfo", {})
                data = result.get("data", [])

                if page == 1:
                    last_page = pag_info.get("lastPage", 1)
                    total = pag_info.get("total", "?")
                    print(f"  GraphQL cobranças: total={total} páginas={last_page}")

                all_data.extend(data)
                page += 1

            except Exception as e:
                print(f"  GraphQL erro p.{page}: {e}")
                break

        print(f"  GraphQL carregou: {len(all_data)} cobranças")
        if not all_data:
            return pd.DataFrame()
        return self._norm_cobrancas(pd.json_normalize(all_data))

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
