# Formato del circuito

Un circuito e' un file JSON. Contiene solo semantica: componenti, reti e
attese. Non contiene coordinate, misure in pixel o informazioni di disegno.

## Schema di alto livello

| Chiave | Tipo | Obbligatoria | Descrizione |
|---|---|---|---|
| `id` | string | consigliata | identificatore, di solito il nome del file |
| `title` | string | no | titolo leggibile |
| `ref` | string | no | fonte o riferimento didattico |
| `notes` | string | no | spiegazione mostrata prima dei risultati |
| `analysis` | `"dc"` o `"transient"` | no (default `dc`) | tipo di analisi |
| `tstop` | numero | no | durata del transitorio in secondi |
| `dt` | numero | no | passo di integrazione in secondi |
| `parts` | oggetto | si | componenti, chiave = identificatore |
| `nets` | oggetto | si | reti, chiave = nome della rete |
| `expect` | oggetto | no | attese verificate automaticamente |

## Parti

```json
"parts": {
  "V1": {"type": "battery_9v"},
  "R1": {"type": "resistor", "r": "470"},
  "D1": {"type": "led_red"}
}
```

- La chiave (`V1`, `R1`, ...) e' l'identificatore usato nelle reti e nei
  risultati.
- `type` deve esistere in `data/components/`.
- Ogni altra chiave sovrascrive il parametro omonimo del catalogo.

Gli identificatori devono essere stabili: un LLM che rigenera un circuito deve
riusare gli stessi nomi, altrimenti i riferimenti nelle reti si rompono.

## Reti

```json
"nets": {
  "p": ["V1.+", "R1.1"],
  "m": ["R1.2", "D1.A"],
  "gnd": ["V1.-", "D1.K"]
}
```

- Ogni pin di ogni componente deve comparire in **una sola** rete.
- La massa e' una rete chiamata `gnd` (accettati anche `0`, `GND`, `ground`).
  Deve esistere, altrimenti il caricamento fallisce con `no_ground`.
- Una rete con un solo pin e' un nodo flottante: il motore avvisa.

## Pin opzionali e massa

Alcuni pin possono restare scollegati se il catalogo li dichiara `optional`,
per esempio i contatti non usati di un rele' a due poli. Il simbolo `GND` ha un
solo pin, che appartiene sempre alla rete `gnd`: non ha effetto elettrico ed è
il modo in cui l'editor collega una massa.

## Layout affiancato

La disposizione grafica non sta in questo JSON. Per i progetti l'editor scrive
un file affiancato:

```
data/projects/mio_circuito.json
data/projects/mio_circuito.layout.json
```

Il file di layout contiene `parts` (posizione e rotazione), `gnd_y` e, se
servono, `routes` con percorsi espliciti. Un LLM può ignorarlo: il circuito è
completo senza geometria. Specifica in `docs/GUI.md`.

## Nomi dei segnali

- Tensione di una rete: `V(nome_rete)`, per esempio `V(m)`.
- Corrente di un componente: `I(identificatore)`, per esempio `I(D1)`.
- Nei risultati di transitorio sono disponibili come forme d'onda; in DC come
  valori scalari.

## Attese

```json
"expect": {
  "I(D1)": {"approx": 0.015, "tol": 0.05},
  "V(m)": {"approx": 1.95, "tol": 0.03},
  "V(out)": {"at": 10, "approx": 5.69, "tol": 0.03, "min": 0, "max": 9.1},
  "violations": ["D1"]
}
```

| Chiave | Descrizione |
|---|---|
| `approx` | valore atteso (numerico, in unita' SI) |
| `tol` | tolleranza relativa, default 0.05 |
| `at` | istante in secondi in cui valutare `approx` (solo transitorio) |
| `min` | minimo ammesso della forma d'onda |
| `max` | massimo ammesso della forma d'onda |
| `peak_min` | il massimo della forma d'onda deve superare questa soglia |
| `mean` | media della forma d'onda |
| `mean_tol` | tolleranza relativa sulla media (default `tol`) |
| `violations` | componenti che devono risultare guasti |

Le unita' nei valori sono sempre SI: 15 mA si scrive `0.015`.

Una chiave puo' contenere una **lista** di condizioni, tutte valutate sullo
stesso segnale (utile per piu' istanti):

```json
"V(out)": [
  {"at": 0.011, "approx": 12.0, "tol": 0.05},
  {"at": 0.023, "approx": 12.0, "tol": 0.05},
  {"max": 13.0}
],
"V(m)": {"mean": 6.0, "mean_tol": 0.05}
```

## Valori con suffissi

I parametri numerici accettano stringhe con prefisso:

| Suffisso | Moltiplicatore | Esempio |
|---|---|---|
| `p` | 1e-12 | `10p` |
| `n` | 1e-9 | `100n` |
| `u`, `µ` | 1e-6 | `1000u` |
| `m` | 1e-3 | `20m` |
| `k`, `K` | 1e3 | `4.7k` |
| `M` | 1e6 | `2M` |
| `meg` | 1e6 | `1meg` |
| `G` | 1e9 | `1G` |

Attenzione: `m` e' milli, `M` e' mega; per evitare ambiguita' si puo' usare
`meg`. Sono accettati anche i simboli `ohm`, `F`, `H`, `A`, `V`, che vengono
ignorati.

## Esempio DC completo

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

## Esempio transitorio

```json
{
  "id": "rc",
  "title": "Carica di un condensatore",
  "analysis": "transient",
  "tstop": 10,
  "dt": 0.01,
  "parts": {
    "V1": {"type": "battery_9v"},
    "R1": {"type": "resistor", "r": "10k"},
    "C1": {"type": "capacitor", "c": "1000u"}
  },
  "nets": {
    "p": ["V1.+", "R1.1"],
    "m": ["R1.2", "C1.+"],
    "gnd": ["V1.-", "C1.-"]
  },
  "expect": {
    "V(m)": {"at": 10, "approx": 5.69, "tol": 0.03}
  }
}
```

Con `tau = R*C = 10 s`, dopo 10 secondi il condensatore e' al 63% di 9 V. Il
valore esatto e' `9*(1 - e^-1) = 5.689`.

## Modifiche da riga di comando

```bash
./lab run exp04 --set POT1.pos=0.2
./lab run exp06 --set SW1.closed=false
./lab sweep exp04 --sweep POT1.pos=0,0.25,0.5,0.75,1
```

`--set` non modifica il file su disco: agisce solo sulla simulazione corrente.

## Regole per la generazione da parte di un LLM

1. Non inventare tipi di componente: leggi prima il catalogo (`./lab db`).
2. Usa solo reti esplicite; niente connessioni implicite per posizione.
3. Ogni pin va collegato; se un pin e' inutilizzato, scegli un componente
   adatto invece di lasciarlo flottante.
4. Identificatori corti e stabili: `R1`, `R2`, `D1`, `C1`.
5. Un solo oggetto per componente, struttura piatta.
6. Le attese sono opzionali ma rendono il circuito verificabile: usale sempre.
7. Se una simulazione fallisce, correggi in base all'errore strutturato, non
   cambiando valori a caso.

## Errori di validazione

| Codice | Causa |
|---|---|
| `no_ground` | manca una rete di massa |
| `multiple_ground` | piu' reti dichiarate come massa |
| `unknown_part` | una rete riferisce un componente non dichiarato |
| `bad_pin_ref` | riferimento senza `PID.pin` |
| `multi_net` | lo stesso pin compare in due reti |
| `floating_pin` | un pin non e' collegato |
| `bad_value` | valore numerico non valido o non positivo |
| `singular` | matrice singolare, nodo isolato o componente aperto |
| `unsupported` | tipo non simulabile dal motore |
| `too_long` | troppi passi di transitorio |

Gli errori sono pensati per essere letti da una macchina: ogni eccezione espone
`code`, `message` e, quando utile, il componente o il pin responsabile.
