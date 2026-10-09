# Quiplash Backend

A serverless backend for a Quiplash-style party game, built on **Azure Functions (Python v2 programming model)**. It manages player accounts and multilingual prompts, using:

- **Azure Cosmos DB** – storage for players and prompts
- **Azure AI Translator** – detects a prompt's language and translates it into every supported language
- **Azure AI Content Safety** – moderates prompts for harmful content

Supported languages: English (`en`), Welsh (`cy`), Spanish (`es`), Tamil (`ta`), Simplified Chinese (`zh-Hans`) and Arabic (`ar`).

## Project structure

```
.
├── function_app.py         # All HTTP and Cosmos DB–triggered functions
├── test_all_functions.py   # Integration test suite covering every function
├── tests/                  # Earlier per-function tests
├── host.json               # Functions host config (route prefix removed)
├── requirements.txt        # Python dependencies
└── local.settings.json     # Local secrets and config (git-ignored)
```

## API

All HTTP endpoints use `FUNCTION` auth level, so requests must include a function key, either as an `x-functions-key` header or a `?code=` query parameter. `host.json` sets `routePrefix` to `""`, so routes are served from the root (e.g. `/player/register`, not `/api/player/register`).

Every endpoint takes a JSON body, including the `GET` endpoints. Unless noted otherwise, responses have the form `{"result": <bool>, "msg": <string>}`.

### Players

#### `POST /player/register`

Registers a new player.

```json
{ "username": "alice123", "password": "password1" }
```

| Condition | `msg` |
|---|---|
| Username not 5–12 characters | `Username less than 5 characters or more than 12 characters` |
| Password not 8–12 characters | `Password less than 8 characters or more than 12 characters` |
| Username already taken | `Username already exists` |
| Success | `OK` |

New players are stored with `games_played: 0` and `total_score: 0`.

#### `GET /player/login`

```json
{ "username": "alice123", "password": "password1" }
```

Returns `OK` on success, or `Username or password incorrect`.

#### `PUT /player/update`

Increments a player's stats.

```json
{ "username": "alice123", "add_to_games_played": 1, "add_to_score": 50 }
```

Returns `OK`, or `Player does not exist`.

### Prompts

#### `POST /prompt/create`

Creates a prompt, detects its language and stores translations in all supported languages.

```json
{ "username": "alice123", "text": "The worst thing to say at a wedding", "tags": ["funny", "wedding"] }
```

| Condition | `msg` |
|---|---|
| Text not 20–120 characters | `Prompt less than 20 characters or more than 120 characters` |
| Player not found | `Player does not exist` |
| Language unsupported, or detection confidence below 0.2 | `Unsupported language` |
| Success | `OK` |

Duplicate tags are removed. The stored document looks like:

```json
{
  "id": "<uuid>",
  "username": "alice123",
  "texts": [{ "language": "en", "text": "..." }, { "language": "cy", "text": "..." }],
  "tags": ["funny", "wedding"]
}
```

#### `POST /prompt/moderate`

Runs the English text of each prompt through Azure AI Content Safety (Hate, Sexual, SelfHarm, Violence). A prompt is flagged when its average severity is greater than 2. IDs that don't exist, or that have no English text, are skipped silently.

```json
{ "prompt-ids": ["<id1>", "<id2>"] }
```

Response:

```json
[{ "prompt-id": "<id1>", "outcome": false, "average_severity": 0.0 }]
```

#### `POST /prompt/delete`

Deletes every prompt belonging to a player.

```json
{ "player": "alice123" }
```

Returns `{"result": true, "msg": "<n> prompts deleted"}`.

### Utilities

#### `GET /utils/get`

Returns all prompts written by any of the given players that have at least one of the given tags.

```json
{ "players": ["alice123", "bob4567"], "tag_list": ["funny"] }
```

The response is a JSON array of prompt documents.

#### `utils_welcome` (Cosmos DB trigger)

Runs on changes to the player container. When a document with `games_played == 0` and `total_score == 0` appears (a new registration), it creates a translated welcome prompt (`"Welcome to COMP3207, <username>"`) for that player with no tags. Lease state is kept in a `leases` container, which is created automatically.

## Configuration

Create `local.settings.json` in the project root (it is git-ignored, so don't commit it):

```json
{
  "IsEncrypted": false,
  "Values": {
    "FUNCTIONS_WORKER_RUNTIME": "python",
    "AzureWebJobsStorage": "",
    "AzureCosmosDBConnectionString": "AccountEndpoint=...;AccountKey=...;",
    "DatabaseName": "quiplash",
    "PlayerContainerName": "player",
    "PromptContainerName": "prompt",
    "TranslationEndpoint": "https://api.cognitive.microsofttranslator.com/",
    "TranslationKey": "<translator-key>",
    "TRANSLATOR_REGION": "<translator-region>",
    "ContentSafetyEndpoint": "https://<resource>.cognitiveservices.azure.com/",
    "ContentSafetyKey": "<content-safety-key>",
    "DeploymentURL": "https://<app-name>.azurewebsites.net",
    "FunctionAppKey": "<function-key>"
  }
}
```

When deploying, set the same values as Application Settings on the Function App.

The prompt container must be partitioned on `/username`, because `/prompt/delete` deletes by that partition key.

## Running locally

Prerequisites: Python 3.10+ and [Azure Functions Core Tools](https://learn.microsoft.com/azure/azure-functions/functions-run-local) v4.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
func start
```

The app runs at `http://localhost:7071`.

## Testing

`test_all_functions.py` is an integration suite that calls the running endpoints and checks the results directly in Cosmos DB.

> **Warning:** before each test, the suite deletes **every document** in the player and prompt containers. Run it only against a development database.

Start the app with `func start`, then in another terminal run:

```bash
python -m unittest test_all_functions -v
```

The tests read settings from `local.settings.json`, falling back to environment variables. To test the deployed app instead of the local one, set `BASE_URL = DEPLOYED_URL` in `test_all_functions.py`.

## Deployment

Deploy with Core Tools:

```bash
func azure functionapp publish <function-app-name>
```

Or use the Azure Functions extension in VS Code (the config is in `.vscode/`).
