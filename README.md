# CFO IA · Grupo Jet
> Plataforma financeira inteligente com Diretor CFO IA (Maxwell)

---

## 🚀 Deploy no Streamlit Cloud — Passo a passo

### 1. Criar repositório no GitHub
1. Acesse [github.com](https://github.com) → **New repository**
2. Nome: `grupo-jet-cfo` · Marque **Private** (recomendado) → **Create**
3. Faça upload de **todos os arquivos** desta pasta:
   - `app.py`
   - `requirements.txt`
   - `.streamlit/config.toml`

> ⚠️ **NÃO envie** o arquivo `secrets.toml.example` — ele contém informações sensíveis.

### 2. Conectar ao Streamlit Cloud
1. Acesse [share.streamlit.io](https://share.streamlit.io)
2. Faça login com sua conta GitHub
3. Clique em **"New app"**
4. Selecione o repositório `grupo-jet-cfo`
5. Branch: `main` · Main file: `app.py`
6. Clique em **"Deploy!"**

### 3. Configurar a chave da API (obrigatório para o CFO IA)
1. No painel do Streamlit Cloud, clique na sua app
2. Clique em **"⚙️ Settings"** → **"Secrets"**
3. Cole o seguinte (com sua chave real):
```toml
ANTHROPIC_API_KEY = "sk-ant-SUA_CHAVE_AQUI"
```
4. Clique em **Save** → o app reinicia automaticamente

> A chave é obtida em [console.anthropic.com](https://console.anthropic.com) → API Keys

### 4. Acessar
A URL será:
```
https://SEU_USUARIO-grupo-jet-cfo-app-XXXX.streamlit.app
```

---

## 📋 Funcionalidades

| Módulo | Descrição |
|--------|-----------|
| 📊 Dashboard | KPIs, fluxo de caixa, alertas de prioridade |
| 👥 Clientes | Carteira importada do Hubsoft |
| 🏦 Extratos | Upload CSV/XLSX de BTG, Caixa, C6, Safra, BB |
| 📥 Planilhas | Importação Excel Hubsoft + Contas a Pagar |
| 📋 Contas a Pagar | Scoring de prioridade |
| 📈 Previsão | Projeção 12 meses com 3 cenários |
| 🤝 Negociação | Contratos renegociáveis e inadimplentes |
| 🤖 CFO IA | Chat com Maxwell, diretor financeiro IA |

---

## 🔐 Segurança

- **Repositório privado** recomendado para dados internos
- **Nunca** commite `secrets.toml` com chaves reais
- Configure sempre via Streamlit Cloud → Settings → Secrets

---

*Grupo Jet · Plataforma CFO IA · Powered by Claude AI*
