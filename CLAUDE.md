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

Ordem de tentativas:

1. **Resend** (HTTPS POST para `https://api.resend.com/emails`) — usado
   primeiro porque o sandbox da routine normalmente permite HTTPS mas
   bloqueia portas SMTP. API key default embutida; sobreponível com
   `RESEND_API_KEY`. Sender default `onboarding@resend.dev`
   (sobreponível com `RESEND_FROM`).
   **IMPORTANTE:** enquanto o domínio não for verificado no Resend, o
   free tier só aceita entregar aos emails da conta do dono. Sintoma:
   `HTTP 403 "host not in allowlist"`. Para enviar a
   `miguel.reis@sier.pt` é preciso:
   - verificar um domínio (`sier.pt` ou `enginis.net`) na dashboard do
     Resend e apontar os DNS records, e depois
   - definir `RESEND_FROM=noreply@<dominio-verificado>`.
   Sem isto, o caminho Resend falha e só SMTP pode entregar.
2. **SMTP** (`mail.enginis.net:465` SSL por default) como fallback. Se
   falhar, tenta `465/SSL`, `587/STARTTLS`, `2525`, `25` em sequência
   com timeout de 20s cada.

Se TODOS os caminhos falharem, o script sai com código 1 mas mantém os
artefactos. Reporte os caminhos ao utilizador.

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
