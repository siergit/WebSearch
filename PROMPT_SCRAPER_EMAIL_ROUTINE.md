# Prompt — Rotina Claude Code: scraper headless + envio por email

Template para gerar, num projecto novo, uma rotina Claude Code (modo
remoto) que faz scraping de um site com Playwright + Chromium headless
e envia o resultado por email via Resend HTTPS.

Como usar: preenche os **PARÂMETROS** no topo e cola o bloco
"PROMPT A ENVIAR AO CLAUDE" num `claude` novo, na raiz de um repo
vazio (ou num branch novo). O Claude cria todos os ficheiros,
`bash setup.sh` e executa o script.

---

## PARÂMETROS — preencher antes de enviar

```
PROJECT_NAME        = <slug do projecto, ex.: container-tracking>
SCRIPT_ENTRY        = <nome do .py principal, ex.: track_and_email.py>
SLASH_COMMAND       = <nome do slash, ex.: /track-container>

TARGET_URL_PRIMARY  = <URL principal a fazer scrape>
TARGET_URL_FALLBACK = <URL alternativa, opcional>
DATA_IDENTIFIER     = <ID único que tem de estar visível na pagina quando os dados carregam
                       — ex.: "COSU6448851830" (container), "PT50..." (IBAN),
                       "TSLA" (ticker). O scraper só aceita a captura
                       se este string aparecer no texto renderizado.>
DATA_KEYWORDS       = <3-5 labels/abreviações específicas, case-insensitive,
                       que SÓ apareçam em páginas com dados reais. Evitar
                       palavras que apareçam em FAQ/marketing. Exemplos:
                       "POL|POD|ETA|ETD|Vessel|Voyage" para shipping;
                       "Last Price|Bid|Ask|Volume|PE" para stocks.>
DATE_REQUIRED       = <true/false. Se true, a heurística exige também
                       uma data reconhecível (ex.: 2026-04-25 ou 25 Apr 2026).
                       Deixa true se os dados tipicamente incluem timestamps.>

RECIPIENT           = <email de destino>
RESEND_FROM         = <"Label <noreply@dominio-verificado>">
                      -- o dominio TEM de estar verificado no Resend com
                      SPF + DKIM + DMARC senao cai em spam
RESEND_API_KEY      = <re_... gerado no dashboard do Resend>

SUBJECT_PREFIX      = <prefixo fixo do assunto, ex.: "Container tracking">

ARTIFACTS_BASE_DIR  = /tmp/<PROJECT_NAME>
```

---

## PROMPT A ENVIAR AO CLAUDE

Cria uma rotina Claude Code em modo remoto que faz scraping headless
e envia email. Gera exactamente estes ficheiros, nada mais:

1. `setup.sh` — bootstrap idempotente.
2. `requirements.txt` — só `playwright>=1.58.0`.
3. `{SCRIPT_ENTRY}` — Playwright + Resend.
4. `.claude/settings.json` — permissões, env vars, SessionStart hook.
5. `.claude/commands/{slash-command-base}.md` — slash command.
6. `CLAUDE.md` — instruções do projecto.

Todos com os parâmetros listados acima substituídos. Abaixo estão as
**restrições obrigatórias** — vieram de experiência real a correr
rotinas Claude Code. NÃO inventes alternativas a menos que peça.

### Infra-estrutura / rede do sandbox da rotina

- A rotina corre num sandbox com **egress proxy** que:
  - Filtra domínios por **allowlist do Environment** (Claude Code web
    → Environments → Network access → **Full** ou **Custom** com
    `api.resend.com` + hosts de scraping). **Não** está nas settings
    da rotina; está nas settings do Environment.
  - Devolve HTTP 403 com body `Host not in allowlist` quando bloqueia.
  - Devolve HTTP 503 intermitente com body `DNS cache overflow` sob
    carga — é um bug de LRU do proxy, não é do destino.
  - Cloudflare em frente de `api.resend.com` rejeita `Python-urllib/X`
    com **error 1010** ("banned by browser signature"). Qualquer
    request HTTP feito em Python tem de levar User-Agent tipo
    `Mozilla/5.0 ... Chrome/124.0 Safari/537.36`.
  - **Portos SMTP (25/465/587/2525) estão sempre bloqueados.** Usar
    exclusivamente Resend HTTPS. Deixar SMTP como opt-in
    (`TRACKING_TRY_SMTP=1`) para não queimar tempo em timeouts.

### Chromium

- O sandbox da rotina já vem com Chromium em
  `/opt/pw-browsers/chromium-<ver>/chrome-linux/chrome` (tipicamente
  1194+). **Descobrir e reutilizar** antes de tentar download.
- `setup.sh` deve ser idempotente:
  1. Se `python3 -c "import playwright"` funciona, saltar `pip install`.
  2. Procurar `/usr/bin/chromium{,-browser}`, `/usr/bin/google-chrome{,-stable}`,
     `/snap/bin/chromium` e `glob /opt/pw-browsers/chromium-*/chrome-linux/chrome`.
  3. Se nenhum existe, `python3 -m playwright install chromium` com
     timeout 90s.
  4. Se o CDN falhar, `apt-get install -y chromium || chromium-browser`,
     depois `dnf`, depois `apk`.
  5. `exit 0` no final mesmo em falha (para o SessionStart hook não
     rebentar; o Python faz re-detecção em runtime).
- Launch args obrigatórios: `--no-sandbox --ignore-certificate-errors`.
- **Playwright ≥ 1.58** para compatibilidade com o Chromium pré-bundled.
- **Não** passar `--headless=old`; Chromium novo removeu esse modo e
  rebenta a launch com `TargetClosedError`. Usar `headless=True`
  (Playwright moderno passa `--headless=new`).
- Respeitar `CHROMIUM_EXECUTABLE_PATH` como override para debug.

### Scraping

- Ir a TARGET_URL_PRIMARY; se falhar ou não conseguir dados, cair em
  TARGET_URL_FALLBACK.
- `page.goto(url, wait_until="domcontentloaded", timeout=45_000)` —
  **não** usar `wait_until="networkidle"`; widgets com polling
  background nunca disparam networkidle.
- A seguir, `page.wait_for_load_state("networkidle", timeout=10_000)`
  envolto em try/except (best-effort).
- `_dismiss_overlays(page)` — clicar em "Accept all", "I agree",
  `#onetrust-accept-btn-handler`, `[aria-label=Close]`.
- **Wait for data**: `page.wait_for_function()` que exige:
  - `DATA_IDENTIFIER` presente em `document.body.innerText`;
  - E (se DATE_REQUIRED) uma data-like regex no body:
    `\\b\\d{4}[-/]\\d{1,2}[-/]\\d{1,2}\\b|...`
  - Timeout 45s. Se timeout, o código continua e deixa a heurística
    Python decidir.
- Scroll para o elemento que contém `DATA_IDENTIFIER`
  (`page.get_by_text(id).first.scroll_into_view_if_needed()`) antes do
  screenshot. Isto ancora a imagem aos dados, não ao hero banner.
- Screenshot `full_page=True`.
- Guardar:
  - `tracking.png` (ou equivalente)
  - `tracking.html` (sanitizado, ver secção "Sanitização HTML")
  - `tracking-raw.html` (original, só para debug local)

### Heurísticas de aceitação

Duas funções distintas:

- `_html_looks_real(html)` — rejeita páginas de erro do proxy:
  - False se `html` contém `host not in allowlist` ou
    `dns cache overflow`.
  - False se `len(html.strip()) <= 200`.
  - True caso contrário.
  - **Não** requerer keywords específicas do site (falha com fallbacks).

- `_has_tracking_data(text, identifier)` — aceita só dados reais:
  - False se `identifier.upper() not in text.upper()`.
  - False se não houver data (regex acima) — quando DATE_REQUIRED.
  - False se matchar negativos: `无数据`, `"no data"`, `"not found"`.
  - True se a regex de `DATA_KEYWORDS` matchar ≥ 1 vez.

Retry:
- Cada fonte: 2 tentativas (primeira; se `_html_looks_real` falha →
  5s backoff e 2ª; se `_has_tracking_data` falha → 3s backoff e 2ª).
- Depois salta para a próxima fonte. No fim, se nada resultou, emite
  `===SCRAPE_WARNING===` no log mas continua para enviar o email (com
  a melhor captura que tivemos, ou a última tentada).

### Sanitização HTML (para passar antivírus)

Anexar HTML bruto no email apanha falsos positivos de AV
(ESET → `JS/Kryptik.CLV`). Antes de anexar, correr:

- Strip `<script>`, `<iframe>`, `<noscript>`, `<object>`, `<embed>`,
  `<applet>` (incluindo conteúdo).
- Strip atributos `on\\w+=...` (event handlers).
- Substituir `href|src|action="javascript:..."` por `="#"`.

Guardar o raw na pasta de artifacts como `*-raw.html` só para debug.

### Envio por email (Resend HTTPS)

- Endpoint: `https://api.resend.com/emails` via `urllib.request`
  (evitar `requests` para não adicionar deps).
- Headers obrigatórios:
  - `Authorization: Bearer <key>`
  - `Content-Type: application/json`
  - `Accept: application/json`
  - `User-Agent: Mozilla/5.0 ... Chrome/124.0 Safari/537.36`
    (sem isto, 403 com `error code: 1010`)
- Payload: `from`, `to: [...]`, `subject`, `text`, `html`,
  `attachments: [{filename, content (base64)}, ...]`.
- **Retry obrigatório**: até 4 tentativas com backoff **10s / 30s / 60s**
  em `502/503/504/520/521/522/523/524`.
- Antes de cada retry, **warm-up HEAD** ao `api.resend.com` para
  primar o DNS cache do proxy.
- Timeout do POST: 60s (payload + proxy lento).
- Log delimitado: `===RESEND_RESPONSE_BEGIN===\nHTTP {code}\n{body}\n===RESEND_RESPONSE_END===`.
- **Sender domain verificado no Resend com SPF + DKIM + DMARC.**
  Domínio só com verificação base cai em spam no MX do destinatário.
  Idealmente o sender é `noreply@<dominio-do-destinatario>` com DNS
  auto-configurado.

### Assunto / corpo do email

- Subject: `{SUBJECT_PREFIX} {DATA_IDENTIFIER} via {source_label} - {YYYY-MM-DD HH:MM UTC}`
- Body HTML: lista com `DATA_IDENTIFIER`, source, URL, captured_at,
  page title. Seguido de `<pre>` com o texto scraped.
- Body plain: versão equivalente sem HTML.
- Attachments:
  - `{project}.png` (screenshot)
  - `{project}.html` (sanitizado)
  - `metadata.json` (container/id, source, source_url, captured_at,
    page_title)

### Artefactos

- `ARTIFACTS_BASE_DIR / RUN_TIMESTAMP` onde
  `RUN_TIMESTAMP = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")`.
- Override com env var `{PROJECT}_ARTIFACTS_DIR`.
- Nunca apagar dirs antigas automaticamente.

### Logging verbatim (anti-paráfrase)

A rotina Claude tem tendência a parafrasear a saída do script.
Contra-medidas:

- Instalar uma classe `_Tee` que duplica stdout/stderr para
  `<ARTIFACTS_DIR>/run.log`.
- Imprimir `===RUN_LOG_PATH=== <path>` como primeira linha.
- Delimitar blocos críticos com markers `===FOO_BEGIN===` /
  `===FOO_END===`.
- Connectivity probe no início:
  ```
  ===CONNECTIVITY_PROBE===
    api.resend.com: OK (200)
    <host-do-scrape>: HTTP 503 ''
  ===CONNECTIVITY_PROBE_END===
  ```
  (Keep list reduzida a 2 hosts — evita evict-thrash no DNS cache do
  proxy.)
- Exit code distinto por cenário (0 = envio OK, 1 = falha completa).
- O slash command deve exigir ao Claude da rotina que devolva
  **apenas** o `run.log` num code-fence + `EXIT=<n>`.

### `.claude/settings.json`

```json
{
  "permissions": {
    "allow": [
      "Bash(bash setup.sh)",
      "Bash(python3 {SCRIPT_ENTRY})",
      "Bash(cat {ARTIFACTS_BASE_DIR}/*/run.log)",
      "Bash(ls {ARTIFACTS_BASE_DIR}/*)",
      "Bash(python3 -m pip install:*)",
      "Bash(python3 -m playwright install:*)"
    ]
  },
  "env": {"{PROJECT}_SKIP_EMAIL": "0"},
  "hooks": {
    "SessionStart": [{
      "hooks": [{
        "type": "command",
        "command": "bash setup.sh >/tmp/{PROJECT}-setup.log 2>&1 || true"
      }]
    }]
  }
}
```

### `.claude/commands/{slash-command-base}.md`

```markdown
---
description: <descrição curta>
allowed-tools: Bash(bash setup.sh), Bash(python3 {SCRIPT_ENTRY}), Bash(cat {ARTIFACTS_BASE_DIR}/*/run.log)
---

Corre a rotina. Faz isto literalmente e não parafraseies.

1. `bash setup.sh`
2. `python3 {SCRIPT_ENTRY}` — regista o exit code.
3. `cat $(ls -1dt {ARTIFACTS_BASE_DIR}/*/run.log | head -1)`
4. Responde com UM code-fence contendo o `run.log` completo, exactamente
   como foi produzido. Sem resumo, sem tradução, sem reescrita.
5. Depois do code-fence acrescenta uma linha final: `EXIT=<code>`.

Mais nada. Sem comentários, sem conclusões.
```

### `CLAUDE.md`

Secções:

- **Comportamento da rotina** — comando ou slash; exit 0 em sucesso.
- **Configuração fixa** — URLs primária/fallback, destinatário,
  domínio do sender, API key do Resend. Listar todos os env vars
  overridables.
- **Heurística de aceitação** — explicar que só aceita captura se
  tiver DATA_IDENTIFIER + data + keyword; senão tenta próxima fonte.
- **Chromium / fallback** — descrever onde procura.
- **Envio de email** — Resend primário; SMTP opt-in via env; modo
  skip-email para delegar ao connector Gmail da rotina.
- **Artefactos** — dir por run em UTC.
- **Desenvolvimento** — branch principal do projecto; commits
  automáticos; o que NUNCA alterar sem instrução explícita (IDs,
  destinatário).

### Configuração no Environment (UMA vez, no Claude Code web)

- Editar o Environment associado → Network access → **Full** OU
  **Custom** com allowlist:
  - `api.resend.com`
  - domínio(s) do scraping
- Setup script do Environment pode ficar default (`#!/bin/bash`
  vazio); o `setup.sh` do repo é que faz tudo.

### Anti-padrões — evita

- `wait_until="networkidle"` como critério único.
- Aceitar a captura só por termos como "bill of lading" no texto
  (matcham FAQ em landing pages).
- Retry em ciclos curtos (<10s) para 503 do proxy — não dá tempo.
- Envio SMTP como caminho primário.
- `Python-urllib` a falar com Cloudflare sem UA.
- Anexar HTML bruto com `<script>` (AV flag).
- Ficheiros de documentação inventados — ficar pelos 6 listados.
- Criar o repo sem um branch dedicado (usar sempre feature branch,
  push com `-u`, PR draft).

---

## Checklist de validação (correr manualmente após gerar)

```bash
bash setup.sh
python3 {SCRIPT_ENTRY}
cat $(ls -1dt {ARTIFACTS_BASE_DIR}/*/run.log | head -1)
```

Expected no run.log:
- `===CONNECTIVITY_PROBE===` com `api.resend.com: OK (200)` e host
  do scraping OK ou 503 (tolerável).
- `===SCRAPE_WARNING===` **ausente**.
- `widget: tracker populated with <ID> + date` ou equivalente.
- `===RESEND_RESPONSE_BEGIN=== HTTP 200 {"id":"..."}` .
- `EXIT=0`.

Expected na inbox (verificar spam!):
- Email com screenshot ancorado nos dados.
- Attachment HTML sem ser marcado como trojan.
- Subject com source label.
