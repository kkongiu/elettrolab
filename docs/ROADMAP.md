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
- [x] 7 esercizi e 5 test del motore
- [x] Documentazione di progetto e licenza MIT

## Fase 1 - Server MCP (prossima)

Obiettivo: un LLM progetta, valida, simula e corregge un circuito senza aprire
il codice.

- [ ] Pacchetto `clab_mcp` con trasporto `stdio`
- [ ] Tool di lettura: catalogo, esercizi, schema
- [ ] `validate_circuit` con errori strutturati
- [ ] `simulate_circuit` con output limitato e riassunto delle forme d'onda
- [ ] `check_circuit` e `sweep_parameter`
- [ ] Risorse MCP per catalogo, esercizi e documentazione
- [ ] Prompt `progetta_circuito` e `debug_circuito`
- [ ] Tool di scrittura dietro `CLAB_MCP_ALLOW_WRITE=1`
- [ ] Test con client in memoria e transcript dorati

Criterio di accettazione: un LLM riceve un obiettivo, genera un circuito,
sbaglia, legge l'errore, corregge e ottiene `check` superato.

Specifica: `docs/MCP-SERVER.md`.

## Fase 2 - Interfaccia grafica

Obiettivo: l'esperienza da laboratorio, senza perdere il testo come sorgente.

Fatto (prototipo):

- [x] Visualizzatore schematico con simboli per R, C, L, V, LED, SW, pot, rele'
- [x] Corrente animata con verso e velocita' per ramo
- [x] LED che si accendono e "bruciatura" visibile
- [x] Grafico delle forme d'onda integrato con cursore temporale
- [x] Pausa/ripresa, scelta del segnale, scheda dati
- [x] Layout separato dal JSON del circuito

Da fare:

- [ ] Editor schematico con snap e trascinamento
- [ ] Pannello componenti alimentato dal catalogo
- [ ] Slider collegati ai parametri (tensione, potenziometro)
- [ ] Vista breadboard 2D con occupazione dei fori
- [ ] Salvataggio del layout dall'editor

Tecnologia attuale: Tkinter + Matplotlib, senza dipendenze di sistema.
Un frontend web resta possibile; il motore e il formato non cambiano.

## Fase 3 - Modelli avanzati

- [ ] Transistore bipolare (Ebers-Moll semplificato)
- [ ] MOSFET come interruttore
- [ ] Timer 555 comportamentale
- [ ] Porte logiche 74xx
- [ ] Analisi AC e diagrammi di Bode
- [ ] Fallback a ngspice via subprocess per subcircuiti e modelli non primitivi
- [ ] Import/export del formato CircuitJS

Il fallback a ngspice mantiene lo stesso `Result`: il resto del progetto non
deve accorgersi del cambio di motore.

## Fase 4 - Contenuti

- [ ] Set di esercizi progressivo su corrente, tensione, resistenza
- [ ] Elettronica digitale di base
- [ ] Lezioni con domande e verifiche
- [ ] Localizzazione italiana e inglese
- [ ] Pacchetti di esercizi creati dagli utenti

Regola: nessun testo, figura o materiale di terzi.

## Fase 5 - Laboratorio completo

- [ ] Breadboard 3D e jumper
- [ ] Emulazione di microcontroller (fuori scope a breve termine)
- [ ] Condivisione dei progetti
- [ ] Modalita' insegnante e classe

## Non obiettivi attuali

- Sostituire un EDA professionale (KiCad, Altium).
- Simulare schede complete o microcontroller.
- PCB, autorouting, gerber.
- Analisi termica, rumore, affidabilita'.

## Dipendenze tra le fasi

La fase 1 non richiede la GUI. La fase 2 richiede il layout deterministico, che
puo' essere sviluppato in parallelo alla fase 1. La fase 3 richiede il formato
stabile e i test di regressione. La fase 4 puo' procedere in ogni momento.

## Metriche

- `./lab check` sempre verde.
- Nessuna regressione numerica oltre il 2% sui test del motore.
- Tempo di risposta MCP sotto 100 ms per i circuiti didattici.
- Ogni nuovo componente o esercizio arriva con un test.
