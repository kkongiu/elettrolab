# Catalogo componenti

Il database e' composto da un file JSON per tipo in `data/components/`. Non
esiste un elenco centrale da aggiornare: il caricamento legge la cartella e
indicizza per `id`.

## Schema di un componente

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

| Campo | Obbligatorio | Descrizione |
|---|---|---|
| `id` | si | identificatore usato in `"type"`; coincide col nome file |
| `kind` | si | modello di simulazione (vedi tabella) |
| `name` | no | nome mostrato nei report |
| `pins` | si | elenco ordinato dei pin |
| `params` | no | valori di default |
| `limits` | no | soglie per le violazioni |
| `learn` | no | nota didattica mostrata da `show` |
| `numeric` | no | forza quali parametri sono numerici |
| `optional` | no | pin che possono restare scollegati |

I parametri di istanza nel circuito sovrascrivono i default:

```json
"R1": {"type": "resistor", "r": "470"}
```

## Tipi supportati

| `kind` | Componenti | Pin | Parametri | Limiti |
|---|---|---|---|---|
| `R` | resistenze | `1`, `2` | `r` | `pmax` |
| `LAMP` | lampadine | `1`, `2` | `vn`, `p`, `r`, `pmax` | `pmax` |
| `XFMR` | trasformatori | `P+`, `P-`, `S+`, `S-` | `n`, `imax`, `imax2` | `imax`, `imax2` |
| `V` | sorgenti di tensione | `+`, `-` | `v` | `imax` |
| `LED` | LED | `A`, `K` | `vf`, `rd`, `imax` | `imax` |
| `D` | diodi | `A`, `K` | `vf`, `rd`, `imax` | `imax` |
| `SW` | interruttori | `1`, `2` (+ `FB`, `FF` per il PWM) | `closed`, `ron`, `roff`, `t_close`, `t_open`, `period`, `duty`, `t_soft`, `vref`, `ki` | - |
| `C` | condensatori | `+`, `-` | `c` | `vmax` |
| `L` | induttori | `1`, `2` | `l` | `imax` |
| `POT` | potenziometri | `1`, `2`, `W` | `rtotal`, `pos`, `mode` | - |
| `RELAY` | rele' a un polo | `COIL+`, `COIL-`, `COM`, `NC`, `NO` | `rcoil`, `vpull`, `vdrop`, `ron`, `roff`, `td` | - |
| `RELAY2` | rele' a due poli | `COIL+`, `COIL-`, `COM1`, `NC1`, `NO1`, `COM2`, `NC2`, `NO2` | come `RELAY` | - |
| `NPN` | transistore NPN | `C`, `B`, `E` | `vbe`, `beta`, `vcesat`, `ron`, `rb`, `imax` | `imax` |
| `MOS` | MOSFET canale N | `D`, `G`, `S` | `vth`, `ron`, `roff`, `imax` | `imax` |
| `PUT` | PUT | `A`, `G`, `K` | `vf`, `ron`, `ihold`, `imax` | `imax` |
| `SPK` | altoparlante | `+`, `-` | `r` | `pmax` |
| `GND` | simbolo di massa | `1` | - | - |

Un `kind` non presente in questa tabella produce l'errore `unsupported`. I
componenti non primitivi saranno delegati a ngspice in una fase successiva
(vedi `docs/ROADMAP.md`).

## Parametri

### R

- `r`: resistenza in ohm.
- `pmax`: potenza massima in watt; oltre questa soglia scatta `overpower`.

### LAMP

- `r`: resistenza del filamento in ohm (24 ohm per una 12 V 6 W).
- `vn`: tensione nominale in volt; sotto meta' di `vn` la lampadina e' spenta.
- `p`: potenza nominale, solo informativa.
- `pmax`: potenza massima in watt; oltre scatta `overpower`.
La lampadina e' modellata come una resistenza: l'accensione (alone giallo)
e' solo grafica.

### XFMR

- `n`: rapporto `N2/N1`; `v2 = n*v1` e `i1 = -n*i2`. Per 230 V -> 24 V, `n = 24/230 ~ 0,104`.
- `imax`, `imax2`: corrente massima al primario e al secondario.
Il secondario e' separato dal primario, ma nel simulatore va riferito a massa
(o a un resistore di riferimento). Non sono modellati magnetizzazione,
perdite e saturazione.

### V

- `v`: tensione in volt (sorgente DC).
- `imax`: corrente massima erogabile; oltre scatta `short`.
- La sorgente e' ideale: non ha resistenza interna.
- `wave: "sin"`: sorgente sinusoidale; `amp` e' il picco (V), `freq` in Hz,
  `offset` in V. Se `amp` manca si puo' usare `vrms`.

### LED

- `vf`: tensione di soglia.
- `rd`: resistenza dinamica, usata nel modello a tratti `V = vf + rd*I`.
- `imax`: corrente massima; oltre scatta `burned`.
- Il LED spento e' modellato con una conduttanza trascurabile.

### D

Diodo a giunzione o di potenza: stesso modello a tratti del LED
(`V = vf + rd*I`), senza emissione luminosa. `vf = 0,7 V` per il diodo
piccolo, `0,9 V` per quello di potenza; `imax` provoca `burned`.

### SW

- `closed`: stato iniziale (in DC anche stato finale).
- `ron`, `roff`: resistenze di chiusura e apertura.
- `t_close`, `t_open`: istanti di commutazione nel transitorio, in secondi.
- `period`, `duty`, `t_soft`: interruttore PWM (periodo, frazione di chiusura, rampa iniziale).
- `vref`, `ki`: retroazione integrale; con `FB` all'uscita mantiene `V(FB) = vref`.
- `FF` (opzionale): feedforward; il duty parte da `vref/V(FF)` per compensare le variazioni dell'ingresso.

### C

- `c`: capacita' in farad.
- `vmax`: tensione massima; oltre scatta `overvoltage`.
- In DC e' un circuito aperto; nel transitorio usa backward Euler.

### L

- `l`: induttanza in henry.
- `imax`: corrente massima.
- In DC e' un corto; nel transitorio e' un ramo con resistenza equivalente
  `L/dt`.

### POT

- `rtotal`: resistenza totale.
- `pos`: posizione del cursore, da 0 (verso il pin 1) a 1 (verso il pin 2).
- `mode`: `divider` usa entrambe le sezioni; `rheostat` usa solo `1`-`W` e
  lascia il pin `2` scollegabile.

### RELAY

- `rcoil`: resistenza della bobina.
- `vpull`, `vdrop`: isteresi di eccitazione e rilascio, in volt.
- `ron`, `roff`: resistenze dei contatti.
- `td`: tempo minimo di permanenza dello stato, in secondi (default 0.01).
- Il contatto `COM-NC` e' chiuso a rele' a riposo, `COM-NO` quando eccitato.
- `td` e' anche il tempo minimo di permanenza dello stato nel transitorio.

### RELAY2

Due deviatori indipendenti mossi dalla stessa bobina. I contatti sono
`COM1/NC1/NO1` e `COM2/NC2/NO2`; i contatti `NO1` e `NO2` sono dichiarati
opzionali nel catalogo, quindi un polo puo' restare inutilizzato. Il parametro
`td` permette di rendere visibile la fase a riposo nei dimostratori didattici.

### NPN

Modello a tre stati (off, attivo, saturazione), non Ebers-Moll:

- off: giunzioni ad alta resistenza;
- attivo: `Vbe = vbe + rb·Ib`, `Ic = beta·Ib`;
- saturazione: `Vce = vcesat + ron·Ic`.

Parametri tipici: `vbe=0.7 V`, `beta=240`, `vcesat=0.2 V`, `ron=0.05 Ω`,
`rb=10 Ω`. `rb` e' un parametro di modello, non una resistenza di base da
datasheet. Non ci sono capacita' di giunzione, effetto Early, breakdown o
temperatura. Adatto allo switching, non agli amplificatori lineari.

### MOS

MOSFET a canale N come interruttore: conduce tra `D` e `S` quando
`Vgs > vth`; usa `ron` da acceso e `roff` da spento. Modello comportamentale
senza capacita' di gate, body diode o transcaratteristica.

### PUT

Modello a due stati: spento (alta resistenza) e acceso (`ron` tra A e K).
Scatta quando `Va > Vg + vf`; si spegne quando la corrente scende sotto
`ihold`. Il gate e' ad alta impedenza e non ha corrente nel modello. E' un
modello comportamentale: non riproduce il rapporto intrinseco o le curve del
2N6027.

### SPK

Altoparlante da 8 Ω modellato come carico resistivo. Il motore non simula
l'acustica: riproduce il segnale reale della corrente dell'altoparlante, con la
fondamentale e le armoniche. `pmax` e' la potenza massima.

### GND

Un solo pin, che deve appartenere alla rete `gnd`. Non ha effetto elettrico: e'
il simbolo con cui l'editor collega una massa. Il motore lo ignora.

## Unita' e valori

I parametri numerici accettano stringhe con suffisso SI (`4.7k`, `1000u`,
`1meg`). Vedi `docs/CIRCUIT-FORMAT.md` per la tabella completa.

Un parametro e' considerato numerico se il suo valore di default e' convertibile
con il parser SI. Per forzare il comportamento si puo' usare la lista
`"numeric": ["parametro"]` nel file del componente.

## Convenzioni di corrente

| Segnale | Verso positivo |
|---|---|
| `I(R1)` | dal pin `1` al pin `2` |
| `I(D1)` | da `A` a `K` |
| `I(SW1)` | dal pin `1` al pin `2` |
| `I(C1)` | da `+` a `-` |
| `I(V1)` | erogata dal terminale `+` |
| `I(POT1)` | dal pin `1` al cursore `W` |
| `I(RY1)` | nella bobina, da `COIL+` a `COIL-` |

## Aggiungere un componente

Esempio: una batteria da 5 V.

1. Creare `data/components/battery_5v.json`:

```json
{
  "id": "battery_5v",
  "kind": "V",
  "name": "Batteria 5 V",
  "pins": ["+", "-"],
  "params": {"v": 5},
  "limits": {"imax": 1},
  "learn": "Sorgente ideale da 5 V."
}
```

2. Usarla in un circuito:

```json
"V1": {"type": "battery_5v"}
```

3. Verificare:

```bash
./lab db
./lab run exp03 --set V1=v
```

Il passaggio 3 e' solo un controllo che il tipo venga caricato; per una prova
completa conviene creare un esercizio dedicato.

## Regole

- Il nome del file deve essere `<id>.json`.
- I pin devono essere univoci e non vuoti.
- I parametri sono numeri o stringhe; i booleani vanno scritti `true`/`false`.
- Le note didattiche non devono contenere materiale di terzi.
- Aggiungere un componente non richiede modifiche al codice.
