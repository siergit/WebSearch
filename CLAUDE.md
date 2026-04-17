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

- URL alvo (default): <https://www.searates.com/container/tracking/?shipment-type=sea&number=COSU6448851830&type=BL&sealine=COSU>
- Destinatário (default): `miguel.reis@sier.pt`
- SMTP (default, já embutido no script):
  - host: `mail.enginis.net`
  - port: `465` (SSL)
  - user: `noreply@enginis.net`
  - password: `vvs-mSp88eosg1m(`

Os valores podem ser sobrepostos via env vars: `TRACKING_URL`,
`TRACKING_RECIPIENT`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`,
`SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_USE_SSL`.

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

**Primário — Gmail connector (routine Claude):** o sandbox da routine
tem um egress proxy que devolve `403 Host not in allowlist` para hosts
não pré-aprovados (bloqueia `api.resend.com`) e faz timeout em portas
SMTP. Por isso o envio é feito pelo próprio Claude da routine, usando
o connector Gmail que está anexo à routine.

- `.claude/settings.json` define `TRACKING_SKIP_EMAIL=1`, pelo que o
  Python só faz scraping e grava os artefactos. Imprime em stdout uma
  linha `===ARTIFACTS_READY=== <dir>` com os paths de `tracking.png` e
  `tracking.html`, seguidos do recipient.
- O slash command `/track-container` indica à routine Claude que tem de
  ler essa linha e chamar o Gmail connector com `to`, `subject`, `body`
  e as attachments.

**Fallback — Resend / SMTP (desactivado por default):** o script ainda
tem o caminho Resend (`https://api.resend.com/emails`, sender
`noreply@resend.unikrobotics.com`) e SMTP (`mail.enginis.net:465` SSL,
com fallback 587/2525/25). Para reactivar, desligue `TRACKING_SKIP_EMAIL`
ou passe `TRACKING_SKIP_EMAIL=0`. Só vai funcionar se os hosts
correspondentes entrarem na allowlist do Environment (Claude Code web
→ Environments → Network access → Custom).

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
