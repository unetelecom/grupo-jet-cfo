"""
HUBSOFT API — Grupo Jet Telecom
Versão definitiva — comunicação completa com REST + GraphQL
"""
import re, time, calendar
import requests
import pandas as pd
from datetime import datetime, timedelta

# ─────────────────────────────────────────────────────────────────────
# Clientes intercompany (excluídos do faturamento)
# ─────────────────────────────────────────────────────────────────────
IC_NOMES = {"RDMI","RRD TELECOM","GRUPO JET","JET TELECOM","RD TELECOM"}

# ─────────────────────────────────────────────────────────────────────
# AUTENTICAÇÃO OAuth2
# ─────────────────────────────────────────────────────────────────────
OAUTH_PATHS = ["/oauth/token", "/api/oauth/token", "/oauth/access-token"]

def _auth(base_url, client_id, client_secret, username, password):
    """Autentica e retorna (token, base_url_ativo, path_usado)."""
    s = requests.Session()
    s.headers["Accept"] = "application/json"
    body = {
        "grant_type":    "password",
        "client_id":     str(client_id),
        "client_secret": client_secret,
        "username":      username,
        "password":      password,
    }
    errors = []
    for base in [base_url.rstrip("/")]:
        for path in OAUTH_PATHS:
            for ct, kw in [
                ("application/x-www-form-urlencoded", {"data": body}),
                ("application/json",                  {"json": body}),
            ]:
                try:
                    r = s.post(f"{base}{path}",
                               headers={"Content-Type": ct, "Accept": "application/json"},
                               timeout=15, **kw)
                    if r.status_code in (404, 405):
                        errors.append(f"{r.status_code} {path} [{ct[:4]}]")
                        break
                    if r.status_code not in (200, 201):
                        errors.append(f"{r.status_code} {path}: {r.text[:60]}")
                        continue
                    tok = r.json().get("access_token") or r.json().get("token")
                    if tok:
                        return tok, base, path
                    errors.append(f"sem_token {path}")
                except requests.ConnectionError as e:
                    errors.append(f"conn {base}: {e!s:.50}")
                    break
                except Exception as e:
                    errors.append(f"err {path}: {e!s:.60}")

    raise ConnectionError(
        "Hubsoft: falha de autenticação.\n" +
        "\n".join(f"  {e}" for e in errors[:15])
    )


# ─────────────────────────────────────────────────────────────────────
# CLASSE PRINCIPAL
# ─────────────────────────────────────────────────────────────────────
class HubsoftAPI:

    def __init__(self, base_url, client_id, client_secret, username, password):
        self._base    = base_url.rstrip("/")
        self._cid     = str(client_id)
        self._csec    = client_secret
        self._user    = username
        self._pass    = password
        self._token   = None
        self._expiry  = None
        self._active  = base_url.rstrip("/")
        self.s        = requests.Session()
        self.s.headers["Accept"] = "application/json"
        # Cache do schema GraphQL
        self._gql_schema = None

    # ── AUTH ─────────────────────────────────────────────────────────
    def autenticar(self):
        tok, base, path = _auth(self._base, self._cid, self._csec,
                                 self._user, self._pass)
        self._token  = tok
        self._active = base
        self._expiry = datetime.now() + timedelta(seconds=3540)
        self.s.headers["Authorization"] = f"Bearer {tok}"
        print(f"  Auth OK via {path}")
        return tok

    def _ensure_token(self):
        if not self._token or datetime.now() >= (self._expiry or datetime.min):
            self.autenticar()

    # ── HTTP GET ──────────────────────────────────────────────────────
    def _get(self, endpoint, params=None, retries=3):
        self._ensure_token()
        url = f"{self._active}{endpoint}"
        for t in range(retries):
            try:
                r = self.s.get(url, params=params or {}, timeout=30)
                if r.status_code == 401:
                    self.autenticar()
                    r = self.s.get(url, params=params or {}, timeout=30)
                if r.status_code == 404:
                    raise requests.HTTPError(f"404 {url}")
                r.raise_for_status()
                return r.json()
            except requests.Timeout:
                if t == retries - 1: raise
                time.sleep(2 ** t)

    # ── PAGINAÇÃO REST ────────────────────────────────────────────────
    def _paginar(self, endpoint, params=None, limit=100, max_pages=500):
        """Percorre todas as páginas de um endpoint REST."""
        p = dict(params or {})
        p.update({"pagina": 0, "itens_por_pagina": limit})
        dados = []
        total_esperado = None

        for pg in range(max_pages):
            resp = self._get(endpoint, p)
            pag  = resp.get("paginacao") or {}

            # Extrai bloco de dados — tenta várias chaves conhecidas
            bloco = (
                resp.get("dados") or resp.get("data") or
                resp.get("faturas") or resp.get("cobrancas") or
                resp.get("clientes") or []
            )

            if pg == 0:
                total_esperado = pag.get("total_registros")
                ultima_pg = pag.get("ultima_pagina", 0)
                print(f"  {endpoint}: total={total_esperado} págs={ultima_pg+1}")
                if not bloco:
                    print(f"  keys da resposta: {list(resp.keys())}")

            if isinstance(bloco, list):
                dados.extend(bloco)
            elif isinstance(bloco, dict) and bloco:
                dados.append(bloco)

            ultima = pag.get("ultima_pagina", 0)
            atual  = pag.get("pagina_atual", p["pagina"])
            if not bloco or atual >= ultima:
                break
            p["pagina"] = atual + 1

        print(f"  → {len(dados)} registros carregados")
        if total_esperado and len(dados) < int(total_esperado or 0):
            print(f"  ⚠ incompleto: {len(dados)} de {total_esperado}")
        return dados

    # ── GRAPHQL ───────────────────────────────────────────────────────
    def _gql(self, query, variables=None):
        """Executa query GraphQL."""
        self._ensure_token()
        url = f"{self._active}/graphql/v1"
        r = self.s.post(url, json={"query": query, **({"variables": variables} if variables else {})},
                        timeout=30)
        r.raise_for_status()
        return r.json()

    def _gql_schema(self):
        """Carrega o schema GraphQL (com cache)."""
        if self._gql_schema:
            return self._gql_schema
        try:
            resp = self._gql("""{
              __schema {
                queryType { fields { name args { name } } }
                types { name fields { name } }
              }
            }""")
            if resp.get("data"):
                self._gql_schema = resp["data"]["__schema"]
                # Loga queries financeiras disponíveis
                queries = [f["name"] for f in self._gql_schema.get("queryType",{}).get("fields",[])]
                fin_q = [q for q in queries if any(x in q.lower() for x in
                         ["cobran","fatura","financ","receber","pagamento"])]
                print(f"  GQL queries financeiras: {fin_q}")
                # Loga campos do tipo Cobranca
                for t in self._gql_schema.get("types",[]):
                    if "cobran" in t["name"].lower() and not t["name"].startswith("_") and t.get("fields"):
                        campos = [f["name"] for f in t["fields"]]
                        print(f"  GQL tipo {t['name']}: {campos}")
        except Exception as e:
            print(f"  GQL schema erro: {e}")
        return self._gql_schema

    def _gql_cobrancas_all(self, data_ini, data_fim, per_page=100):
        """
        Busca cobranças via GraphQL.
        Descobre automaticamente os campos e args corretos via introspecção.
        """
        schema = self._gql_schema()
        if not schema:
            return pd.DataFrame()

        # Descobre args do query cobrancas
        cob_args = []
        cob_query_name = None
        for f in schema.get("queryType",{}).get("fields",[]):
            if "cobran" in f["name"].lower() or "fatura" in f["name"].lower():
                cob_query_name = f["name"]
                cob_args = [a["name"] for a in f.get("args",[])]
                print(f"  GQL query: {cob_query_name}({cob_args})")
                break

        if not cob_query_name:
            print("  GQL: query cobrancas não encontrada")
            return pd.DataFrame()

        # Descobre campos do tipo Cobranca
        cob_fields = ["id", "valor", "data_vencimento", "status"]  # fallback
        for t in schema.get("types",[]):
            if "cobran" in t["name"].lower() and not t["name"].startswith("_") and t.get("fields"):
                cob_fields = [f["name"] for f in t["fields"]]
                break

        # Remove campos problemáticos conhecidos
        cob_fields = [f for f in cob_fields if f not in ("__typename",)]
        fields_str = "\n".join(cob_fields[:30])

        # Monta args de data com base nos args disponíveis
        date_args = ""
        if "de" in cob_args and "ate" in cob_args:
            date_args = f', de:"{data_ini}", ate:"{data_fim}"'
        elif "data_inicio" in cob_args and "data_fim" in cob_args:
            date_args = f', data_inicio:"{data_ini}", data_fim:"{data_fim}"'
        elif "data_vencimento_ini" in cob_args:
            date_args = f', data_vencimento_ini:"{data_ini}", data_vencimento_fim:"{data_fim}"'

        # Busca todas as páginas
        all_data = []
        page = 1
        last_page = 1

        while page <= last_page:
            query = f"""
            {{
              {cob_query_name}(page:{page}, first:{per_page}{date_args}) {{
                paginatorInfo {{ currentPage lastPage total }}
                data {{ {fields_str} }}
              }}
            }}
            """
            try:
                resp = self._gql(query)
                if resp.get("errors"):
                    # Tenta sem filtro de data se der erro
                    if date_args and page == 1:
                        print(f"  GQL erro com data, tentando sem filtro...")
                        date_args = ""
                        continue
                    errs = [e["message"][:80] for e in resp["errors"][:3]]
                    print(f"  GQL p{page} erros: {errs}")
                    break

                result   = resp.get("data",{}).get(cob_query_name,{})
                pag_info = result.get("paginatorInfo",{})
                data_raw = result.get("data",[])

                if page == 1:
                    last_page = pag_info.get("lastPage", 1)
                    total     = pag_info.get("total","?")
                    print(f"  GQL {cob_query_name}: total={total} págs={last_page}")
                    if data_raw:
                        print(f"  GQL campos retornados: {list(data_raw[0].keys())}")

                all_data.extend(data_raw)
                page += 1

            except Exception as e:
                print(f"  GQL p{page} erro: {e}")
                break

        if not all_data:
            return pd.DataFrame()

        df = self._norm(pd.json_normalize(all_data))

        # Filtra por período se não foi filtrado na query
        if not date_args and "data_vencimento" in df.columns:
            mask = (
                (df["data_vencimento"] >= pd.Timestamp(data_ini)) &
                (df["data_vencimento"] <= pd.Timestamp(data_fim))
            )
            df = df[mask].copy()
            print(f"  GQL filtrado client-side: {len(df)} cobranças")

        return df

    # ── REST COBRANÇAS ────────────────────────────────────────────────
    def _rest_cobrancas(self, data_ini, data_fim):
        """
        Busca cobranças via REST.
        Tenta múltiplos endpoints e variações de parâmetros.
        Retorna o maior conjunto de dados encontrado.
        """
        # Todos os endpoints e variações de params conhecidos
        tentativas = []

        # /cliente/financeiro — retorna TODOS os tipos (docs v1.99)
        for params in [
            {"data_vencimento_ini": data_ini, "data_vencimento_fim": data_fim},
            {"data_inicio": data_ini, "data_fim": data_fim},
            {"de": data_ini, "ate": data_fim},
            {"data_ini": data_ini, "data_fim": data_fim},
            {},  # sem filtro
        ]:
            tentativas.append(("/api/v1/integracao/cliente/financeiro", params))

        # /financeiro/fatura — confirmado: 190 boletos
        tentativas.append(("/api/v1/integracao/financeiro/fatura",
                           {"data_vencimento_ini": data_ini, "data_vencimento_fim": data_fim}))

        # /financeiro — confirmado: 190 boletos (chave "faturas")
        tentativas.append(("/api/v1/integracao/financeiro",
                           {"data_vencimento_ini": data_ini, "data_vencimento_fim": data_fim}))

        melhor = None
        melhor_n = 0
        for ep, params in tentativas:
            try:
                dados = self._paginar(ep, params)
                if dados and len(dados) > melhor_n:
                    df = self._norm(pd.json_normalize(dados))
                    if len(df) > melhor_n:
                        melhor = df
                        melhor_n = len(df)
                        print(f"  Melhor até agora: {ep} → {len(df)}")
                        if len(df) > 500:
                            break  # achou dados suficientes
            except Exception as e:
                if "404" not in str(e):
                    print(f"  Erro {ep}: {e!s:.60}")

        return melhor if melhor is not None else pd.DataFrame()

    # ── NORMALIZAÇÃO ──────────────────────────────────────────────────
    @staticmethod
    def _norm(df):
        """Normaliza colunas e classifica status de pagamento."""
        if df.empty:
            return df

        today = pd.Timestamp.now().normalize()

        RENAME = {
            "id":                       "id_cobranca",
            "id_cliente":               "id_cliente",
            "nome_razaosocial":         "nome_cliente",
            "nome":                     "nome_cliente",
            "cliente.nome_razaosocial": "nome_cliente",
            "cliente.nome":             "nome_cliente",
            "valor":                    "valor",
            "valor_pago":               "valor_pago",
            "recebido":                 "recebido",
            "data_vencimento":          "data_vencimento",
            "data_pagamento":           "data_pagamento",
            "data_lancamento":          "data_lancamento",
            "status":                   "status_raw",
            "situacao":                 "status_raw",
            "descricao":                "descricao",
            "tipo_cobranca":            "tipo_cobranca",
            "forma_pagamento":          "forma_pagamento",
        }
        df = df.rename(columns={k: v for k, v in RENAME.items() if k in df.columns})

        # Garante colunas obrigatórias
        for col in ["id_cobranca","nome_cliente","valor","data_vencimento","status_raw"]:
            if col not in df.columns:
                df[col] = None

        # Converte datas
        for dc in ["data_vencimento","data_pagamento","data_lancamento"]:
            if dc in df.columns:
                df[dc] = pd.to_datetime(df[dc], errors="coerce").dt.normalize()

        # Converte valores
        for vc in ["valor","valor_pago"]:
            if vc in df.columns:
                df[vc] = pd.to_numeric(df[vc], errors="coerce").fillna(0).abs()

        # Log diagnóstico
        print(f"  Colunas: {list(df.columns)[:12]}")
        if "status_raw" in df.columns:
            sv = df["status_raw"].fillna("VAZIO").astype(str).str.lower().unique()
            print(f"  Status valores: {list(sv[:8])}")
        if "recebido" in df.columns:
            print(f"  Campo recebido: {df['recebido'].head(3).tolist()}")

        # Classificação de status — multi-critério
        PAGO = {
            "pago","pago_total","pago_parcial",
            "recebido","recebido_total","recebido_parcial",
            "liquidado","liquidado_total","liquidado_parcial",
            "baixado_banco","baixado_pix","baixado_manual",
            "baixado_faturamento","baixado_cheque","baixado",
            "quitado","quitado_parcial",
            "sim","yes","true","1","s",
        }

        def _status(row):
            # 1. Campo recebido
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
            if s in PAGO: return "PAGO"
            # 5. por vencimento
            d = row.get("data_vencimento")
            if pd.notna(d) and pd.Timestamp(d) < today: return "ATRASADO"
            return "A_VENCER"

        df["status"] = df.apply(_status, axis=1)
        p = (df["status"]=="PAGO").sum()
        a = (df["status"]=="ATRASADO").sum()
        v = (df["status"]=="A_VENCER").sum()
        print(f"  Classificados: PAGO={p} ATR={a} AV={v}")

        # Remove intercompany
        if "nome_cliente" in df.columns:
            mask_ic = df["nome_cliente"].fillna("").str.upper().apply(
                lambda n: any(ic in n for ic in IC_NOMES))
            if mask_ic.any():
                print(f"  Removendo {mask_ic.sum()} intercompany")
                df = df[~mask_ic]

        df["dias_atraso"] = df["data_vencimento"].apply(
            lambda d: max(0,(today - pd.Timestamp(d)).days) if pd.notna(d) else 0)

        return df.reset_index(drop=True)

    # ── CLIENTES ──────────────────────────────────────────────────────
    def get_clientes(self):
        """Retorna DataFrame com todos os clientes ativos."""
        for ep in ["/api/v1/integracao/cliente/todos",
                   "/api/v1/integracao/cliente"]:
            try:
                dados = self._paginar(ep, {"status":"ativo"})
                if dados:
                    df = pd.json_normalize(dados)
                    return df.rename(columns={"id":"id_cliente","nome_razaosocial":"nome"})
            except Exception as e:
                if "404" not in str(e): print(f"  Clientes {ep}: {e}")
        return pd.DataFrame()

    # ── IMPORTAR TUDO ─────────────────────────────────────────────────
    def importar_tudo(self, mes=None):
        """
        Importa todas as cobranças do mês via GraphQL (preferencial) ou REST.
        Retorna dict compatível com o app.py.
        """
        if not mes:
            mes = datetime.now().strftime("%Y-%m")
        ano, m  = map(int, mes.split("-"))
        ult_dia = calendar.monthrange(ano, m)[1]
        d_ini   = f"{mes}-01"
        d_fim   = f"{mes}-{ult_dia:02d}"

        print(f"\n{'='*50}")
        print(f"HUBSOFT importar_tudo({mes}) — {d_ini} a {d_fim}")
        print(f"{'='*50}")

        # ── 1. Tenta GraphQL ─────────────────────────────────────────
        cob_mes = pd.DataFrame()
        gql_ok  = False
        try:
            print("\n[1] Tentando API GraphQL...")
            cob_mes = self._gql_cobrancas_all(d_ini, d_fim)
            if not cob_mes.empty:
                print(f"  ✅ GraphQL: {len(cob_mes)} cobranças")
                gql_ok = True
        except Exception as e:
            print(f"  GraphQL indisponível: {e!s:.80}")

        # ── 2. Fallback REST ─────────────────────────────────────────
        if cob_mes.empty:
            print("\n[2] Fallback REST...")
            cob_mes = self._rest_cobrancas(d_ini, d_fim)
            print(f"  REST: {len(cob_mes)} cobranças")

        if cob_mes.empty:
            print("  ⚠ Nenhuma cobrança encontrada!")
            return self._resultado_vazio(mes)

        # ── 3. Clientes ──────────────────────────────────────────────
        print("\n[3] Buscando clientes...")
        try:
            clientes = self.get_clientes()
            print(f"  {len(clientes)} clientes")
        except Exception as e:
            print(f"  Clientes erro: {e}")
            clientes = pd.DataFrame()

        # ── 4. Separa por status ─────────────────────────────────────
        pagas     = cob_mes[cob_mes["status"]=="PAGO"].copy()
        atrasadas = cob_mes[cob_mes["status"]=="ATRASADO"].copy()
        a_vencer  = cob_mes[cob_mes["status"]=="A_VENCER"].copy()

        # ── 5. rec_df (para o app — faturamento) ────────────────────
        rec_df = cob_mes.rename(columns={"nome_cliente":"nome_razaosocial"}).copy()
        rec_df["__val"]  = pd.to_numeric(rec_df.get("valor",0), errors="coerce").fillna(0)
        rec_df["__venc"] = rec_df.get("data_vencimento")
        rec_df["__nome"] = rec_df.get("nome_razaosocial","").fillna("").astype(str)
        rec_df["__pago"] = rec_df["status"] == "PAGO"
        # Fallback: se 0 pagos, usa col id para marcar os da cob pagas
        if rec_df["__pago"].sum() == 0 and not pagas.empty:
            id_col = "id_cobranca"
            if id_col in rec_df.columns and id_col in pagas.columns:
                ids_p = set(pagas[id_col].astype(str))
                rec_df["__pago"] = rec_df[id_col].astype(str).isin(ids_p)
        rec_df["__nome_c"] = rec_df["__nome"]

        # ── 6. rec_recebidos (equivale ao extrato) ──────────────────
        cob_rec       = pagas if not pagas.empty else pd.DataFrame()
        rec_recebidos = pd.DataFrame()
        if not cob_rec.empty:
            rec_recebidos = pd.DataFrame({
                "__pagante": cob_rec.get("nome_cliente", pd.Series(dtype=str)).fillna(""),
                "__val":     pd.to_numeric(cob_rec.get("valor",0), errors="coerce").fillna(0),
                "__data":    cob_rec.get("data_pagamento", pd.Series(dtype="datetime64[ns]")),
                "__memo":    cob_rec.get("descricao", pd.Series(dtype=str)).fillna(""),
            })
            rec_recebidos = rec_recebidos[rec_recebidos["__val"] > 0]

        # ── 7. Totais ────────────────────────────────────────────────
        faturado  = float(cob_mes["valor"].sum())
        recebido  = float(rec_recebidos["__val"].sum()) if not rec_recebidos.empty else 0.0
        atrasado  = float(atrasadas["valor"].sum()) if not atrasadas.empty else 0.0
        av        = float(a_vencer["valor"].sum()) if not a_vencer.empty else 0.0
        adimpl    = round(len(pagas)/max(len(cob_mes),1)*100,1)
        brt_now   = (datetime.utcnow() - timedelta(hours=3)).strftime("%d/%m/%Y %H:%M")

        print(f"\n{'='*50}")
        print(f"RESUMO {mes}: {len(cob_mes)} cobranças | "
              f"Fat={faturado:.2f} | Rec={recebido:.2f} | "
              f"Atr={atrasado:.2f} | AV={av:.2f} | "
              f"Adimpl={adimpl}%")
        print(f"Fonte: {'GraphQL' if gql_ok else 'REST'}")
        print(f"{'='*50}\n")

        totais = {
            "faturado":     faturado,
            "recebido":     recebido,
            "atrasado":     atrasado,
            "a_vencer":     av,
            "n_cobrancas":  len(cob_mes),
            "n_pagas":      len(pagas),
            "n_atrasadas":  len(atrasadas),
            "n_a_vencer":   len(a_vencer),
            "n_clientes":   len(clientes),
            "adimplencia":  adimpl,
            "mes":          mes,
            "fonte":        "graphql" if gql_ok else "rest",
            "atualizado_em": brt_now,
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

    def _resultado_vazio(self, mes):
        brt = (datetime.utcnow()-timedelta(hours=3)).strftime("%d/%m/%Y %H:%M")
        totais = {k:0 for k in ["faturado","recebido","atrasado","a_vencer",
                                  "n_cobrancas","n_pagas","n_atrasadas","n_a_vencer","n_clientes"]}
        totais.update({"adimplencia":0,"mes":mes,"fonte":"vazio","atualizado_em":brt})
        empty = pd.DataFrame()
        return {"rec_df":empty,"rec_recebidos":empty,"clientes":empty,
                "cob_mes":empty,"pagas":empty,"atrasadas":empty,"a_vencer":empty,
                "totais":totais}

    # ── CRUZAMENTO POR CLIENTE ────────────────────────────────────────
    def cruzamento_clientes(self, cob_df=None, mes=None):
        if cob_df is None or (hasattr(cob_df,"empty") and cob_df.empty):
            cob_df = self.importar_tudo(mes)["cob_mes"]
        if cob_df.empty or "nome_cliente" not in cob_df.columns:
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
        return cli.sort_values("faturado", ascending=False)


# ─────────────────────────────────────────────────────────────────────
# DIAGNÓSTICO
# ─────────────────────────────────────────────────────────────────────
def diagnosticar(hub_url, client_id, client_secret, username, password, mes="2026-05"):
    """
    Testa todos os endpoints disponíveis e retorna relatório.
    Usado pela aba de diagnóstico no app.
    """
    import json
    resultado = {"auth": None, "rest": [], "graphql": {}}

    # Auth
    try:
        tok, base, path = _auth(hub_url, client_id, client_secret, username, password)
        resultado["auth"] = {"ok": True, "token": tok[:20]+"...", "base": base, "path": path}
    except Exception as e:
        resultado["auth"] = {"ok": False, "erro": str(e)}
        return resultado

    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {tok}", "Accept": "application/json"})
    d_ini, d_fim = f"{mes}-01", f"{mes}-31"

    # Todos os endpoints a testar
    endpoints = [
        "/api/v1/integracao/financeiro/fatura",
        "/api/v1/integracao/financeiro",
        "/api/v1/integracao/financeiro/cobranca",
        "/api/v1/integracao/cliente/financeiro",
        "/api/v1/integracao/cliente/todos",
        "/api/v1/integracao/cliente",
    ]
    param_sets = [
        ("venc",       {"pagina":0,"itens_por_pagina":1,"data_vencimento_ini":d_ini,"data_vencimento_fim":d_fim}),
        ("inicio/fim", {"pagina":0,"itens_por_pagina":1,"data_inicio":d_ini,"data_fim":d_fim}),
        ("de/ate",     {"pagina":0,"itens_por_pagina":1,"de":d_ini,"ate":d_fim}),
        ("sem_data",   {"pagina":0,"itens_por_pagina":1}),
    ]

    for ep in endpoints:
        for plabel, params in param_sets:
            try:
                r = s.get(f"{base}{ep}", params=params, timeout=10)
                total = ""
                keys  = ""
                try:
                    d = r.json()
                    pag   = d.get("paginacao",{})
                    total = str(pag.get("total_registros","—"))
                    keys  = str(list(d.keys()))[:70]
                except: keys = r.text[:50]
                resultado["rest"].append({
                    "Endpoint": ep, "Params": plabel,
                    "Status": r.status_code, "Total": total,
                    "Keys": keys, "OK": r.status_code==200,
                })
                if r.status_code == 200: break  # não precisa testar outras variações
            except Exception as ex:
                resultado["rest"].append({
                    "Endpoint":ep,"Params":plabel,"Status":"Err",
                    "Total":"","Keys":str(ex)[:50],"OK":False})
                break

    # GraphQL
    try:
        r_gql = s.post(f"{base}/graphql/v1", json={"query":"""{
          __schema {
            queryType { fields { name args { name } } }
            types { name fields { name } }
          }
        }"""}, timeout=15)
        if r_gql.status_code == 200:
            schema = r_gql.json().get("data",{}).get("__schema",{})
            if schema:
                all_queries = [f["name"] for f in schema.get("queryType",{}).get("fields",[])]
                fin_queries = {}
                for f in schema.get("queryType",{}).get("fields",[]):
                    nm = f["name"].lower()
                    if any(x in nm for x in ["cobran","fatura","financ","receber"]):
                        fin_queries[f["name"]] = [a["name"] for a in f.get("args",[])]
                cob_fields = {}
                for t in schema.get("types",[]):
                    if any(x in t["name"].lower() for x in ["cobran","fatura"]) \
                       and not t["name"].startswith("_") and t.get("fields"):
                        cob_fields[t["name"]] = [f["name"] for f in t["fields"]]
                resultado["graphql"] = {
                    "ok": True,
                    "all_queries": all_queries,
                    "fin_queries": fin_queries,
                    "types": cob_fields,
                }
            else:
                resultado["graphql"] = {"ok": False, "resp": r_gql.json()}
        else:
            resultado["graphql"] = {"ok": False, "status": r_gql.status_code}
    except Exception as e:
        resultado["graphql"] = {"ok": False, "erro": str(e)}

    return resultado
