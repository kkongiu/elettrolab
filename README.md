# elettrolab

Laboratorio di elettronica didattico in Python per Linux: i circuiti sono dati
(JSON), non disegni. Un motore MNA risolve in corrente continua e nel tempo,
un catalogo di componenti su file rende la libreria espandibile senza toccare
il codice, e ogni esercizio dichiara i valori attesi per verificarsi da solo.

Nato come laboratorio didattico progressivo per circuiti base; formato e
database sono generici e non legati a un corso specifico.

## Stato

- Motore MNA: DC e transitorio (backward Euler)
- Componenti primitivi: R, V, L, C, LED, interruttore, potenziometro, rele'
- Violazioni didattiche: LED bruciato, resistenza in sovrapotenza, condensatore
  in sovratensione, cortocircuito della sorgente
- CLI con menu, grafico ASCII, CSV, sweep di parametri
- 7 esercizi verificati automaticamente, 5 test del motore
- GUI e server MCP: pianificati (vedi `docs/MCP-SERVER.md` e `docs/ROADMAP.md`)

## Avvio rapido

```bash
cd /home/kongiu/elettrolab
./lab                      # menu interattivo
./lab run exp09 --plot "V(m)"
./lab run exp04 --set POT1.pos=0.2
./lab sweep exp04 --sweep POT1.pos=0,0.25,0.5,0.75,1
./lab check                # esegue e verifica tutti gli esercizi
./lab selftest             # verifica il motore di simulazione
./lab db                   # catalogo componenti
```

Il launcher funziona da qualsiasi directory. In alternativa:

```bash
cd /home/kongiu/elettrolab
python3 -m clab run exp03
```

Dipendenze: Python 3.10+ e NumPy. Nessun'altra libreria.

## Comandi

| Comando | Descrizione |
|---|---|
| `list` | elenca gli esercizi disponibili |
| `run ID` | simula un esercizio e stampa nodi, correnti, potenze e controlli |
| `run ID --set PID.param=valore` | modifica un parametro prima della simulazione |
| `run ID --plot "V(nodo)"` | grafico ASCII del segnale (o `--plot none`) |
| `run ID --csv file.csv` | esporta tutte le forme d'onda |
| `sweep ID --sweep PID.param=v1,v2,...` | ripete la simulazione su piu' valori |
| `show ID` | mostra componenti, reti, attese e note didattiche |
| `check` | esegue tutti gli esercizi e confronta con le attese |
| `selftest` | test numerici del solver |
| `db` | elenca il catalogo componenti |
| `menu` | menu interattivo (default del launcher) |

Codici di uscita: `0` successo, `1` controlli falliti (solo con `--strict` o
`check`), `2` errore di circuito o di simulazione.

## Come funziona

1. `clab/db.py` carica `data/components/*.json` in un catalogo di tipi.
2. `clab/circuit.py` legge il circuito, assegna un nodo a ogni rete, valida i
   pin e costruisce la mappa pin -> nodo. La massa e' la rete `gnd`.
3. `clab/solver.py` costruisce la matrice MNA e risolve:
   - DC: condensatori aperti, induttori in corto, punto di riposo;
   - transitorio: companion model di C e L, passo fisso, retroazione di stato
     per LED, rele' e contatti.
4. `clab/report.py` formatta risultati, violazioni e grafici.
5. `clab/cli.py` espone tutto come comandi.

Dettagli in `docs/ARCHITECTURE.md`.

## Formato del circuito

```json
{
  "id": "exp03",
  "title": "Il primo circuito",
  "analysis": "dc",
  "parts": {
    "V1": {"type": "battery_9v"},
    "R1": {"type": "resistor", "r": "470"},
    "D1": {"type": "led_red"}
  },
  "nets": {
    "p": ["V1.+", "R1.1"],
    "m": ["R1.2", "D1.A"],
    "gnd": ["V1.-", "D1.K"]
  },
  "expect": {
    "I(D1)": {"approx": 0.015, "tol": 0.05},
    "V(m)": {"approx": 1.95, "tol": 0.03}
  }
}
```

Regola per gli LLM: si scrivono solo componenti, reti e attese. Mai coordinate.
Specifica completa in `docs/CIRCUIT-FORMAT.md`.

## Database componenti

Un file JSON per componente in `data/components/`:

```json
{
  "id": "led_red",
  "kind": "LED",
  "name": "LED rosso",
  "pins": ["A", "K"],
  "params": {"vf": 1.8, "rd": 10, "imax": 0.03},
  "limits": {"imax": 0.03},
  "learn": "Ha bisogno di una resistenza in serie."
}
```

Aggiungere un componente = aggiungere un file. Dettagli e tipi supportati in
`docs/COMPONENTS.md`.

## Esercizi

| id | Titolo | Analisi | Cosa insegna |
|---|---|---|---|
| `exp03` | Il primo circuito | DC | LED con resistenza, 15 mA |
| `exp04` | Variare la tensione | DC | partitore con potenziometro |
| `exp06` | Accendere e spegnere | DC | interruttore in serie |
| `exp08` | Oscillatore a rele' | Transitorio | retroazione, isteresi, condensatore |
| `exp09` | Tempo e condensatori | Transitorio | tau = R*C, 63% dopo una costante |
| `exp13` | Friggere un LED | DC | senza resistenza il LED si brucia |
| `lrc` | RLC serie | Transitorio | risonanza e ringing, dal circuito CircuitJS dell'autore |

Mappa completa, valori attesi e criteri di scelta in `docs/EXERCISES.md`.

## LLM e server MCP

Requisito di progetto: esporre il laboratorio come **server MCP** (Model
Context Protocol) con trasporto `stdio`, cosi' che un LLM possa elencare i
componenti, validare un circuito, simularlo, correggere gli errori strutturati
e creare nuovi esercizi in un ciclo chiuso.

Il progetto del server, i tool, le risorse e il formato degli errori sono in
`docs/MCP-SERVER.md`. Non e' ancora implementato.

## Test

```bash
python3 -m clab selftest   # 5 test numerici del solver
python3 -m clab check      # 7 esercizi contro le attese
```

I test coprono partitore, LED, RC, RLC e la bruciatura del LED.

## Documentazione

- `docs/ARCHITECTURE.md` - moduli, solver, scelte numeriche, limiti
- `docs/CIRCUIT-FORMAT.md` - schema JSON dei circuiti e delle attese
- `docs/COMPONENTS.md` - catalogo, tipi, come estendere il database
- `docs/EXERCISES.md` - esercizi, valori attesi, cosa e' simulabile
- `docs/MCP-SERVER.md` - specifica del server MCP per gli LLM
- `docs/ROADMAP.md` - fasi e prossimi passi
- `CONTRIBUTING.md` - convenzioni e flusso di lavoro

## Origine dei contenuti

Circuiti, esercizi e testi di questo repository sono originali. Il progetto non
include testo, figure o materiale di terzi. Ogni contributo deve rispettare
questa regola.

## Licenza

MIT, vedi `LICENSE`.
