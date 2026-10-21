# Contribuire

## Requisiti

- Python 3.10 o superiore
- NumPy
- Git

Nessuna dipendenza di sistema oltre a Python.

## Avvio

```bash
git clone https://github.com/kkongiu/elettrolab.git
cd elettrolab
./lab test
./lab selftest
./lab check
```

Il launcher usa `python3 -m clab` dalla radice del progetto.

## Prima di proporre una modifica

```bash
./lab test
./lab selftest
./lab check
```

`./lab test` include i test fisici e, se `ngspice` e' installato, i confronti
SPICE. Per installarlo: `sudo apt-get install -y ngspice`.

Tutti gli esercizi devono restare verdi. Se un controllo cambia per una scelta
voluta, aggiornare sia il circuito sia la documentazione.

## Stile

- Codice e identificatori in inglese; messaggi utente e documentazione in
  italiano.
- Nessun commento nel codice se non per scelte numeriche non ovvie.
- Funzioni piccole, nessuna dipendenza non necessaria.
- Gli errori espongono `code`, `message` e il contesto (`part`, `pin`).
- I valori numerici passano sempre da `clab/units.py`.
- Il formato del circuito non deve contenere coordinate o dettagli grafici.

## Modificare un modello fisico

- Aggiornare `clab/solver.py` e, se serve, il catalogo.
- Aggiungere un test in `tests/test_physics.py`.
- Se possibile, confrontare con `ngspice` in `tests/test_ngspice.py`.
- Aggiornare `docs/MODELS.md` e `docs/VALIDATION.md`.

## Aggiungere un componente

1. Creare `data/components/<id>.json` seguendo `docs/COMPONENTS.md`.
2. Se serve un nuovo `kind`, aggiungere la stampa MNA in `clab/solver.py` e il
   calcolo delle correnti in `_extract`.
3. Aggiungere un test in `tests/` (o in `cmd_selftest` per il motore).
4. Aggiornare `docs/COMPONENTS.md`.

Un componente che non e' un primitivo va nella roadmap come fallback ngspice,
non implementato a mano nel solver.

## Aggiungere un esercizio

1. Creare `data/exercises/<id>.json` seguendo `docs/CIRCUIT-FORMAT.md`.
2. Verificare con `./lab show <id>` che i pin siano tutti collegati.
3. Simulare e leggere i valori con `./lab run <id>`.
4. Scrivere `expect` con tolleranze sensate.
5. Eseguire `./lab check`.
6. Aprire `./lab gui <id>` e sistemare la disposizione; per gli esercizi
   integrati il layout va in `clab/layouts.py`.
7. Aggiornare la tabella in `docs/EXERCISES.md` e nel README.

I progetti utente usano due file: `<nome>.json` (circuito) e
`<nome>.layout.json` (geometria). Il primo deve restare privo di coordinate.

## Documentazione

La documentazione sta in `docs/` ed e' parte del progetto. Una modifica al
formato o ai comandi richiede un aggiornamento contestuale di:

- `README.md`
- `docs/CIRCUIT-FORMAT.md`
- `docs/COMPONENTS.md` o `docs/EXERCISES.md`
- `docs/GUI.md` se cambia lo schema o l'animazione
- `docs/MCP-SERVER.md` se cambia l'interfaccia per gli LLM

## Contenuti di terzi

Non inserire testo, immagini, tabelle o figure provenienti da libri, corsi o
siti. Circuiti, esercizi e spiegazioni devono essere originali. Le topologie
elettriche e i valori sono fatti tecnici; le descrizioni no.

## Commit

Messaggi brevi, all'imperativo, in inglese:

```
Add capacitor overvoltage check
Fix relay dwell time in transient
Document the MCP tool surface
```

Un commit = una modifica coerente. Non includere file generati (`__pycache__`,
CSV, risultati di simulazione).

## Licenza

Contribuendo accetti che il codice sia distribuito con licenza MIT (vedi
`LICENSE`).
