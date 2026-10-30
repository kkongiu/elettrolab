# PCB (anteprima)

Elettrolab **non è un CAD PCB**: questa è un'anteprima didattica. Dal circuito
(netlist) genera un PCB a **un lato** con footprint THT e SMD, rame e
serigrafia, esportabile in SVG.

## Cosa fa

- catalogo `data/footprints/*.json` (pad tondi o rettangolari, foro, ingombro,
  serigrafia e mappa tra pad fisici e pin logici);
- posizionamento automatico a righe (max ~100 mm, poi va a capo);
- router A* a 8 direzioni: griglia da 0,5 mm per THT e 0,25 mm se il layout
  include SMD; clearance 0,15 mm e piste da 0,3 mm;
  massa su **bus per riga** + bus verticale; **DRC** automatico;
- serigrafia: contorni, riferimenti, valori e polarità;
- SVG in scala 1:1 (1 unità = 1 mm) e scheda **PCB** nella GUI.

## Comandi

```bash
./lab pcb exp03                 # riepilogo del layout
./lab pcb exp03 -o exp03.svg    # export SVG
```

Nella GUI: scheda **PCB** → **Esporta SVG**.

## Footprint

```json
{"id": "R_axial",
 "pads": {"1": [-5.08, 0], "2": [5.08, 0]},
 "pad": {"diameter": 2.0, "drill": 0.9},
 "body": {"type": "rect", "w": 12.7, "h": 4.5}}
```

Per piazzole SMD si dichiara la dimensione rettangolare per pin:

```json
{"id":"R_0603", "pads":{"1":[-0.8,0],"2":[0.8,0]},
 "pad_shapes":{"1":{"shape":"rect","w":0.9,"h":1.0},
                "2":{"shape":"rect","w":0.9,"h":1.0}},
 "body":{"type":"rect","w":1.6,"h":0.8}}
```

Per package con pin fisici ripetuti o pad esposto, `pad_map` associa ogni
piazzola fisica al pin elettrico dello schema (per esempio i due pad BAT del
BQ24074).

I nomi dei pad devono coincidere con i pin del componente. Un componente può
forzare `"footprint": "..."`; altrimenti si usa il default per `kind`
(`clab/pcb.py`).

## Limiti (MVP)

- un lato, nessun via; posizionamento a righe (max ~100 mm); router a
  griglia con clearance/DRC; se non c'è spazio una rete resta **non
  instradata** (segnalata); niente Gerber/KiCad;
- non è pronto per la fabbricazione: è un'anteprima; footprint generici di
  connettori, ESD e protezione batteria vanno sostituiti con quelli del
  componente scelto;
- la serigrafia non è ancora ottimizzata (sovrapposizioni possibili).

## DRC

Il DRC calcola la distanza dalle geometrie rettangolari SMD e controlla
piste-piste, piste-pad e pad-pad con clearance 0,15 mm:
`violations` è vuoto quando non ci sono sovrapposizioni. Se una rete non
trova spazio non viene disegnata una pista sovrapposta: la rete resta non
instradata e compare in `warnings` (CLI: `./lab pcb ID`; GUI: barra della
scheda PCB).

## Prossimi passi

- export Gerber/Excellon con **gerbonara** (Apache-2.0) o KiCad;
- due lati e vias; rotazione; DRC più fine e router adatto ai package SMD.

## Licenza

Tutto il codice nuovo è MIT. Per il futuro export Gerber si userà `gerbonara`
(Apache-2.0, compatibile); nessun codice GPL.
