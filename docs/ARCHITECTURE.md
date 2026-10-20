# Architettura

## Visione

Il progetto separa tre cose che di solito finiscono intrecciate:

1. **Descrizione** del circuito: JSON semantico, senza coordinate.
2. **Modello** dei componenti: catalogo su file, estendibile dall'utente.
3. **Motore** di simulazione: MNA in NumPy, senza dipendenze esterne.

La GUI (fase successiva) e il server MCP (fase 1) sono soltanto consumatori di
queste tre parti. Nessuna logica elettrica vive nell'interfaccia.

```
circuito.json ──> Circuit ──> MNA ──> Result ──> report / GUI / MCP
                    │           │
              data/components   violazioni, controlli
```

## Moduli

| File | Responsabilita' |
|---|---|
| `clab/units.py` | parsing e formattazione SI (`4.7k`, `1000u`, `meg`) |
| `clab/db.py` | caricamento del catalogo, merge dei parametri di istanza |
| `clab/circuit.py` | indicizzazione dei nodi, validazione, mappa pin -> nodo |
| `clab/solver.py` | matrici MNA, DC e transitorio, stati, violazioni, controlli |
| `clab/report.py` | tabelle testuali, grafico ASCII, CSV |
| `clab/cli.py` | comandi, overrides, sweep, selftest |
| `data/components/*.json` | un file per tipo di componente |
| `data/exercises/*.json` | un file per esercizio, con attese |

## Nodi e netlist

- Ogni chiave di `nets` e' una rete.
- Le reti `gnd`, `0`, `GND`, `ground`, `GROUND` sono la massa (nodo 0).
- Ogni voce e' un riferimento `PID.pin`, per esempio `R1.2` o `D1.A`.
- `circuit.py` verifica che ogni pin compaia in esattamente una rete; i pin
  mancanti sono un errore `floating_pin`, salvo il pin 2 del potenziometro in
  modalita' `rheostat`.
- I nodi non di massa ricevono un indice 0..n-1 nell'ordine di dichiarazione.

Il formato non contiene coordinate: la disposizione grafica, quando servira',
sara' un file separato prodotto dall'editor e mai dal modello linguistico.

## Sistema MNA

Incognite: `x = [tensioni di nodo, correnti di ramo]`, con una corrente di ramo
per ogni sorgente di tensione e per ogni induttore. La matrice e' densa; per i
circuiti didattici (meno di 100 nodi) la soluzione e' nell'ordine dei
microsecondi.

Stampe:

| Componente | Contributo |
|---|---|
| R | conduttanza `1/R` fra i due nodi |
| V | ramo con `v_a - v_b = V` |
| I (futuro) | iniezione di corrente |
| L (DC) | ramo con `v_a - v_b = 0` (corto) |
| L (transitorio) | ramo con `v_a - v_b - (L/dt) i = -(L/dt) i_prev` |
| C (DC) | aperto |
| C (transitorio) | conduttanza `C/dt` piu' sorgente di storia `(C/dt) v_prev` |
| LED | acceso: `Vf + Rd i`; spento: conduttanza trascurabile |
| SW | `Ron` o `Roff` secondo lo stato |
| POT | due resistenze `rtotal*pos` e `rtotal*(1-pos)` |
| RELAY | bobina resistiva, contatti COM-NC e COM-NO come resistenze di stato |

### DC

Condensatori aperti, induttori in corto. Lo stato di LED e rele' e' risolto per
iterazione di punto fisso: si risolve, si aggiornano gli stati, si ricostruisce
la matrice. Se lo stato entra in un ciclo, il circuito non ha un punto di
riposo e il risultato lo segnala (tipico dell'oscillatore a rele').

### Transitorio

Passo fisso, integrazione backward Euler: stabile incondizionatamente, adatta
alla didattica. Ogni passo:

1. costruisce il sistema con lo stato precedente;
2. risolve;
3. itera solo sui LED (max 4 volte);
4. registra tensioni e correnti;
5. aggiorna lo stato dei rele' con isteresi e tempo di permanenza `td`
   (default 10 ms), per evitare rimbalzi numerici piu' rapidi del passo.

Le condizioni iniziali sono zero: condensatori scarichi, induttori senza
corrente. Un interruttore chiuso a `t = 0` produce quindi un gradino.

### Scelta automatica di dt e durata

Euristica, sovrascrivibile con `dt` e `tstop` nell'esercizio:

- resistenza totale somma di R, potenziometri, bobine e LED;
- costanti `tau = R*C` e `tau = L/R`;
- frequenze `f0 = 1/(2*pi*sqrt(L*C))`;
- `dt = min(tau)/20`, ridotto a `1/(50*f0)` se ci sono risonanze;
- `tstop = max(6*tau, 20/f0)`, limitato a 120 s;
- massimo 300.000 passi, oltre i quali si chiede di ridurre la durata.

## Risultati

`Result` contiene:

- `nodes`: tensione finale di ogni rete;
- `currents`, `power`: per ogni componente;
- `time`, `waves`: serie temporali (`V(rete)`, `I(componente)`);
- `violations`: guasti didattici;
- `checks`: esito delle attese dell'esercizio;
- `notes`: avvisi del motore (per esempio oscillazione in DC).

Le violazioni non fermano la simulazione: servono a spiegare cosa succederebbe
nella realta'. Un LED oltre `imax` diventa `burned`, una resistenza oltre
`pmax` va in `overpower`, un condensatore oltre `vmax` in `overvoltage`, una
sorgente oltre `imax` in `short`.

## Controlli

`expect` nel JSON viene confrontato con i risultati:

| Chiave | Significato |
|---|---|
| `approx`, `tol` | valore finale entro tolleranza relativa |
| `at` | valore interpolato a un istante |
| `min`, `max` | limiti sull'intera forma d'onda |
| `violations` | elenco dei componenti che devono guastarsi |

`check` restituisce una lista di esiti con segnale, esito e dettaglio leggibile.
Il server MCP usera' lo stesso formato, con codici macchina.

## Limiti attuali

- Solo componenti primitivi elencati sopra: niente transistori, 555, logica,
  amplificatori operazionali o subcircuiti.
- Sorgenti ideali (nessuna resistenza interna modellata).
- Nessuna analisi AC, rumore, temperatura o deriva.
- Contatti del rele' modellati come resistenze: nessun rimbalzo meccanico reale.
- Un solo nodo di massa.
- Matrice densa: adatta a circuiti didattici, non a netlist grandi.
- Nessun controllo di topologia ridondante: un nodo isolato produce una matrice
  singolare, riportata come errore `singular`.

## Dipendenze

Python 3.10+ e NumPy. Il motore non usa SPICE esterni. In futuro, i componenti
non primitivi potranno essere delegati a ngspice via subprocess, mantenendo lo
stesso formato di circuito e lo stesso `Result`.
