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
- GUI con schema animato: corrente che scorre, LED che si accendono, guasti
- Breadboard 2D con fori, rail e validazione elettrica per gli esercizi base
- Editor grafico: palette, spostamento, rotazione, collegamento pin-to-pin
- Pannello "Codice": JSON del circuito e del layout, modificabile e applicabile
- Progetti utente salvati in `data/projects/`
- 10 esercizi verificati automaticamente, 7 test del motore, 11 test fisici
- 3 confronti con ngspice (LED, RC, NPN)
- Server MCP con strumenti di catalogo, validazione, simulazione, check e scrittura protetta

## Avvio rapido

```bash
cd /home/kongiu/elettrolab
./lab gui                  # laboratorio grafico animato
./lab gui exp09            # apre direttamente un esercizio
./lab                      # menu interattivo da terminale
./lab run exp09 --plot "V(m)"
./lab run exp04 --set POT1.pos=0.2
./lab sweep exp04 --sweep POT1.pos=0,0.25,0.5,0.75,1
./lab check                # esegue e verifica tutti gli esercizi
./lab selftest             # verifica il motore di simulazione
./lab test                 # test unitari e fisici (+ ngspice)
./lab db                   # catalogo componenti
```

Il launcher funziona da qualsiasi directory. In alternativa:

```bash
cd /home/kongiu/elettrolab
python3 -m clab run exp03
```

Dipendenze: Python 3.10+ e NumPy per il motore. La GUI richiede anche Tkinter
(incluso in Python su Linux) e Matplotlib. `ngspice` e' opzionale e serve solo
per i test di confronto SPICE.

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
| `test` | test unitari di documento, reti e layout |
| `db` | elenca il catalogo componenti |
| `menu` | menu interattivo (default del launcher) |
| `gui [ID]` | laboratorio grafico con schema animato |

Codici di uscita: `0` successo, `1` controlli falliti (solo con `--strict` o
`check`), `2` errore di circuito o di simulazione.

## Interfaccia grafica

![Editor grafico](docs/gui-editor.png)

`./lab gui` apre il laboratorio e l'editor: esercizi e progetti a sinistra,
palette componenti, schema al centro, proprietà e problemi a destra, JSON,
grafico e dati sotto.

- simboli disegnati dal motore: resistenze, condensatori, induttori, batterie,
  LED, interruttori, potenziometri, rele' a uno o due poli e massa
- i puntini arancioni sono la corrente: velocita' e verso seguono la corrente
  di ogni ramo; i LED si accendono in proporzione e mostrano una X quando si
  bruciano
- il transitorio scorre in loop (Pausa/Riprendi) e il cursore sul grafico segue
  l'animazione
- **editor**: scegli un componente dalla palette e cliccalo sulla tela; trascina
  per spostare, `R` per ruotare, `Canc` per eliminare, "Filo" per collegare due
  pin; `Ctrl+Z`/`Ctrl+Y` annullano
- **proprietà**: seleziona un componente per modificarne i parametri, ruotarlo,
  eliminarlo o vedere i pin e la rete; i parametri principali hanno uno slider
  live (tensione, posizione del potenziometro, R, C, L)
- **Codice**: la scheda mostra il JSON del circuito o del layout, con copia,
  modifica e "Applica"; è lo stesso linguaggio usato dagli LLM
- nel disegno, un pallino scuro è una connessione; un filo interrotto è un
  incrocio senza collegamento
- **progetti**: "Nuovo", "Salva", "Salva copia"; gli esercizi integrati restano
  protetti, i progetti finiscono in `data/projects/`

I layout dei circuiti nuovi stanno nel file affiancato `.layout.json`; il JSON
del circuito resta senza coordinate. Dettagli in `docs/GUI.md`.

![Oscillatore a rele'](docs/gui-relay.png)

## Come funziona

1. `clab/db.py` carica `data/components/*.json` in un catalogo di tipi.
2. `clab/document.py` tiene il circuito modificabile (`parts`, `nets`,
   `layout`) e permette stati incompleti mentre si disegna.
3. `clab/circuit.py` compila il documento in una netlist rigorosa: assegna un
   nodo a ogni rete, valida i pin e costruisce la mappa pin -> nodo. La massa
   e' la rete `gnd`.
4. `clab/solver.py` costruisce la matrice MNA e risolve:
   - DC: condensatori aperti, induttori in corto, punto di riposo;
   - transitorio: companion model di C e L, passo fisso, retroazione di stato
     per LED, rele' e contatti.
5. `clab/schematic.py` disegna simboli, fili, corrente e LED; `clab/gui.py`
   assembla laboratorio, editor e pannello codice.
6. `clab/report.py` formatta risultati, violazioni e grafici.
7. `clab/cli.py` espone tutto come comandi.

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

Regola per gli LLM: si scrivono solo componenti, reti e attese. Mai coordinate:
la disposizione grafica vive nel file `.layout.json` affiancato, che l'editor
aggiorna da solo. Specifica completa in `docs/CIRCUIT-FORMAT.md`.

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
| `exp08` | Oscillatore a rele' con due LED | Transitorio | contatti NC/NO, 10.4 mA per LED |
| `exp08b` | Variante a due poli | Transitorio | LED alternati su due contatti indipendenti |
| `exp09` | Tempo e condensatori | Transitorio | tau = R*C, 63% dopo una costante |
| `exp10` | Il transistor come interruttore | DC | NPN in cutoff, attivo e saturazione |
| `exp11` | Oscillatore a rilascio con PUT | Transitorio | PUT, carica RC, LED impulsivo |
| `exp13` | Friggere un LED | DC | senza resistenza il LED si brucia |
| `lrc` | RLC serie | Transitorio | risonanza e ringing, dal circuito CircuitJS dell'autore |

Mappa completa, valori attesi e criteri di scelta in `docs/EXERCISES.md`.

## LLM e server MCP

Il laboratorio e' esposto come **server MCP** (Model Context Protocol) con
trasporto `stdio`, implementato in `clab_mcp` con l'SDK MCP 2.x.

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[mcp]"
./lab mcp
```

Tool disponibili: `list_components`, `get_component`, `list_exercises`,
`get_circuit`, `validate_circuit`, `simulate_circuit`, `check_circuit`,
`sweep_parameter`, `add_component`, `add_exercise`.

```json
{
  "mcpServers": {
    "elettrolab": {
      "command": "/home/kongiu/elettrolab/.venv/bin/python",
      "args": ["-m", "clab_mcp"],
      "cwd": "/home/kongiu/elettrolab"
    }
  }
}
```

Le scritture (`add_component`, `add_exercise`) sono disabilitate salvo
`CLAB_MCP_ALLOW_WRITE=1`; i nuovi esercizi finiscono in `data/projects/`.
Specifica e stato in `docs/MCP-SERVER.md`.

## Test

```bash
./lab test                 # 25 test core (documento, fisica, ngspice, breadboard)
.venv/bin/python -m unittest discover -s tests -v   # + 9 test MCP
./lab selftest             # 7 test numerici del solver
./lab check                # 10 esercizi contro le attese
```

I test coprono partitore, LED, RC, RLC, NPN (cutoff/attivo/saturazione), PUT,
la bruciatura in transitorio, il merge delle reti, il layout, la breadboard,
il confronto con ngspice e il server MCP (tool, risorse, trasporto stdio,
scrittura protetta).
I test SPICE vengono saltati se `ngspice` non e' installato; i test MCP se
`mcp` non e' nel Python usato.

## Documentazione

- `docs/ARCHITECTURE.md` - moduli, solver, scelte numeriche, limiti
- `docs/GUI.md` - schema animato, breadboard, simboli, layout, animazione
- `docs/CIRCUIT-FORMAT.md` - schema JSON dei circuiti e delle attese
- `docs/COMPONENTS.md` - catalogo, tipi, come estendere il database
- `docs/EXERCISES.md` - esercizi, valori attesi, cosa e' simulabile
- `docs/MODELS.md` - equazioni, parametri, validita' e limiti dei modelli
- `docs/VALIDATION.md` - test, tolleranze e confronto ngspice
- `docs/MCP-SERVER.md` - specifica del server MCP per gli LLM
- `docs/ROADMAP.md` - fasi e prossimi passi
- `CONTRIBUTING.md` - convenzioni e flusso di lavoro

## Origine dei contenuti

Circuiti, esercizi e testi di questo repository sono originali. Il progetto non
include testo, figure o materiale di terzi. Ogni contributo deve rispettare
questa regola.

## Licenza

MIT, vedi `LICENSE`.
