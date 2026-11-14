import json
from typing import Optional
import typer
from plant_copilot.workflow import WorkflowEngine

app = typer.Typer(help="Plant Copilot CLI - Deterministic AI Manufacturing Analytics")
engine = WorkflowEngine()


@app.command()
def ask(
    question: Optional[str] = typer.Argument(None, help="Natural language question to ask (omit if using --resume)"),
    tenant: str = typer.Option("Kalpa Appliances", "--tenant", "-t", help="Tenant company name (cannot be overridden by prompt)"),
    plant: str = typer.Option("north", "--plant", "-p", help="Plant backend: 'north' or 'south'"),
    resume: Optional[str] = typer.Option(None, "--resume", "-r", help="Resume a previous run_id from its last checkpoint"),
):
    """Answer a user question with a checkpointed Gemini AI tool-calling agent."""
    if resume:
        result = engine.resume(resume)
    else:
        if not question:
            typer.echo("Error: provide a question or --resume <run_id>.")
            raise typer.Exit(1)
        result = engine.run(question, tenant_name=tenant, plant=plant)

    cp = result["checkpoint"]
    if result["status"] == "ok":
        typer.echo(f"\n[Run ID]: {cp.run_id}")
        typer.echo(f"[Answer]: {result['answer']}")
        typer.echo(f"[Value]: {result['value']}")
        typer.echo(f"[Tokens]: {cp.token_usage}")
        typer.echo(f"[Result Hash]: {result['evidence']['result_hash']}")
    elif result["status"] == "failed_retryable":
        typer.echo(f"\n[Status]: FAILED_RETRYABLE (progress saved at step {cp.current_step})")
        typer.echo(f"[Error]: {result.get('error')}")
        typer.echo(f"[Resume Command]: python -m plant_copilot.cli ask --resume {cp.run_id}")
        raise typer.Exit(1)
    else:
        typer.echo(f"\n[Status]: {result['status']}")
        typer.echo(f"[Info]: {result.get('answer') or result.get('error')}")


@app.command()
def checkpoint(
    identifier: Optional[str] = typer.Argument(None, help="Run ID or Result Hash of the checkpoint (defaults to latest)"),
):
    """View stored checkpoint by run_id, result hash, or show the latest."""
    cp_dir = engine.checkpoint_dir
    files = sorted(cp_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        typer.echo("No checkpoints found.")
        raise typer.Exit(1)

    if not identifier or identifier.lower() == "latest":
        with open(files[0], "r", encoding="utf-8") as f:
            typer.echo(f"Showing latest checkpoint ({files[0].stem}):\n" + f.read())
        return

    cp = engine._load_checkpoint(identifier)
    if cp:
        typer.echo(cp.model_dump_json(indent=2))
        return

    for fpath in files:
        with open(fpath, "r", encoding="utf-8") as f:
            data = json.load(f)
            hashes = data.get("result_hashes", {})
            if identifier in hashes.values():
                typer.echo(f"Found checkpoint for result hash {identifier} (run_id: {data.get('run_id')}):\n")
                typer.echo(json.dumps(data, indent=2))
                return

    typer.echo(f"No checkpoint found matching run_id or result_hash: {identifier}")
    raise typer.Exit(1)


if __name__ == "__main__":
    app()
