# 🔗 Integração Hubsoft — Como Usar

## 1. Credenciais necessárias

No Hubsoft, acesse: **Configurações → Integrações → API**

| Campo | Onde encontrar |
|---|---|
| URL | `https://jettelecom.hubsoft.com.br` |
| client_id | ID do usuário de API (ex: `147`) |
| client_secret | Secret gerado pelo Hubsoft |
| username | E-mail do usuário de API |
| password | Senha do usuário de API |

## 2. Configurar no Streamlit Cloud (recomendado)

Em **Settings → Secrets** do seu app:

```toml
HUBSOFT_URL           = "https://jettelecom.hubsoft.com.br"
HUBSOFT_CLIENT_ID     = "147"
HUBSOFT_CLIENT_SECRET = "seu_secret_aqui"
HUBSOFT_USERNAME      = "api@grupojet.com"
HUBSOFT_PASSWORD      = "sua_senha_aqui"
ANTHROPIC_API_KEY     = "sk-ant-..."
```

## 3. Adicionar ao app.py principal

Adicione estes imports no topo do app.py:
```python
from hubsoft_api import HubsoftAPI
from hubsoft_streamlit import render_tab_hubsoft
```

Adicione a tab nas tabs:
```python
tab_hubsoft = st.tabs([..., "🔗 Hubsoft"])
with tab_hubsoft:
    render_tab_hubsoft()
```

## 4. Endpoints utilizados

| Dado | Endpoint |
|---|---|
| Cobranças | `GET /api/v1/integracao/financeiro/cobranca` |
| Faturas | `GET /api/v1/integracao/financeiro/fatura` |
| Clientes | `GET /api/v1/integracao/cliente` |
| Token | `POST /oauth/token` |

## 5. Parâmetros de filtro (cobranças)

```
data_vencimento_ini = 2026-05-01
data_vencimento_fim = 2026-05-31
status = pago | aberto | atrasado
pagina = 0
limit  = 100
```

## 6. Uso via Python puro

```python
from hubsoft_api import HubsoftAPI

hub = HubsoftAPI(
    base_url      = "https://jettelecom.hubsoft.com.br",
    client_id     = "147",
    client_secret = "...",
    username      = "api@grupojet.com",
    password      = "...",
)

hub.autenticar()

# Cobranças do mês
fin = hub.get_financeiro_consolidado("2026-05")
print(fin["totais"])

# Cruzamento por cliente
cli = hub.get_cruzamento_clientes("2026-05")
print(cli.head())

# Cobranças atrasadas
atras = hub.get_cobrancas_atrasadas()

# Cobranças a vencer (30 dias)
a_vencer = hub.get_cobrancas_a_vencer(dias=30)
```
