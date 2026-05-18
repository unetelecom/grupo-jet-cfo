# CFO IA · Grupo Jet
**Plataforma financeira inteligente com Diretor CFO IA (Maxwell)**

---

## 🚀 Deploy no GitHub Pages — Passo a passo

### 1. Criar repositório no GitHub
1. Acesse [github.com](https://github.com) e faça login
2. Clique em **"New repository"** (botão verde)
3. Nome sugerido: `grupo-jet-cfo`
4. Marque **"Public"** (necessário para GitHub Pages gratuito)
5. Clique em **"Create repository"**

### 2. Fazer upload do arquivo
**Opção A — pelo navegador (mais fácil):**
1. No repositório criado, clique em **"uploading an existing file"**
2. Arraste o arquivo `index.html` para a área de upload
3. Clique em **"Commit changes"**

**Opção B — via Git (terminal):**
```bash
git clone https://github.com/SEU_USUARIO/grupo-jet-cfo.git
cd grupo-jet-cfo
cp /caminho/index.html .
git add index.html
git commit -m "Adicionar plataforma CFO IA"
git push
```

### 3. Ativar GitHub Pages
1. No repositório, clique em **Settings** (engrenagem)
2. No menu lateral, clique em **Pages**
3. Em **"Source"**, selecione: **"Deploy from a branch"**
4. Branch: **main** · Pasta: **/ (root)**
5. Clique em **Save**
6. Aguarde 1–2 minutos

### 4. Acessar a plataforma
A URL será:
```
https://SEU_USUARIO.github.io/grupo-jet-cfo/
```

---

## 🔑 Configurar Chave da API Anthropic (obrigatório para o CFO IA)

A plataforma usa a API da Anthropic para alimentar o Maxwell CFO.

### Obter a chave
1. Acesse [console.anthropic.com](https://console.anthropic.com)
2. Vá em **API Keys** → **Create Key**
3. Copie a chave (começa com `sk-ant-...`)

### Inserir no código
Abra o `index.html` e localize a linha:
```javascript
body:JSON.stringify({model:'claude-sonnet-4-20250514',...
```

Adicione o header de autorização:
```javascript
headers:{
  'Content-Type':'application/json',
  'x-api-key':'SUA_CHAVE_AQUI',
  'anthropic-version':'2023-06-01'
}
```

> ⚠️ **Atenção de segurança:** Para produção com dados reais, mova a chave para um backend (Node.js/PHP) para não expô-la no frontend.

---

## 📋 Funcionalidades

| Módulo | Descrição |
|--------|-----------|
| 📊 Dashboard | KPIs, fluxo de caixa, alertas de prioridade |
| 👥 Clientes | Carteira completa importada do Hubsoft |
| 🏦 Extratos | Upload de PDF/CSV/OFX de BTG, Caixa, C6, Safra, BB |
| 📥 Planilhas | Importação Excel do Hubsoft + Contas a Pagar |
| 📋 Pagamentos | Scoring de prioridade de contas a pagar |
| 📈 Previsão | Projeção 12 meses com 3 cenários |
| 🤝 Negociação | Contratos a renegociar e inadimplentes |
| 🤖 CFO IA | Chat direto com Maxwell, diretor financeiro IA |

---

## 🔗 Integração Hubsoft

Para conectar diretamente ao Hubsoft (sem exportar planilhas), é necessário um **proxy backend** para contornar o CORS. Exemplo em Node.js disponível sob demanda.

---

*Grupo Jet · Plataforma CFO IA · Desenvolvido com Claude AI*
