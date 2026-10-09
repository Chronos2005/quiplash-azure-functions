import azure.functions as func
import datetime
import json
import logging
from azure.cosmos import CosmosClient
import os
import requests
import uuid
import time

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
TRANSLATOR_ENDPOINT = os.environ.get("TranslationEndpoint")
TRANSLATOR_KEY = os.environ.get("TranslationKey")
TRANSLATOR_REGION= os.environ.get("TRANSLATOR_REGION")

SUPPORTED_LANGS = ["en", "cy", "es", "ta", "zh-Hans", "ar"]

CONTENT_SAFETY_ENDPOINT = os.environ.get("ContentSafetyEndpoint")
CONTENT_SAFETY_KEY = os.environ.get("ContentSafetyKey")

@app.function_name(name="player_register")
@app.route(route="player/register", methods=["POST"],auth_level=func.AuthLevel.FUNCTION)
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
    query = "SELECT * FROM player p WHERE p.username = @username"
    params = [{"name": "@username", "value": username}]
    items = list(player_container.query_items(query=query, parameters=params, enable_cross_partition_query=True))

    if len(items) > 0:
        return func.HttpResponse(
            json.dumps({"result": False, "msg": "Username already exists"}),
            mimetype="application/json"
        )

    # Create new player
    player_doc = {
        "id": str(uuid.uuid4()),
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
@app.route(route="player/login",methods=["GET"],auth_level=func.AuthLevel.FUNCTION)
def player_login(req: func.HttpRequest) -> func.HttpResponse:
    body = req.get_json()
    username = body["username"]
    password = body["password"]

    query = f"SELECT * FROM player p WHERE p.username = '{username}'"
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
@app.route(route="player/update",methods=["PUT"],auth_level=func.AuthLevel.FUNCTION)
def update_player(req: func.HttpRequest) -> func.HttpResponse:
    body = req.get_json()
    username = body["username"]
    additional_games_played = body["add_to_games_played"]
    additional_score = body["add_to_score"]

    query = f"SELECT * FROM player p WHERE p.username = '{username}'"
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
@app.route(route="prompt/create", methods=["POST"],auth_level=func.AuthLevel.FUNCTION)
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
@app.function_name(name="moderate_prompt")
@app.route(route="prompt/moderate", methods=["POST"],auth_level=func.AuthLevel.FUNCTION) 
def moderate_prompt(req: func.HttpRequest) -> func.HttpResponse:
    logging.info("Moderating prompts...")

    try:
        data = req.get_json()
        prompt_ids = data.get("prompt-ids", [])
    except Exception as e:
        logging.error(f"Invalid JSON body: {str(e)}")
        return func.HttpResponse(
            json.dumps({"result": False, "msg": f"Invalid JSON body: {str(e)}"}),
            mimetype="application/json",
            status_code=400
        )

    # API setup
    headers = {
        "Ocp-Apim-Subscription-Key": CONTENT_SAFETY_KEY,
        "Content-Type": "application/json"
    }

    url = f"{CONTENT_SAFETY_ENDPOINT}/contentsafety/text:analyze?api-version=2024-09-01"

    results = []

    for prompt_id in prompt_ids:
        

        text_to_moderate = None
        try:

            query = "SELECT * FROM c WHERE c.id = @prompt_id"
            params = [{"name": "@prompt_id", "value": prompt_id}]
            
            items = list(prompt_container.query_items(
                query=query, 
                parameters=params, 
                enable_cross_partition_query=True
            ))

            if items:
                prompt_doc = items[0]
                # Find the English text as required by the spec
                for text_obj in prompt_doc.get("texts", []):
                    if text_obj.get("language") == "en":
                        text_to_moderate = text_obj.get("text")
                        break
                if not text_to_moderate:
                    logging.warning(f"Prompt {prompt_id} found but has no 'en' text.")
            else:
                # If a prompt-id does not exist, do not return error.
                logging.warning(f"Prompt {prompt_id} not found in database.")
                
        except Exception as e:
            logging.error(f"Error fetching prompt {prompt_id} from Cosmos DB: {e}")
            continue # Skip this prompt if DB read fails
        
        # If no prompt was found or it had no 'en' text, skip to the next ID
        if not text_to_moderate:
            continue



        body = {
            "text": text_to_moderate,
            "categories": ["Hate", "Sexual", "SelfHarm", "Violence"],
            "outputType": "FourSeverityLevels"
        }

        try:
            response = requests.post(url, headers=headers, json=body)
            response.raise_for_status() # Raise an exception for bad status codes
            analysis = response.json()
        except Exception as e:
            logging.error(f"Error calling Content Safety API for {prompt_id}: {e}")
            continue # Skip this prompt if API call fails

        # Extract severity scores
        categories = analysis.get("categoriesAnalysis", [])
        avg_severity = 0.0 

        if categories:
            try:
                severities = [c["severity"] for c in categories]
                if severities: # Avoid division by zero
                    avg_severity = sum(severities) / len(severities)
            except KeyError:
                logging.error(f"Content Safety API response format unexpected for {prompt_id}")
                continue # Skip if response format is wrong

        # Determine outcome based on spec
        outcome = avg_severity > 2

        results.append({
            "prompt-id": prompt_id,
            "outcome": outcome,
            "average_severity": round(avg_severity, 2) 
        })

    return func.HttpResponse(
        json.dumps(results), 
        mimetype="application/json",
        status_code=200
    )

@app.function_name(name="delete_prompt")
@app.route(route="prompt/delete", methods=["POST"],auth_level=func.AuthLevel.FUNCTION)
def delete_prompt(req: func.HttpRequest) -> func.HttpResponse:
    logging.info("Processing request to delete prompts by player.")

    try:
        data = req.get_json()
        username = data.get("player")
    except Exception as e:
        logging.error(f"Invalid JSON body: {str(e)}")
        return func.HttpResponse(
            json.dumps({"result": False, "msg": "Invalid JSON body"}),
            mimetype="application/json",
            status_code=400
        )

    if not username:
        return func.HttpResponse(
            json.dumps({"result": False, "msg": "Missing 'player' key"}),
            mimetype="application/json",
            status_code=400
        )

    try:
        
        query = "SELECT c.id FROM c"
        
        items_to_delete = list(prompt_container.query_items(
            query=query,
            partition_key=username  
        ))
        
        deleted_count = 0
        for item in items_to_delete:
            item_id = item["id"]
        
            prompt_container.delete_item(item=item_id, partition_key=username)
            deleted_count += 1
            

        response_msg = f"{deleted_count} prompts deleted"
        response_body = {"result": True, "msg": response_msg}
        
        return func.HttpResponse(
            json.dumps(response_body),
            mimetype="application/json"
        )

    except Exception as e:
        logging.error(f"Error deleting prompts for {username}: {e}")
        return func.HttpResponse(
            json.dumps({"result": False, "msg": "An internal error occurred"}),
            mimetype="application/json",
            status_code=500
        )

@app.function_name(name="utils_get") #
@app.route(route="utils/get", methods=["GET"],auth_level=func.AuthLevel.FUNCTION)  
def utils_get(req: func.HttpRequest) -> func.HttpResponse:
    try:
        data = req.get_json()
    except ValueError:
        return func.HttpResponse(
            json.dumps({"error": "Invalid or missing JSON body"}),
            status_code=400,
            mimetype="application/json"
        )

    
    players = data.get("players", [])
    tags = data.get("tag_list", [])

   
    query = """
    SELECT * FROM c
    WHERE ARRAY_CONTAINS(@players, c.username)
    AND EXISTS (
        SELECT VALUE t 
        FROM t IN c.tags 
        WHERE ARRAY_CONTAINS(@tag_list, t)
    )
    """

    params = [
        {"name": "@players", "value": players},
        {"name": "@tag_list", "value": tags}
    ]

    try:
        items = list(prompt_container.query_items(
            query=query,
            parameters=params,
            enable_cross_partition_query=True 
        ))

       
        return func.HttpResponse(
            json.dumps(items, ensure_ascii=False),
            status_code=200,
            mimetype="application/json"
        )

    except Exception as e:
        logging.error(f"Error in /utils/get: {str(e)}") 
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            mimetype="application/json"
        )

@app.function_name(name="utils_welcome")
@app.cosmos_db_trigger(
    arg_name="documents",
    database_name=DATABASE_NAME,
    container_name=PLAYER_CONTAINER_NAME,
    connection="AzureCosmosDBConnectionString",
    lease_container_name="leases", 
    create_lease_container_if_not_exists=True 
) 
def utils_welcome(documents: func.DocumentList) -> None:
    logging.info(f"Cosmos DB trigger processing {len(documents)} documents.")
    

    for doc in documents:
        try:
    
            # We identify a new registration by checking if the scores are 0.
            is_new_player = (doc.get("games_played") == 0 and doc.get("total_score") == 0)
            
            if is_new_player:
                username = doc.get("username")
                if not username:
                    logging.warning("Document with score 0 had no username.")
                    continue
                    
                logging.info(f"New player detected: {username}. Creating welcome prompt.")
                
       
                source_text = f"Welcome to COMP3207, {username}"
                source_lang = "en"
                translated_texts = [{"language": source_lang, "text": source_text}]
                
                # Get list of languages to translate 
                langs_to_translate = [lang for lang in SUPPORTED_LANGS if lang != source_lang]

                if langs_to_translate:
                    headers = {
                        "Ocp-Apim-Subscription-Key": TRANSLATOR_KEY,
                        "Ocp-Apim-Subscription-Region": TRANSLATOR_REGION,
                        "Content-Type": "application/json"
                    }
                    translate_url = f"{TRANSLATOR_ENDPOINT}/translate?api-version=3.0&to=" + "&to=".join(langs_to_translate)
                    
                    response = requests.post(
                        translate_url,
                        headers=headers,
                        json=[{"text": source_text}]
                    )
                    response.raise_for_status() # Check for errors
                    
                    translations = response.json()[0]["translations"]
                    for trans in translations:
                        translated_texts.append({"language": trans["to"], "text": trans["text"]})

                # Create the full prompt document
                prompt_doc = {
                    "id": str(uuid.uuid4()),
                    "username": username,
                    "texts": translated_texts,
                    "tags": [] 
                }

                # Insert into the prompt container
                prompt_container.create_item(prompt_doc)
                logging.info(f"Welcome prompt created for {username}.")

        except Exception as e:
            logging.error(f"Error processing document for {doc.get('id')}: {e}")
            pass