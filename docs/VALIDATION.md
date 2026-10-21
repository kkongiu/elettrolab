# Validazione

## Comandi

```bash
./lab test        # test unitari + fisica + ngspice (se installato)
./lab selftest    # test numerici del solver
./lab check       # esercizi contro le attese
```

`ngspice` e' opzionale per l'uso normale, obbligatorio per i test di confronto:

```bash
sudo apt-get install -y ngspice
ngspice --version
```

I test ngspice vengono saltati automaticamente se `ngspice` non e' nel `PATH`.

## Cosa viene verificato

| Test | Cosa controlla |
|---|---|
| `test_document.py` | reti, merge, layout, salvataggio |
| `test_physics.py` | residuo MNA, RC/RLC, NPN, PUT, violazioni |
| `test_ngspice.py` | confronto con SPICE su LED, RC, NPN |
| `test_breadboard.py` | breadboard: generator, jumper, editing, corti, fili mancanti |
| `test_audio.py` | frequenza dell'oscillatore audio e rendering WAV |
| `test_mcp.py` | tool MCP, risorse, prompt, trasporto stdio, scrittura |

Tolleranze usate:

- lineari: 2% sul valore, 1e-8 sul residuo;
- LED/RC/NPN: 10-15% sul punto di lavoro, per tenere conto dei modelli
  comportamentali;
- convergenza PUT: 10% sul picco tra 50 µs e 25 µs;
- periodo PUT: 0.95-1.12 s.

## Risultati attuali

Tutti i test passano: 37 test core e 9 MCP (2 di trasporto MCP vengono
saltati se si usa il Python di sistema senza SDK). I numeri principali sono in
`docs/MODELS.md`.

## Aggiungere una verifica

1. Per un caso analitico, aggiungere un test in `tests/test_physics.py`.
2. Per un confronto SPICE, aggiungere un test in `tests/test_ngspice.py` e
   usare `clab/spice.py`.
3. Se il componente non e' esportabile in SPICE, motivarlo nel test o nel
   documento dei modelli.

## Limiti

La validazione esterna copre i circuiti lineari e l'NPN con un modello SPICE
standard. Il PUT e il relè sono comportamentali e non hanno un equivalente
SPICE diretto in questo repository; la loro verifica e' analitica e
qualitativa.
