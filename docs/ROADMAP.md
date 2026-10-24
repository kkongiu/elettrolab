# Roadmap

L'ordine non e' casuale: prima il motore e i dati, poi l'interfaccia per gli
LLM, poi quella per gli umani, infine i modelli avanzati.

## Fase 0 - Nucleo (fatto)

- [x] Formato circuito JSON senza coordinate
- [x] Catalogo componenti su file
- [x] Solver MNA DC e transitorio
- [x] LED, interruttore, potenziometro, rele', RLC
- [x] Violazioni didattiche e controlli automatici
- [x] CLI, menu, grafico ASCII, CSV, sweep
- [x] 29 esercizi; 40 test core (7 motore, 11 fisica, 13 breadboard, 3 ngspice, 4 audio, 2 PCB) e 9 test MCP
- [x] Documentazione di progetto e licenza MIT

## Fase 1 - Server MCP (fatta)

Obiettivo: un LLM progetta, valida, simula e corregge un circuito senza aprire
il codice.

- [x] Pacchetto `clab_mcp` con trasporto `stdio`
- [x] Tool di lettura: catalogo, esercizi, schema
- [x] `validate_circuit` con errori strutturati
- [x] `simulate_circuit` con output limitato e riassunto delle forme d'onda
- [x] `check_circuit` e `sweep_parameter`
- [x] Risorse MCP per catalogo, esercizi e documentazione
- [x] Prompt `progetta_circuito` e `debug_circuito`
- [x] Tool di scrittura dietro `CLAB_MCP_ALLOW_WRITE=1`
- [x] Test con client in memoria e transcript dorati

Criterio di accettazione: un LLM riceve un obiettivo, genera un circuito,
sbaglia, legge l'errore, corregge e ottiene `check` superato. Implementato e
verificato con test sul trasporto `stdio`. Manca solo `render_schematic`.

Specifica: `docs/MCP-SERVER.md`.

## Fase 2 - Interfaccia grafica

Obiettivo: l'esperienza da laboratorio, senza perdere il testo come sorgente.

Fatto:

- [x] Visualizzatore schematico con simboli per R, C, L, V, LED, diodo, lampadina, trasformatore, MOSFET, SW, pot, rele'
- [x] Corrente animata con verso e velocita' per ramo
- [x] LED che si accendono e "bruciatura" visibile
- [x] Grafico delle forme d'onda integrato con cursore temporale
- [x] Pausa/ripresa, scelta del segnale, scheda dati
- [x] Layout separato dal JSON del circuito
- [x] Editor: palette, posizionamento, trascinamento, rotazione, cancellazione
- [x] Collegamento pin-to-pin con merge delle reti e instradamento automatico
- [x] Pannello proprieta' con validazione e simulazione live
- [x] Undo/redo, scorciatoie, problemi del circuito
- [x] Pannello Codice con vista circuito/layout, modifica e applicazione
- [x] Progetti in `data/projects/` con file di layout affiancato
- [x] Simbolo di massa e rele' a due poli con pin opzionali
- [x] NPN a tre stati e PUT a due stati (comportamentali)
- [x] Validazione fisica: residuo MNA, RC/RLC, NPN, PUT, ngspice
- [x] Slider live per tensione, potenziometro, R, C, L
- [x] Generatore breadboard 2D per tutti i circuiti
- [x] Editing breadboard: drag/rotate/delete, undo, validazione, sidecar
- [x] I jumper seguono i componenti quando vengono spostati o ruotati
- [x] Disposizione compatta/topologica e pulsante di ottimizzazione
- [x] Router A* dei fili sulla breadboard (colonne/rail, niente corti)
- [x] Zoom/pan della breadboard
- [x] Jumper manuali, gomma, breadboard-first e derivazione reti/sync schema
- [x] Aggiunta di componenti direttamente dalla breadboard
- [x] Step 2 dell'esercizio 11: oscillatore audio e altoparlante
- [x] Riproduzione del suono (WAV, paplay/aplay) e pulsante Ascolta
- [x] Step 3 dell'esercizio 11: amplificazione con 2N2222 e altoparlante sul collettore

Da fare:

- [ ] Trascinamento dei punti di piega dei fili
- [ ] Rinomina delle reti dall'interfaccia
- [ ] Creazione di un nuovo tipo di componente dall'editor
- [ ] "Fissa i valori attuali come attesi" per generare `expect`

Tecnologia attuale: Tkinter + Matplotlib, senza dipendenze di sistema.
Un frontend web resta possibile; il motore e il formato non cambiano.

## Fase 3 - Modelli avanzati

- [x] Transistore bipolare a tre stati (comportamentale)
- [x] PUT comportamentale
- [ ] Ebers-Moll completo per l'NPN
- [ ] PUT tarato su datasheet (η, I_H, V_ON)
- [ ] Resistenza interna di batterie e alimentatori
- [ ] Passo adattivo per i transitori rapidi
- [x] MOSFET come interruttore
- [x] Trasformatore ideale (v2 = n v1, i1 = -n i2)
- [x] Retroazione integrale e feedforward per alimentatori switching
- [ ] Controllo in corrente, limitatore e protezioni attive
- [ ] Timer 555 comportamentale
- [ ] Porte logiche 74xx
- [ ] Analisi AC e diagrammi di Bode
- [x] Confronto con ngspice per circuiti lineari e NPN
- [ ] Fallback a ngspice via subprocess per subcircuiti e modelli non primitivi
- [ ] Import/export del formato CircuitJS

Il fallback a ngspice mantiene lo stesso `Result`: il resto del progetto non
deve accorgersi del cambio di motore.

## Fase 4 - Contenuti

- [x] Progetto caricabatteria solare 12 V -> 5 V (controller + LM2596)
- [ ] Set di esercizi progressivo su corrente, tensione, resistenza
- [ ] Elettronica digitale di base
- [ ] Lezioni con domande e verifiche
- [ ] Localizzazione italiana e inglese
- [ ] Pacchetti di esercizi creati dagli utenti

Regola: nessun testo, figura o materiale di terzi.

## Fase 5 - Laboratorio completo

- [ ] Emulazione di microcontroller (fuori scope a breve termine)
- [ ] Condivisione dei progetti
- [ ] Modalita' insegnante e classe

## Fase 6 - PCB (in corso)

- [x] Catalogo footprint THT (`data/footprints/`)
- [x] Anteprima PCB: rame, pad/fori, serigrafia, disposizione a righe
- [x] Export SVG (1:1)
- [x] Router a griglia con clearance e DRC
- [ ] Export Gerber/Excellon (gerbonara, Apache-2.0)
- [ ] Export KiCad
- [ ] Due lati, vias, SMD, rotazione

## Non obiettivi attuali

- Sostituire un EDA professionale (KiCad, Altium).
- Simulare schede complete o microcontroller.
- Autorouting completo e DRC avanzato (il PCB è in Fase 6).
- Analisi termica, rumore, affidabilita'.

## Dipendenze tra le fasi

La fase 1 non richiede la GUI. La fase 2 richiede il layout deterministico, che
puo' essere sviluppato in parallelo alla fase 1. La fase 3 richiede il formato
stabile e i test di regressione. La fase 4 puo' procedere in ogni momento.

## Metriche

- `./lab check` sempre verde.
- Residuo MNA < 1e-8.
- Lineari entro il 2% dai riferimenti analitici/ngspice.
- Tempo di risposta MCP sotto 100 ms per i circuiti didattici.
- Ogni nuovo componente o esercizio arriva con un test.
