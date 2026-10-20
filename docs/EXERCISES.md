# Esercizi

Ogni esercizio e' un file `data/exercises/<id>.json` con circuito, note e
attese. `./lab run <id>` lo simula, `./lab check` li esegue tutti.

## Elenco

| id | Titolo | Analisi | Valori chiave | Cosa insegna |
|---|---|---|---|---|
| `exp03` | Il primo circuito | DC | `I(D1) = 15 mA`, `V(m) = 1.95 V` | la resistenza limita la corrente |
| `exp04` | Variare la tensione | DC | `I(D1) = 0.906 mA` a `pos = 0.5` | partitore resistivo, dimming |
| `exp06` | Accendere e spegnere | DC | `I(D1) = 15 mA` chiuso, `0` aperto | interruttore in serie |
| `exp08` | Oscillatore a rele' | Transitorio | `V(nc)` fra 2.98 e 9.0 V, periodo ~0.46 s | retroazione, isteresi, condensatore |
| `exp09` | Tempo e condensatori | Transitorio | `V(m) = 5.68 V` a 10 s | costante di tempo `tau = R*C` |
| `exp13` | Friggere un LED | DC | `I(D1) = 720 mA` | senza resistenza il LED si brucia |
| `lrc` | RLC serie | Transitorio | picco 9.14 V, `f0 = 15.9 Hz` | risonanza e smorzamento |

## Dettaglio

### exp03 - Il primo circuito

Batteria 9 V, resistenza 470 ohm, LED rosso. Il LED e' modellato con
`Vf = 1.8 V` e `Rd = 10 ohm`, quindi la corrente vale
`(9 - 1.8) / (470 + 10) = 15 mA`. La resistenza dissipa 106 mW, il LED 29 mW.

Esplorazioni:

```bash
./lab run exp03
./lab run exp03 --set R1.r=1k
./lab run exp03 --set R1.r=10
```

Con 10 ohm la corrente supera il massimo: il report mostra la violazione
`burned` e il controllo fallisce.

### exp04 - Variare la tensione

Potenziometro da 10 kohm come partitore, poi 470 ohm e LED. Con `pos = 0.5` il
cursore e' a 4.5 V e la corrente e' circa 0.906 mA. L'orientamento e':
`pos = 0` porta il cursore verso il pin 1 (9 V), `pos = 1` verso il pin 2 (0 V).

```bash
./lab sweep exp04 --sweep POT1.pos=0,0.25,0.5,0.75,1
```

La corrente scende da 15 mA a 0: e' il comportamento di un dimmer.

### exp06 - Accendere e spegnere

Interruttore in serie al gruppo resistenza-LED.

```bash
./lab run exp06
./lab run exp06 --set SW1.closed=false
```

Nel secondo caso la corrente e' nulla e l'attesa non e' soddisfatta: e' utile
per mostrare la differenza, non per validare l'esercizio.

### exp08 - Oscillatore a rele'

Il contatto NC alimenta la bobina (400 ohm). Appena la bobina si eccita il
contatto apre; il condensatore da 1000 uF in parallelo alla bobina la mantiene
eccitata mentre si scarica. Sotto la soglia di rilascio (3 V) il contatto
richiude e il ciclo riparte. Il LED sul contatto NO resta acceso durante la
scarica e si spegne brevemente a ogni rilascio.

Misure della simulazione: `V(nc)` fra 2.98 e 9.0 V, periodo circa 0.46 s,
`I(D1)` massima 10.4 mA. La sorgente e' ideale, quindi la ricarica del
condensatore e' istantanea e la fase di LED spento dura solo il tempo di
permanenza `td` del rele'.

```bash
./lab run exp08 --plot "V(nc)"
./lab run exp08 --plot "I(D1)"
```

In DC questo circuito non ha punto di riposo: il motore lo segnala e suggerisce
il transitorio.

### exp09 - Tempo e condensatori

`R = 10 kohm`, `C = 1000 uF`, quindi `tau = 10 s`. Dopo una costante di tempo il
condensatore e' al 63% di 9 V, cioe' 5.69 V; dopo tre costanti e' al 95%.

```bash
./lab run exp09 --plot "V(m)"
./lab run exp09 --set R1.r=5k
```

Con 5 kohm la costante dimezza: il grafico si stringe.

### exp13 - Friggere un LED

LED collegato direttamente ai 9 V. Il modello a tratti da' 720 mA contro un
massimo di 30 mA: scatta `burned`. E' il contraltare di `exp03` e spiega a cosa
serve la resistenza.

```bash
./lab run exp13
./lab run exp03
```

### lrc - RLC serie

Gradino di 5 V su `R = 10 ohm`, `L = 1 H`, `C = 100 uF`. Frequenza naturale
`f0 = 1/(2*pi*sqrt(LC)) = 15.9 Hz`, smorzamento
`zeta = (R/2)*sqrt(C/L) = 0.05`. Il condensatore supera i 9 V prima di
assestarsi a 5 V: e' il ringing.

```bash
./lab run lrc --plot "V(m)"
./lab run lrc --set R1.r=200
```

Con 200 ohm lo smorzamento critico elimina l'oscillazione.

## Come funziona la verifica

Il blocco `expect` confronta i risultati con i valori attesi. Per esempio:

```json
"expect": {
  "I(D1)": {"approx": 0.015, "tol": 0.05},
  "V(m)": {"at": 10, "approx": 5.69, "tol": 0.03, "min": 0, "max": 9.1},
  "violations": ["D1"]
}
```

`./lab check` esegue tutti gli esercizi e stampa `PASS` o `FAIL` con il
dettaglio. `./lab run <id> --strict` usa lo stesso criterio per un solo
esercizio.

## Aggiungere un esercizio

1. Copiare un file vicino e cambiare `id`, titolo, parti e reti.
2. Controllare la topologia con `./lab show <id>`.
3. Simulare con `./lab run <id>` e leggere nodi e correnti.
4. Scrivere `expect` con i valori ottenuti, con una tolleranza ragionevole.
5. Eseguire `./lab check`.

Un esercizio senza `expect` e' valido ma non verificabile: usare almeno un
controllo su corrente o tensione.

## Copertura e limiti

Coperti dal motore attuale: partitori, LED, interruttori, carica e scarica RC,
risonanza RLC, rele' con isteresi, potenziometri.

Non ancora coperti: transistori bipolari e MOSFET, timer 555, logica 74xx,
amplificatori operazionali, analisi in frequenza, trasformatori, altoparlanti,
motori e tutto cio' che richiede modelli non lineari o subcircuiti. Questi
richiedono nuovi `kind` o il fallback a ngspice descritto nella roadmap.
