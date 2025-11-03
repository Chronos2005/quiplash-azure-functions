import azure.functions as func
import datetime
import json
import logging
from azure.cosmos import CosmosClient
import os
import requests
import uuid

app = func.FunctionApp()

#Setting up database accss
COSMOS_CONN_STR = os.environ.get("AzureCosmosDBConnectionString")
DATABASE_NAME = os.environ.get("DatabaseName")
PLAYER_CONTAINER_NAME = os.environ.get("PlayerContainerName")
PROMPT_CONTAINER_NAME = os.environ.get("PromptContainerName")

# Connect to Cosmos DB account
client = CosmosClient.from_connection_string(COSMOS_CONN_STR)

# Access the database
database = client.get_database_client(DATABASE_NAME)

# Access containers
player_container = database.get_container_client(PLAYER_CONTAINER_NAME)
prompt_container = database.get_container_client(PROMPT_CONTAINER_NAME)

# Translation set up
TRANSLATOR_ENDPOINT = os.environ.get("TRANSLATOR_ENDPOINT")
TRANSLATOR_KEY = os.environ.get("TRANSLATOR_KEY")
TRANSLATOR_REGION= os.environ.get("TRANSLATOR_REGION")

SUPPORTED_LANGS = ["en", "cy", "es", "ta", "zh-Hans", "ar"]


@app.function_name(name="player_register")
@app.route(route="player/register", methods=["POST"])
def player_register(req: func.HttpRequest) -> func.HttpResponse:
    data = req.get_json()
    username = data["username"]
    password = data["password"]

    # Validation
    if len(username) < 5 or len(username) > 12:
        return func.HttpResponse(
            json.dumps({"result": False, "msg": "Username less than 5 characters or more than 12 characters"}),
            mimetype="application/json"
        )
    if len(password) < 8 or len(password) > 12:
        return func.HttpResponse(
            json.dumps({"result": False, "msg": "Password less than 8 characters or more than 12 characters"}),
            mimetype="application/json"
        )

    # Checking if that username is alredy used
    query = "SELECT * FROM players p WHERE p.username = @username"
    params = [{"name": "@username", "value": username}]
    items = list(player_container.query_items(query=query, parameters=params, enable_cross_partition_query=True))

    if len(items) > 0:
        return func.HttpResponse(
            json.dumps({"result": False, "msg": "Username already exists"}),
            mimetype="application/json"
        )

    # Create new player
    player_doc = {
        "id": username,
        "username": username,
        "password": password,
        "games_played": 0,
        "total_score": 0
    }
    player_container.create_item(player_doc)

    return func.HttpResponse(
        json.dumps({"result": True, "msg": "OK"}),
        mimetype="application/json"
    )

@app.function_name(name="player_login")
@app.route(route="player/login",methods=["GET"])
def player_login(req: func.HttpRequest) -> func.HttpResponse:
    body = req.get_json()
    username = body["username"]
    password = body["password"]

    query = f"SELECT * FROM players p WHERE p.username = '{username}'"
    items = list(player_container.query_items(query=query, enable_cross_partition_query=True))

    if not items:
        response = {"result": False , "msg": "Username or password incorrect"}

    else:
        player = items[0]
        if player.get("password")==password:
            response = {"result": True, "msg": "OK"}
        else:
            response = {"result": False, "msg": "Username or password incorrect"}
    
    return func.HttpResponse(json.dumps(response), mimetype="application/json")
    
@app.function_name(name="update_player")
@app.route(route="player/update",methods=["PUT"])
def update_player(req: func.HttpRequest) -> func.HttpResponse:
    body = req.get_json()
    username = body["username"]
    additional_games_played = body["add_to_games_played"]
    additional_score = body["add_to_score"]

    query = f"SELECT * FROM players p WHERE p.username = '{username}'"
    items = list(player_container.query_items(query=query, enable_cross_partition_query=True))

    if not items:
        response = {"result": False , "msg": "Player does not exist"}
    
    else:
        player = items[0]
        # Update fields
        player["games_played"] = player.get("games_played", 0) + additional_games_played
        player["total_score"] = player.get("total_score", 0) + additional_score


        player_container.replace_item(item=player["id"], body=player)

        response = {"result": True, "msg": "OK"}
    
    return func.HttpResponse(json.dumps(response),mimetype="application/json")


@app.function_name(name="create_prompt")
@app.route(route="prompt/create", methods=["POST"])
def create_prompt(req: func.HttpRequest) -> func.HttpResponse:
    try:
        data = req.get_json()
        username = data.get("username")
        text = data.get("text")
        tags = data.get("tags", [])

        # Validation: Text length 
        if not text or len(text) < 20 or len(text) > 120:
            return func.HttpResponse(
                json.dumps({"result": False, "msg": "Prompt less than 20 characters or more than 120 characters"}),
                mimetype="application/json"
            )

        # Validation: Player existence 
        query = "SELECT * FROM player p WHERE p.username = @username"
        params = [{"name": "@username", "value": username}]
        user = list(player_container.query_items(query=query, parameters=params, enable_cross_partition_query=True))

        if not user:
            return func.HttpResponse(
                json.dumps({"result": False, "msg": "Player does not exist"}),
                mimetype="application/json"
            )

        # detecting input language
        detect_url = f"{TRANSLATOR_ENDPOINT}/detect?api-version=3.0"
        headers = {
            "Ocp-Apim-Subscription-Key": TRANSLATOR_KEY,
            "Ocp-Apim-Subscription-Region": TRANSLATOR_REGION,
            "Content-Type": "application/json"
        }
        detect_response = requests.post(detect_url, headers=headers, json=[{"text": text}])
        detection = detect_response.json()[0]
        detected_lang = detection["language"]
        confidence = detection.get("score", 0)

        # Checking if input language is supported
        if detected_lang not in SUPPORTED_LANGS or confidence < 0.2:
            return func.HttpResponse(
                json.dumps({"result": False, "msg": "Unsupported language"}),
                mimetype="application/json"
            )

        # Translation 
        translated_texts = []
        for lang in SUPPORTED_LANGS:
            if lang == detected_lang:
                # Keep the original text for the detected language
                translated_texts.append({"language": lang, "text": text})
                continue

            translate_url = f"{TRANSLATOR_ENDPOINT}/translate?api-version=3.0&to={lang}"
            response = requests.post(
                translate_url,
                headers=headers,
                json=[{"text": text}]
            )
            result = response.json()
            translated_text = result[0]["translations"][0]["text"]
            translated_texts.append({"language": lang, "text": translated_text})

        # Remove duplicate tags 
        unique_tags = list(dict.fromkeys(tags)) 

        # Create prompt document
        prompt_doc = {
            "id": str(uuid.uuid4()),  
            "username": username,
            "texts": translated_texts,
            "tags": unique_tags
        }

        prompt_container.create_item(prompt_doc)

        return func.HttpResponse(
            json.dumps({"result": True, "msg": "OK"}),
            mimetype="application/json"
        )

    except Exception as e:
        logging.error(f"Error in create_prompt: {e}")
        return func.HttpResponse(
            json.dumps({"result": False, "msg": "Internal server error"}),
            mimetype="application/json",
            status_code=500
        )

