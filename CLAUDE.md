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

## Desenvolvimento

- Branch principal: `claude/container-tracking-email-app-WmDLG` (usada
  como `main` enquanto o repo não tiver outra base).
- Todas as alterações devem ser commitadas e puxadas automaticamente
  para esta branch sem pedir confirmação.
- Nunca alterar o número de container ou o destinatário sem instrução
  explícita do utilizador.
