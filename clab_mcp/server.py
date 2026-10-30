import json
from typing import Optional

from mcp.server.mcpserver import MCPServer

from . import service

mcp = MCPServer(
    name="elettrolab",
    version="0.2.0",
    instructions=(
        "Laboratorio di elettronica didattico. Usa list_components per il catalogo, "
        "get_circuit per un esercizio, validate_circuit prima di simulate_circuit. "
        "I circuiti sono JSON senza coordinate: parts, nets, analysis, expect. "
        "Le scritture sono disabilitate salvo CLAB_MCP_ALLOW_WRITE=1."
    ),
)


@mcp.tool()
def list_components() -> dict:
    """Elenca i componenti disponibili con pin, parametri e limiti."""
    return service.catalog()


@mcp.tool()
def get_component(id: str) -> dict:
    """Dettaglio di un componente del catalogo."""
    return service.component(id)


@mcp.tool()
def list_exercises() -> dict:
    """Elenca esercizi integrati e progetti utente."""
    return service.list_exercises()


@mcp.tool()
def get_circuit(id: str) -> dict:
    """Restituisce il JSON completo di un esercizio o progetto e il suo layout."""
    return service.get_circuit(id)


@mcp.tool()
def render_schematic(circuit: Optional[dict] = None, id: Optional[str] = None,
                     layout: Optional[dict] = None) -> dict:
    """Genera uno schema SVG da un circuito o dall'id di un esercizio/progetto."""
    return service.render_schematic(circuit=circuit, cid=id, layout=layout)


@mcp.tool()
def validate_circuit(circuit: dict) -> dict:
    """Valida un circuito senza simularlo. Restituisce errori e avvisi strutturati."""
    return service.validate(circuit)


@mcp.tool()
def simulate_circuit(circuit: dict, include_waveforms: bool = False,
                     max_points: int = 200) -> dict:
    """Simula DC o transitorio. Le forme d'onda sono campionate a max_points."""
    return service.simulate(circuit, include_waveforms=include_waveforms,
                            max_points=max_points)


@mcp.tool()
def ac_sweep(circuit: dict, source: str, probe: str, fstart: float = 1.0,
             fstop: float = 1e6, points: int = 101) -> dict:
    """Calcola il diagramma di Bode lineare, con sorgente normalizzata a 1 V AC."""
    return service.ac_sweep(circuit, source, probe, fstart=fstart,
                            fstop=fstop, points=points)


@mcp.tool()
def check_circuit(circuit: Optional[dict] = None, id: Optional[str] = None) -> dict:
    """Confronta un circuito (o un esercizio per id) con le sue attese."""
    return service.check(circuit=circuit, cid=id)


@mcp.tool()
def sweep_parameter(circuit: dict, part: str, param: str, values: list,
                    signal: str) -> dict:
    """Ripete la simulazione su piu' valori di un parametro."""
    return service.sweep(circuit, part, param, values, signal)


@mcp.tool()
def add_component(definition: dict, overwrite: bool = False) -> dict:
    """Crea un file nel catalogo. Richiede CLAB_MCP_ALLOW_WRITE=1."""
    return service.add_component(definition, overwrite=overwrite)


@mcp.tool()
def add_exercise(circuit: dict, layout: Optional[dict] = None,
                 overwrite: bool = False) -> dict:
    """Crea un progetto in data/projects. Richiede CLAB_MCP_ALLOW_WRITE=1."""
    return service.add_exercise(circuit, layout=layout, overwrite=overwrite)


@mcp.resource("clab://catalog", mime_type="application/json")
def catalog_resource() -> str:
    return json.dumps(service.catalog(), ensure_ascii=False, indent=2)


@mcp.resource("clab://exercises", mime_type="application/json")
def exercises_resource() -> str:
    return json.dumps(service.list_exercises(), ensure_ascii=False, indent=2)


@mcp.resource("clab://exercise/{id}")
def exercise_resource(id: str) -> str:
    return json.dumps(service.get_circuit(id), ensure_ascii=False, indent=2)


@mcp.resource("clab://schema/circuit", mime_type="application/json")
def schema_resource() -> str:
    return json.dumps(service.schema(), ensure_ascii=False, indent=2)


@mcp.resource("clab://docs/{name}")
def docs_resource(name: str) -> str:
    return service.read_doc(name)


@mcp.prompt()
def progetta_circuito(obiettivo: str) -> str:
    return (
        "Progetta un circuito didattico con questo obiettivo: " + obiettivo + "\n"
        "1. Usa list_components e get_component per i pezzi disponibili.\n"
        "2. Scrivi solo parts, nets, analysis e expect; nessuna coordinata.\n"
        "3. Usa validate_circuit, poi simulate_circuit, poi check_circuit.\n"
        "4. Chiama render_schematic per produrre l'anteprima SVG.\n"
        "5. Correggi in base agli errori strutturati e mostra il JSON finale."
    )


@mcp.prompt()
def debug_circuito(circuito: str) -> str:
    return (
        "Debugga questo circuito:\n" + circuito + "\n"
        "Esegui validate_circuit, leggi gli errori, correggi un problema alla volta "
        "e verifica con simulate_circuit/check_circuit. Non cambiare i valori a caso."
    )


def main():
    mcp.run("stdio")


if __name__ == "__main__":
    main()
