# PCB (anteprima)

Elettrolab **non è un CAD PCB**: questa è un'anteprima didattica. Dal circuito
(netlist) genera un PCB a **un lato** con footprint **THT**, rame e serigrafia,
esportabile in SVG.

## Cosa fa

- catalogo `data/footprints/*.json` (pad, foro, ingombro, serigrafia);
- posizionamento automatico in riga (per ora);
- instradamento semplice: le reti non di massa a catena, la massa su una pista
  in basso;
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

I nomi dei pad devono coincidere con i pin del componente. Un componente può
forzare `"footprint": "..."`; altrimenti si usa il default per `kind`
(`clab/pcb.py`).

## Limiti (MVP)

- un lato, THT, nessun via; posizionamento in riga; router semplice **senza
  clearance/DRC**; niente Gerber/KiCad;
- non è pronto per la fabbricazione: è un'anteprima;
- la serigrafia non è ancora ottimizzata (sovrapposizioni possibili).

## Prossimi passi

- router a griglia con clearance e DRC;
- export Gerber/Excellon con **gerbonara** (Apache-2.0) o KiCad;
- due lati e vias; footprint SMD; rotazione.

## Licenza

Tutto il codice nuovo è MIT. Per il futuro export Gerber si userà `gerbonara`
(Apache-2.0, compatibile); nessun codice GPL.
