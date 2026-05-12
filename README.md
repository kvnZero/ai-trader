## Trader

Starter project using:

- Python 3.12
- Flask
- Tailwind CSS
- uv

### Development

Install Python dependencies:

```bash
uv sync
```

Install frontend dependencies:

```bash
npm install
```

Run the Flask app:

```bash
uv run flask --app main:app --debug run
```

Run the full platform with standalone workers:

```bash
./scripts/start.sh
```

Check worker / review / snapshot status:

```bash
./scripts/status.sh
```

The status script prints:

- worker health
- issue timeline
- review summary
- replay summary
- backtest summary
- recent recommendation snapshots

Watch Tailwind CSS:

```bash
npm run dev
```

Create a production CSS build:

```bash
npm run build
```

### Worker Topology

- `web`: Flask UI and API surface
- `monitoring worker`: persistent watchlist refresh loop
- `sentiment worker`: persistent sentiment ingestion loop

You can also run workers independently:

```bash
uv run python -m app.workers.monitoring
uv run python -m app.workers.sentiment
```

Disable embedded monitoring inside the web process when using standalone workers:

```bash
TRADER_ENABLE_EMBEDDED_MONITORING=0 uv run python main.py
```
