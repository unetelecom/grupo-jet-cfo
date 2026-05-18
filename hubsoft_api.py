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

    def _paginar(self, endpoint, params=None, limit=100, max_pag=500):
        p = dict(params or {})
        p["pagina"]          = 0
        p["itens_por_pagina"]= limit
        dados = []
        total_esperado = None

        for n_pag in range(max_pag):
            resp = self._get(endpoint, p)
            pag  = resp.get("paginacao") or {}

            # Extrai dados PRIMEIRO
            bloco = (resp.get("dados") or resp.get("data") or
                     resp.get("clientes") or resp.get("contratos") or
                     resp.get("faturas") or resp.get("cobrancas") or [])

            # Loga estrutura na primeira chamada
            if n_pag == 0:
                total_esperado = pag.get("total_registros", "?")
                ultima_pag     = pag.get("ultima_pagina", 0)
                resp_keys = list(resp.keys())
                print(f"  Resp keys: {resp_keys}")
                print(f"  Paginacao: total={total_esperado} paginas={ultima_pag+1} itens/pag={limit}")
                if not bloco:
                    print(f"  ATENCAO: bloco vazio! resp={str(resp)[:200]}")
            if isinstance(bloco, list):
                dados.extend(bloco)
            elif isinstance(bloco, dict) and bloco:
                dados.append(bloco)

            ultima = pag.get("ultima_pagina", 0)
            atual  = pag.get("pagina_atual",  p["pagina"])
            if not bloco or atual >= ultima:
                break
            p["pagina"] = atual + 1

        print(f"  Total carregado: {len(dados)} registros")
        if total_esperado and str(total_esperado).isdigit() and len(dados) < int(total_esperado):
            print(f"  INCOMPLETO: {len(dados)} de {total_esperado}")
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
                      tipo_data="vencimento", pago=None, status_pag=None):
        params = {
            f"data_{tipo_data}_ini": data_ini,
            f"data_{tipo_data}_fim": data_fim,
        }
        if pago is not None:
            params["pago"] = int(pago)
        if status_pag:
            params["status_pagamento"] = status_pag

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
        # ── Loga todos os campos para diagnóstico ──
        print(f"  Colunas disponíveis na API: {list(df.columns)}")
        if "status_raw" in df.columns:
            status_unicos = df["status_raw"].fillna("VAZIO").astype(str).str.lower().unique()
            print(f"  Valores de status_raw: {list(status_unicos)[:10]}")
        if "recebido" in df.columns:
            print(f"  Campo 'recebido' sample: {df['recebido'].head(3).tolist()}")
        if "valor_pago" in df.columns:
            print(f"  Campo 'valor_pago' sample: {df['valor_pago'].head(3).tolist()}")
        if "data_pagamento" in df.columns:
            print(f"  Campo 'data_pagamento' sample (não-null): {df['data_pagamento'].dropna().head(3).tolist()}")

        # ── CLASSIFICAÇÃO MULTI-CRITÉRIO ──────────────────────────────
        # Hubsoft usa "recebido" (campo booleano/numérico) OU "data_pagamento" preenchida
        # OU status_raw com variações de "liquidado", "baixado", "recebido", "pago"
        PAGO_STATUS = {
            # Termos em português
            "pago","pago_total","pago_parcial","pago completo",
            "recebido","recebido_total","recebido_parcial",
            "liquidado","liquidado_total","liquidado_parcial",
            "baixado_banco","baixado_pix","baixado_manual","baixado_parcial",
            "baixado_faturamento","baixado cheque","baixado",
            "quitado","quitado_parcial",
            # Valores booleanos/numéricos
            "sim","yes","true","1","2","3",
        }

        def _st(row):
            # 1. Verifica campo "recebido" (booleano Hubsoft)
            rec = str(row.get("recebido","")).lower().strip()
            if rec in ("sim","yes","true","1","s"): return "PAGO"
            # 2. Verifica valor_pago > 0
            vp = 0.0
            try: vp = float(row.get("valor_pago", 0) or 0)
            except: pass
            if vp > 0: return "PAGO"
            # 3. Verifica data_pagamento preenchida
            dp = row.get("data_pagamento")
            if pd.notna(dp) and str(dp).strip() not in ("","None","NaT","nan"): return "PAGO"
            # 4. Verifica status_raw
            s = str(row.get("status_raw","")).lower().strip()
            if s in PAGO_STATUS: return "PAGO"
            # 5. Classifica por data de vencimento
            d = row.get("data_vencimento")
            if pd.notna(d) and pd.Timestamp(d) < today: return "ATRASADO"
            return "A_VENCER"

        df["status"] = df.apply(_st, axis=1)
        p = (df["status"]=="PAGO").sum()
        a = (df["status"]=="ATRASADO").sum()
        v = (df["status"]=="A_VENCER").sum()
        print(f"  Classificados: PAGO={p}, ATRASADO={a}, A_VENCER={v}")
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
        d_ini    = f"{mes}-01"              # sempre do dia 1
        d_fim    = f"{mes}-{ult_dia:02d}"  # até o último dia do mês

        # ── ESTRATÉGIA COMPLETA ───────────────────────────────────────────
        # Busca em paralelo:
        # A) Faturas com VENCIMENTO no mês (maio 01→31)
        # B) Faturas ATRASADAS com vencimento em meses anteriores ainda em aberto
        # C) Combina tudo sem duplicatas

        print(f"=== HUBSOFT importar_tudo({mes}) ===")

        # ── Busca TODAS as faturas do mês por vencimento ─────────────
        # Sem filtro de status — o Hubsoft retorna tudo que vence no período
        print(f"  Buscando faturas venc {d_ini} a {d_fim}...")
        cob_mes = self.get_cobrancas(d_ini, d_fim, tipo_data="vencimento")
        print(f"  → {len(cob_mes)} faturas")

        # Se trouxe menos de 5, tenta buscar SEM filtro de data (tudo do sistema)
        if len(cob_mes) < 5:
            print("  Poucos resultados — tentando sem filtro de data...")
            cob_all = self._paginar(self.COBRANCA_ENDPOINTS[0], {})
            if len(cob_all) > len(cob_mes):
                df_all = self._norm_cobrancas(pd.json_normalize(cob_all))
                # Filtra pelo mês selecionado
                if "data_vencimento" in df_all.columns:
                    mask = (
                        (df_all["data_vencimento"] >= pd.Timestamp(d_ini)) &
                        (df_all["data_vencimento"] <= pd.Timestamp(d_fim))
                    )
                    cob_mes = df_all[mask].copy()
                    print(f"  → filtrado do total: {len(cob_mes)} faturas")

        cob_pagas = cob_mes  # referência para classificação

        # ── Recebidos = faturas classificadas como PAGO ───────────────
        if not cob_mes.empty and "status" in cob_mes.columns:
            cob_rec = cob_mes[cob_mes["status"] == "PAGO"].copy()
            if cob_rec.empty and not cob_pagas.empty:
                print("  0 PAGO — usando fallback (faturas sem status 'aberto')")
                cob_rec = cob_pagas.copy()
                cob_rec["status"] = "PAGO"
        else:
            cob_rec = pd.DataFrame()

        print(f"  PAGO={len(cob_rec)} | Total={len(cob_mes)}")
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
            # Se nenhuma foi classificada como PAGO, usa cob_pagas como referência
            # (o call sem filtro de status retorna as pagas por padrão no Hubsoft)
            status_pago_mask = rec_df.get("status", pd.Series()) == "PAGO"
            if status_pago_mask.sum() == 0 and not cob_pagas.empty:
                id_col_chk = "id_cobranca"
                if id_col_chk in rec_df.columns and id_col_chk in cob_pagas.columns:
                    ids_pagas_set = set(cob_pagas[id_col_chk].astype(str))
                    status_pago_mask = rec_df[id_col_chk].astype(str).isin(ids_pagas_set)
                else:
                    # Sem id disponível: marca tudo do cob_pagas como pago por índice
                    status_pago_mask = rec_df.index < len(cob_pagas)
            rec_df["__pago"]   = status_pago_mask
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
            "atualizado_em":(datetime.utcnow() - timedelta(hours=3)).strftime("%d/%m/%Y %H:%M"),
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
