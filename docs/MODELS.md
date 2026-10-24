# Modelli fisici

Il motore usa **modelli comportamentali** scritti in `clab/solver.py`, non una
libreria SPICE. Le equazioni sono quelle classiche dell'analisi alle maglie
(MNA), con dispositivi a tratti per i componenti non lineari.

## Nucleo numerico

- incognite: tensioni di nodo + correnti dei rami di tensione/induttanza;
- condensatori e induttori: companion model di **backward Euler**;
- condizioni iniziali: condensatori scarichi, induttori a corrente zero;
- risoluzione: `numpy.linalg.solve`; residuo lineare `max|A·x−b|` esposto in
  `Result.residual`;
- stato di LED, relè, NPN e PUT: iterazione a punto fisso con numero massimo di
  passi; se lo stato entra in un ciclo, il risultato lo segnala.

Backward Euler è del primo ordine: introduce smorzamento numerico. Sul RLC
didattico il picco vale 9.14 V contro 9.27 V analitici (~1.5%). Il passo è
scelto nell'esercizio o con l'euristica di `_auto_timing`.

## Componenti lineari

| Tipo | Modello | Note |
|---|---|---|
| R | `V = R·I` | lineare |
| C | `I = C·dV/dt`, backward Euler | ideale, nessuna ESR |
| L | `V = L·dI/dt`, backward Euler | ideale, nessuna saturazione |
| V | sorgente ideale | nessuna resistenza interna |
| SW | `Ron` / `Roff` | stato statico o `t_close`/`t_open` |
| POT | due resistenze, `rtotal·pos` e `rtotal·(1−pos)` | lineare |
| LAMP | `V = R·I` | filamento come resistenza, senza dipendenza dalla temperatura |

Le sorgenti ideali sono una semplificazione importante: nei circuiti con
condensatori grandi la ricarica produce picchi di corrente che una batteria
reale limiterebbe con la sua resistenza interna.

## LED

Modello a tratti:

- spento: conduttanza trascurabile;
- acceso: `V = Vf + Rd·I`, con `Vf = 1.8 V`, `Rd = 10 Ω` (rosso),
  `Vf = 2.1 V` (verde);
- `imax` è il limite continuo usato per la bruciatura.

Non sono modellati breakdown inverso, capacità di giunzione, deriva termica né
la curva esponenziale del diodo.

## Relè

- bobina: resistenza `rcoil` (400 Ω), nessuna induttanza;
- contatti: `Ron`/`Roff`, isteresi `vpull`/`vdrop`;
- `td`: ritardo minimo di permanenza dello stato, usato per rappresentare la
  meccanica in modo lumped. In exp08/exp08b vale 20 ms; la GUI mostra una scia
  luminosa per rendere visibile il lampo del LED su NC.

Non sono modellati rimbalzo dei contatti, usura, forza di ritorno o dinamica
dell'armatura.

## NPN — modello a 3 stati

Non è Ebers-Moll: è un interruttore a tratti con tre stati.

| Stato | Modello |
|---|---|
| off | B-E e C-E ad alta resistenza (`1e-9 S`) |
| attivo | B-E: `0.7 V + rb·Ib`; `Ic = β·Ib` con `β = beta` |
| saturazione | C-E: `Vce = vcesat + ron·Ic` |

Parametri: `vbe=0.7 V`, `beta=240`, `vcesat=0.2 V`, `ron=0.05 Ω`, `rb=10 Ω`,
`imax=0.6 A`.

Transizioni: off→attivo se `Vbe>0.7`; attivo→saturazione se `Vce<0.2`;
saturazione→attivo se `β·Ib` è insufficiente a sostenere la corrente di carico.
`rb` è un parametro di modello, non una resistenza di base da datasheet.

Limiti: nessuna capacità di giunzione, tempo di immagazzinamento, effetto
Early, breakdown, temperatura o rumore. Va bene per switching; non per
amplificatori lineari.

## PUT — modello a 2 stati

- spento: alta resistenza A-K;
- acceso: resistenza `ron = 50 Ω` tra anodo e catodo;
- accensione: `Va > Vg + 0.6 V`;
- spegnimento: corrente di anodo `< ihold = 50 µA`;
- gate: alta impedenza (nessuna corrente di gate), la soglia è fissata dal
  partitore esterno.

È un modello comportamentale: non riproduce il rapporto intrinseco η, la
corrente di gate o la curva di anodo di un 2N6027. I parametri non sono
tarati su datasheet.

## Altoparlante e suono

L'altoparlante (`SPK`) e' un carico resistivo da 8 Ω. Il suono non e' simulato
acusticamente: si riproduce il segnale reale della corrente dell'altoparlante,
risamplato, filtrato e compresso; contiene la fondamentale e le armoniche. Il file
WAV e' riprodotto con `paplay`, `pw-play`, `aplay` o `ffplay`. Il file WAV e' riprodotto con `paplay`, `pw-play`, `aplay`
o `ffplay`. Il timbro reale dipende dall'altoparlante e dalla cassa; il tono del
simulatore serve a sentire la frequenza del circuito.

## Validazione

`./lab test` esegue i test fisici; se `ngspice` è installato, esegue anche i
confronti SPICE (altrimenti li salta).

Confronti attuali (ngspice 45.2):

| Caso | ngspice | elettrolab | Scarto |
|---|---|---|---|
| exp03 `V(m)` | 1.9676 V | 1.950 V | ~0.9% |
| exp03 `I(D1)` | 14.963 mA | 15.0 mA | ~0.3% |
| exp09 `V(m)` a 10 s | 5.6891 V | 5.6808 V | ~0.15% |
| exp10 `V(c)` | 9.9406 V | 9.9385 V | ~0.02% |
| exp10 `I(V1)` | 11.597 mA | 11.609 mA | ~0.1% |

Test interni:

- NPN: cutoff (`Vbe≈0`, `Ic≈0`), attivo (`β≈240`), saturazione (`Vce≈0.2 V`);
- PUT: soglia `Vg+0.6`, periodo ~1.036 s, convergenza del picco entro il 10%
  tra 50 µs e 25 µs;
- transitorio: un picco oltre `imax` produce `burned`;
- residuo lineare `< 1e-8` su tutti gli esercizi.

## Limiti noti

- Sorgenti ideali, nessuna resistenza interna.
- LED, NPN e PUT a tratti; niente temperatura, capacità parassite, breakdown.
- Relè senza induttanza di bobina e senza rimbalzo.
- Passo fisso: i transitori molto più rapidi di `dt` possono essere
  sotto-campionati. exp11 usa 50 µs per risolvere la scarica del PUT.
- Il PUT non è confrontato con un modello SPICE: la validazione esterna copre
  i circuiti lineari e l'NPN.
