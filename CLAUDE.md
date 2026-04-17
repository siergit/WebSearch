# Container tracking email routine

App invocada por uma routine Claude (modo remoto). Usa Playwright para
abrir a página de tracking da SeaRates, capturar screenshot full-page,
extrair todos os dados visíveis e enviar por email.

## Comportamento do routine

Quando a routine for executada, deve correr simplesmente:

```
bash setup.sh
python3 track_and_email.py
```

Ou o slash command equivalente:

```
/track-container
```

O script sai com código 0 em sucesso. Reporta ao utilizador o destinatário
e a confirmação do envio.

## Configuração fixa

- Fonte primária (default): COSCO eLines —
  `https://elines.coscoshipping.com/ebtracking/public/bill/COSU6448851830`.
  É a autoridade para containers COSU (COSCO). Sem UI de marketing em
  volta dos dados.
- Fonte fallback (default): SeaRates —
  `https://www.searates.com/container/tracking/?shipment-type=sea&number=COSU6448851830&type=BL&sealine=COSU`.
  Usada se a COSCO falhar ou não devolver dados de tracking.
- Destinatário (default): `miguel.reis@sier.pt`
- SMTP (default, já embutido no script):
  - host: `mail.enginis.net`
  - port: `465` (SSL)
  - user: `noreply@enginis.net`
  - password: `vvs-mSp88eosg1m(`

Os valores podem ser sobrepostos via env vars: `TRACKING_URL` (SeaRates),
`COSCO_URL` (COSCO), `TRACKING_SKIP_COSCO=1` (salta a COSCO),
`TRACKING_RECIPIENT`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`,
`SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_USE_SSL`.

O script só aceita uma captura como válida se a página contiver pelo
menos dois indicadores de dados reais (`Port of Loading`, `Vessel`,
`ETA`, `POL`, `POD`, `Bill of Lading`, etc.) via
`_has_tracking_data()`. Senão tenta a próxima fonte.

## Estrutura

- `track_and_email.py` — Playwright + SMTP
- `setup.sh` — instala Python deps e Chromium (idempotente)
- `requirements.txt` — dependências Python pinadas
- `.claude/commands/track-container.md` — slash command `/track-container`
- `.claude/settings.json` — hook `SessionStart` corre `setup.sh`

## Chromium / fallback

Se o download do Chromium pela Playwright falhar (CDN bloqueada na
sandbox), `setup.sh` tenta `apt-get install -y chromium` /
`chromium-browser`, depois `dnf` e `apk`. O script Python procura
automaticamente em `/usr/bin/chromium`, `/usr/bin/chromium-browser`,
`/usr/bin/google-chrome`, `/usr/bin/google-chrome-stable`,
`/snap/bin/chromium` e binários dentro de `/opt/pw-browsers/`, e pode ser
forçado com `CHROMIUM_EXECUTABLE_PATH=/caminho/para/chrome`.

Se ambos falharem: instale manualmente o pacote chromium do SO e volte
a correr o comando.

## Envio de email

**Primário — Resend HTTPS:** com o Environment configurado em Network
access = **Full** (Claude Code web → Environments → editar WebSearch),
o `POST https://api.resend.com/emails` passa. O pedido leva um
User-Agent `Chrome/...` para não apanhar Cloudflare error 1010 ("banned
by browser signature") e tem retry exponencial (4 tentativas) em
respostas 502/503/504/520-524 porque o egress proxy do routine devolve
ocasionalmente `HTTP 503 DNS cache overflow`.

A scraping também faz retry (até 3 tentativas com backoff) se a página
capturada corresponder ao erro do proxy em vez do tracker real —
detecção via `_html_looks_real()` em `track_and_email.py`.

**Fallback — SMTP (opt-in):** `mail.enginis.net:465` SSL com fallback
587/2525/25. Os portos saem sempre em timeout no sandbox, por isso só
corre se `TRACKING_TRY_SMTP=1`. Fica desligado por default para não
gastar ~80 s em timeouts.

**Modo Gmail connector (legacy):** se `TRACKING_SKIP_EMAIL=1`, o Python
salta todo o envio e imprime `===ARTIFACTS_READY=== <dir>`. Deixado
para quando não há Resend/Full access disponível — o Claude da routine
entrega via Gmail connector. Actualmente não é o caminho default.

## Artefactos

Cada corrida grava os ficheiros num subdirectório novo em
`/tmp/container-tracking/YYYYMMDD_HHMM/` (UTC) — `tracking.png`,
`tracking.html`. O directório base é sobreponível com
`TRACKING_ARTIFACTS_DIR`. Directórios antigos nunca são apagados
automaticamente.

## Desenvolvimento

- Branch principal: `claude/container-tracking-email-app-WmDLG` (usada
  como `main` enquanto o repo não tiver outra base).
- Todas as alterações devem ser commitadas e puxadas automaticamente
  para esta branch sem pedir confirmação.
- Nunca alterar o número de container ou o destinatário sem instrução
  explícita do utilizador.
