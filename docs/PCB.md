# PCB (anteprima)

Elettrolab **non è un CAD PCB**: questa è un'anteprima didattica. Dal circuito
(netlist) genera un PCB a **un lato** con footprint **THT**, rame e serigrafia,
esportabile in SVG.

## Cosa fa

- catalogo `data/footprints/*.json` (pad, foro, ingombro, serigrafia);
- posizionamento automatico a righe (max ~90 mm, poi va a capo);
- router a griglia (0,5 mm) con **clearance** 0,3 mm e A* a 8 direzioni;
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

I nomi dei pad devono coincidere con i pin del componente. Un componente può
forzare `"footprint": "..."`; altrimenti si usa il default per `kind`
(`clab/pcb.py`).

## Limiti (MVP)

- un lato, THT, nessun via; posizionamento a righe (max ~90 mm); router a
  griglia con clearance/DRC; se non c'è spazio una rete resta **non
  instradata** (segnalata); niente Gerber/KiCad;
- non è pronto per la fabbricazione: è un'anteprima;
- la serigrafia non è ancora ottimizzata (sovrapposizioni possibili).

## DRC

Il router usa una griglia da 0,5 mm con clearance 0,3 mm (piste 0,6 mm).
Dopo l'instradamento un **DRC** controlla piste-piste, piste-pad e pad-pad:
`violations` è vuoto quando non ci sono sovrapposizioni. Se una rete non
trova spazio non viene disegnata una pista sovrapposta: la rete resta non
instradata e compare in `warnings` (CLI: `./lab pcb ID`; GUI: barra della
scheda PCB).

## Prossimi passi

- export Gerber/Excellon con **gerbonara** (Apache-2.0) o KiCad;
- due lati e vias; footprint SMD; rotazione; DRC più fine.

## Licenza

Tutto il codice nuovo è MIT. Per il futuro export Gerber si userà `gerbonara`
(Apache-2.0, compatibile); nessun codice GPL.
