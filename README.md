# Plant Copilot

Deterministic, multi-tenant manufacturing-analytics AI copilot for Plant North (`data/factory.db`) and Plant South (`data/south_sample.db`).

## Setup (Windows PowerShell)

    python -m venv .venv
    .\.venv\Scripts\Activate.ps1
    pip install -r requirements.txt
    $env:PYTHONPATH = "src"
    $env:GEMINI_API_KEY = "YOUR_API_KEY"
    # Optional higher free-tier RPM:
    # $env:GEMINI_MODEL = "gemini-3.1-flash-lite-preview"

## Run All Tests (72 tests)

    python -m pytest -v

## Generate answers.json

    python scripts\19_generate_answers.py

## Interactive CLI

    python -m plant_copilot.cli ask "What is running right now?" --tenant "Kalpa Appliances"
    python -m plant_copilot.cli ask "Which machine lost the most time yesterday, and why?"
    python -m plant_copilot.cli ask "What is running right now?" --plant south
    python -m plant_copilot.cli ask --resume RUN_ID
    python -m plant_copilot.cli checkpoint latest
