# Server MCP

## Requisito

Il laboratorio deve poter essere pilotato da un LLM attraverso un **server MCP**
(Model Context Protocol). L'obiettivo non e' "generare un'immagine di un
circuito", ma chiudere il ciclo:

```
l'LLM scrive il circuito -> il server valida -> simula -> restituisce numeri
ed errori strutturati -> l'LLM corregge -> il circuito supera le attese
```

Il server e' un adapter sottile sopra `clab`: non duplica il motore e non
introduce logica elettrica propria.

## Trasporto e processo

- Trasporto principale: `stdio`, avviato dall'host MCP.
- Trasporto opzionale: HTTP locale, solo in una fase successiva.
- Comando previsto: `python3 -m clab_mcp` dalla radice del progetto.
- Dipendenza: SDK Python ufficiale `mcp`.
- Il server non esegue codice fornito dal client: accetta solo JSON di
  circuito e nomi di componenti.

## Struttura prevista

```
clab_mcp/
  __main__.py       # avvio stdio
  server.py         # registrazione tool, risorse, prompt
  tools.py          # adapter verso clab
  schemas.py        # modelli di input/output
  safety.py         # limiti, modalita' sola lettura, sandbox
tests/
  test_mcp.py       # client in memoria, transcript dorati
```

## Tool

| Tool | Scrittura | Descrizione |
|---|---|---|
| `list_components` | no | catalogo completo |
| `get_component` | no | dettaglio di un tipo |
| `list_exercises` | no | elenco degli esercizi |
| `get_circuit` | no | JSON completo di un esercizio |
| `validate_circuit` | no | validazione senza simulare |
| `simulate_circuit` | no | simulazione DC o transitorio |
| `check_circuit` | no | confronto con le attese |
| `sweep_parameter` | no | ripete la simulazione su piu' valori |
| `render_schematic` | no | SVG dello schema (fase 2) |
| `add_component` | si | crea un file nel catalogo |
| `add_exercise` | si | crea un esercizio verificato |

### `list_components`

Input: nessuno.

Output:

```json
{
  "components": [
    {"id": "resistor", "name": "Resistenza", "kind": "R",
     "pins": ["1", "2"], "params": {"r": "1k"}, "limits": {"pmax": 0.25}}
  ]
}
```

### `get_component`

Input: `{"id": "led_red"}`.

Output: oggetto del catalogo, piu' `learn` e `usage` con un esempio minimo.

### `list_exercises`

Output: `{"exercises": [{"id": "exp03", "title": "...", "analysis": "dc"}]}`.

### `get_circuit`

Input: `{"id": "exp03"}` oppure `{"path": "data/exercises/exp03.json"}`.
Il percorso e' confinato alla cartella `data/`.

Output: il JSON del circuito, non modificato.

### `validate_circuit`

Input:

```json
{"circuit": { "...": "oggetto circuito" }}
```

Output:

```json
{"ok": false,
 "errors": [
   {"code": "floating_pin", "message": "D1 (led_red): pin non collegati: K",
    "part": "D1", "pins": ["K"]}
 ]}
```

Non esegue simulazioni: e' veloce e pensato per il primo giro del ciclo LLM.

### `simulate_circuit`

Input:

```json
{
  "circuit": { "...": "oggetto circuito" },
  "include_waveforms": false,
  "max_points": 200
}
```

Output DC:

```json
{
  "ok": true,
  "analysis": "dc",
  "nodes": {"p": 9.0, "m": 1.95},
  "currents": {"V1": 0.015, "R1": 0.015, "D1": 0.015},
  "power": {"R1": 0.106, "D1": 0.029},
  "violations": [],
  "notes": []
}
```

Output transitorio: come sopra, piu' `time` e `waves` campionati a
`max_points`, piu' un riassunto per segnale (`min`, `max`, `final`). Le forme
d'onda complete non vengono mai restituite: il client puo' chiedere un CSV con
un tool dedicato in una fase successiva.

Regole:

- `max_points` predefinito 200, massimo 2000.
- `max_nodes` 200, `max_steps` 300000.
- Se il circuito non e' valido, il tool restituisce `ok: false` con gli errori
  di validazione, non un'eccezione.

### `check_circuit`

Input: `{"circuit": {...}}` oppure `{"id": "exp03"}`.

Output:

```json
{
  "ok": true,
  "checks": [
    {"signal": "I(D1)", "ok": true, "detail": "0.015 (atteso 0.015 +/- 5%)"}
  ],
  "violations": []
}
```

### `sweep_parameter`

Input:

```json
{"circuit": {...}, "part": "POT1", "param": "pos",
 "values": [0, 0.25, 0.5, 0.75, 1], "signal": "I(D1)"}
```

Output: tabella `{"rows": [{"value": 0, "signal": 0.015, "violations": []}]}`.

### `render_schematic`

Fase 2. Input: circuito. Output: stringa SVG. Il layout e' deterministico e
separato dal JSON del circuito.

### `add_component` e `add_exercise`

Disabilitati per default. Richiedono `CLAB_MCP_ALLOW_WRITE=1` e un percorso
dentro `data/`. Devono:

1. validare il nuovo oggetto;
2. rifiutare id gia' esistenti;
3. scrivere in modo atomico;
4. restituire il percorso creato.

Non devono mai sovrascrivere file esistenti senza un flag esplicito.

## Risorse

| URI | Contenuto |
|---|---|
| `clab://catalog` | catalogo componenti in JSON |
| `clab://exercises` | elenco esercizi |
| `clab://exercise/{id}` | circuito completo |
| `clab://schema/circuit` | schema JSON del formato |
| `clab://docs/{nome}` | documentazione del progetto |

## Prompt

- `progetta_circuito`: istruzioni per generare un circuito valido e verificabile
  a partire da un obiettivo didattico.
- `debug_circuito`: istruzioni per leggere gli errori strutturati e correggere
  un circuito senza cambiare i valori a caso.

## Ciclo di lavoro consigliato per l'LLM

1. `list_components` e `get_component` per i pezzi disponibili.
2. Scrittura del JSON con componenti, reti, `analysis` e `expect`.
3. `validate_circuit`: correggere `floating_pin`, `multi_net`, `no_ground`.
4. `simulate_circuit`: leggere nodi, correnti, violazioni.
5. `check_circuit`: se fallisce, confrontare i valori e correggere valori o
   topologia.
6. Solo quando i controlli passano, proporre il circuito all'utente.

## Errori

Il server usa gli stessi codici del motore (`no_ground`, `floating_pin`,
`multi_net`, `bad_value`, `singular`, `unsupported`, `too_long`) e aggiunge:

| Codice | Causa |
|---|---|
| `invalid_json` | input non deserializzabile |
| `schema_error` | campo mancante o tipo errato |
| `not_found` | esercizio o componente inesistente |
| `write_disabled` | tool di scrittura senza autorizzazione |
| `path_denied` | percorso fuori da `data/` |
| `too_large` | circuito o risposta oltre i limiti |

## Sicurezza

- Sola lettura per default.
- Nessuna esecuzione di codice, nessuna shell, nessun accesso di rete.
- Percorsi normalizzati e confinati a `data/`.
- Limiti su nodi, passi, punti e dimensione della risposta.
- Nessun segreto nei log.
- Output deterministico: stessi input, stessi numeri.

## Test del server

- Test unitari con client MCP in memoria.
- Un transcript dorato per ogni tool.
- Un test end-to-end: circuito sbagliato -> errore -> correzione -> `check`
  superato.
- Test di sicurezza: scrittura senza flag, path traversal, input enorme.

## Criteri di accettazione della fase 1

1. Un LLM, senza aprire il codice, elenca i componenti.
2. Genera un circuito per un obiettivo dato.
3. Riceve errori strutturati e li corregge.
4. Ottiene una simulazione coerente e `check` superato.
5. Crea un nuovo componente e lo usa in un circuito.

Stato: **da implementare**. Vedi `docs/ROADMAP.md`.
