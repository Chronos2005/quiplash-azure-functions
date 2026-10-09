import unittest
import requests
import json
import os
import time
import uuid
from azure.cosmos import CosmosClient

# --- Load Settings and Initialize Clients ---
# This is done once when the module is imported.

try:
    with open('local.settings.json') as settings_file:
        settings = json.load(settings_file)['Values']
except FileNotFoundError:
    print("Warning: local.settings.json not found. Attempting to use environment variables.")
    settings = os.environ

# Ensure all required settings are present
REQUIRED_SETTINGS = [
    "AzureCosmosDBConnectionString", "DatabaseName",
    "PlayerContainerName", "PromptContainerName", "FunctionAppKey"
]
for key in REQUIRED_SETTINGS:
    if key not in settings:
        raise ValueError(f"Missing required setting: {key}")

# Initialize Cosmos DB Clients
COSMOS_CLIENT = CosmosClient.from_connection_string(
    settings['AzureCosmosDBConnectionString']
)
DATABASE = COSMOS_CLIENT.get_database_client(settings['DatabaseName'])
PLAYER_CONTAINER = DATABASE.get_container_client(settings['PlayerContainerName'])
PROMPT_CONTAINER = DATABASE.get_container_client(settings['PromptContainerName'])

# --- Base URL and Auth ---
LOCAL_URL = 'http://localhost:7071/'
DEPLOYED_URL = 'https://quiplash-ram1g23-geftavf6dja3ekbk.francecentral-01.azurewebsites.net'
BASE_URL = LOCAL_URL
FUNCTION_KEY = settings['FunctionAppKey']
HEADERS = {'x-functions-key': FUNCTION_KEY}

# --------------------------------------------


class BaseTestCase(unittest.TestCase):
    """
    Base class for all test cases.
    Handles database cleaning before each test.
    """
    # Share clients across all test cases
    player_container = PLAYER_CONTAINER
    prompt_container = PROMPT_CONTAINER

    def setUp(self):
        """Clean up both containers before each test."""
        # Clear players
        for item in self.player_container.query_items(
                query="SELECT * FROM c",
                enable_cross_partition_query=True):
            self.player_container.delete_item(item, partition_key=item["id"])
        
        # Clear prompts
        for item in self.prompt_container.query_items(
                query="SELECT * FROM c",
                enable_cross_partition_query=True):
            # Correct partition key for prompts is "username"
            self.prompt_container.delete_item(item, partition_key=item["username"])

    def _create_player(self, username, password, games=0, score=0):
        """Helper to create a player directly in the DB."""
        player_doc = {
            "id": str(uuid.uuid4()),
            "username": username,
            "password": password,
            "games_played": games,
            "total_score": score
        }
        self.player_container.create_item(player_doc)
        return player_doc

# --------------------------------------------

class TestPlayerRegisterFunction(BaseTestCase):
    """Tests for /player/register"""
    TEST_URL = f"{BASE_URL}/player/register"

    def test_valid_registration(self):
        """Test that a valid player can be successfully registered."""
        payload = {"username": "player01", "password": "password1"}
        response = requests.post(self.TEST_URL, json=payload, headers=HEADERS)
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertTrue(data["result"])
        self.assertEqual(data["msg"], "OK")

        # Check DB
        results = list(self.player_container.query_items(
            query=f"SELECT * FROM c WHERE c.username = '{payload['username']}'", 
            enable_cross_partition_query=True))
        self.assertEqual(len(results), 1)
        player_doc = results[0]
        self.assertEqual(player_doc["games_played"], 0)
        self.assertEqual(player_doc["total_score"], 0)
    
    def test_duplicate_username(self):
        """Test registering an existing username returns an error."""
        self._create_player("player01", "password123") # Pre-create player

        payload = {"username": "player01", "password": "password1"}
        response = requests.post(self.TEST_URL, json=payload, headers=HEADERS)
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertFalse(data["result"])
        self.assertEqual(data["msg"], "Username already exists")

    def test_username_too_short(self):
        """Test usernames < 5 chars."""
        payload = {"username": "abc", "password": "password1"}
        response = requests.post(self.TEST_URL, json=payload, headers=HEADERS)
        data = response.json()
        self.assertFalse(data["result"])
        self.assertEqual(data["msg"], "Username less than 5 characters or more than 12 characters")

    def test_username_too_long(self):
        """Test usernames > 12 chars."""
        payload = {"username": "thisiswaytoolong", "password": "password1"}
        response = requests.post(self.TEST_URL, json=payload, headers=HEADERS)
        data = response.json()
        self.assertFalse(data["result"])
        self.assertEqual(data["msg"], "Username less than 5 characters or more than 12 characters")

    def test_password_too_short(self):
        """Test passwords < 8 chars."""
        payload = {"username": "validuser", "password": "short"}
        response = requests.post(self.TEST_URL, json=payload, headers=HEADERS)
        data = response.json()
        self.assertFalse(data["result"])
        self.assertEqual(data["msg"], "Password less than 8 characters or more than 12 characters")
    
    def test_password_too_long(self):
        """Test passwords > 12 chars."""
        payload = {"username": "validuser", "password": "thispasswordistoolong"}
        response = requests.post(self.TEST_URL, json=payload, headers=HEADERS)
        data = response.json()
        self.assertFalse(data["result"])
        self.assertEqual(data["msg"], "Password less than 8 characters or more than 12 characters")

# --------------------------------------------

class TestPlayerLoginFunction(BaseTestCase):
    """Tests for /player/login"""
    TEST_URL = f"{BASE_URL}/player/login"

    def setUp(self):
        super().setUp()
        self._create_player("login_user", "good_password")

    def test_successful_login(self):
        payload = {"username": "login_user", "password": "good_password"}
        response = requests.get(self.TEST_URL, json=payload, headers=HEADERS)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["result"])
        self.assertEqual(data["msg"], "OK")

    def test_wrong_password(self):
        payload = {"username": "login_user", "password": "wrong_password"}
        response = requests.get(self.TEST_URL, json=payload, headers=HEADERS)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["result"])
        self.assertEqual(data["msg"], "Username or password incorrect")
    
    def test_nonexistent_user(self):
        payload = {"username": "no_user", "password": "good_password"}
        response = requests.get(self.TEST_URL, json=payload, headers=HEADERS)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["result"])
        self.assertEqual(data["msg"], "Username or password incorrect")

# --------------------------------------------

class TestPlayerUpdateFunction(BaseTestCase):
    """Tests for /player/update"""
    TEST_URL = f"{BASE_URL}/player/update"

    def setUp(self):
        super().setUp()
        self.player_doc = self._create_player("update_user", "pass", games=10, score=100)

    def test_successful_update(self):
        payload = {"username": "update_user", "add_to_games_played": 5, "add_to_score": 50}
        response = requests.put(self.TEST_URL, json=payload, headers=HEADERS)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["result"])
        self.assertEqual(data["msg"], "OK")

        # Verify in DB
        updated_doc = self.player_container.read_item(
            item=self.player_doc["id"], partition_key=self.player_doc["id"])
        self.assertEqual(updated_doc["games_played"], 15) # 10 + 5
        self.assertEqual(updated_doc["total_score"], 150) # 100 + 50

    def test_update_nonexistent_player(self):
        payload = {"username": "no_user", "add_to_games_played": 5, "add_to_score": 50}
        response = requests.put(self.TEST_URL, json=payload, headers=HEADERS)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["result"])
        self.assertEqual(data["msg"], "Player does not exist")

# --------------------------------------------

class TestPromptCreateFunction(BaseTestCase):
    """Tests for /prompt/create"""
    TEST_URL = f"{BASE_URL}/prompt/create"

    def setUp(self):
        super().setUp()
        self._create_player("prompt_creator", "password123",games=1)

    def test_successful_prompt_creation(self):
        payload = {
            "username": "prompt_creator",
            "text": "This is a valid prompt for testing the translation service.",
            "tags": ["test", "valid", "test"] # Duplicate tag
        }
        response = requests.post(self.TEST_URL, json=payload, headers=HEADERS)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["result"], f"API returned error: {data.get('msg')}")
        self.assertEqual(data["msg"], "OK")

        # Verify in DB
        results = list(self.prompt_container.query_items(
            query="SELECT * FROM c WHERE c.username = 'prompt_creator'", 
            partition_key="prompt_creator"))
        self.assertEqual(len(results), 1)
        
        prompt_doc = results[0]
        # Check duplicate tags were removed
        self.assertEqual(prompt_doc["tags"], ["test", "valid"]) 
        
        # Check translations
        self.assertEqual(len(prompt_doc["texts"]), 6) # en, cy, es, ta, zh-Hans, ar
        langs = {t["language"] for t in prompt_doc["texts"]}
        self.assertEqual(langs, {"en", "cy", "es", "ta", "zh-Hans", "ar"})
        
        # Check original text was used for 'en'
        en_text = next(t["text"] for t in prompt_doc["texts"] if t["language"] == "en")
        self.assertEqual(en_text, payload["text"])

    def test_prompt_player_does_not_exist(self):
        payload = {"username": "no_user", "text": "This text is valid but the user is not.", "tags": []}
        response = requests.post(self.TEST_URL, json=payload, headers=HEADERS)
        data = response.json()
        self.assertFalse(data["result"])
        self.assertEqual(data["msg"], "Player does not exist")

    def test_prompt_text_length_validation(self):
        payload = {"username": "prompt_creator", "text": "Too short.", "tags": []}
        response = requests.post(self.TEST_URL, json=payload, headers=HEADERS)
        data = response.json()
        self.assertFalse(data["result"])
        self.assertEqual(data["msg"], "Prompt less than 20 characters or more than 120 characters")

    def test_prompt_unsupported_language(self):
        # Per FAQ, use numbers to get confidence < 0.2
        payload = {"username": "prompt_creator", "text": "123456789012345678901", "tags": []}
        response = requests.post(self.TEST_URL, json=payload, headers=HEADERS)
        data = response.json()
        self.assertFalse(data["result"])
        self.assertEqual(data["msg"], "Unsupported language")

# --------------------------------------------

class TestPromptModerateFunction(BaseTestCase):
    """Tests for /prompt/moderate"""
    TEST_URL = f"{BASE_URL}/prompt/moderate"

    def setUp(self):
        super().setUp()
        # Create prompts directly in DB
        self.safe_prompt = self.prompt_container.create_item({
            "id": "safe1", "username": "mod_user",
            "texts": [{"language": "en", "text": "This is a perfectly safe and friendly prompt."}, {"language": "es", "text": "..."}],
            "tags": []
        })
        
        # This text is known to trigger Content Safety
        self.unsafe_prompt = self.prompt_container.create_item({
            "id": "unsafe1", "username": "mod_user",
            "texts": [{"language": "en", "text": "I hate monkey and want to kill and rape them"}, {"language": "es", "text": "..."}],
            "tags": []
        })
    
    def test_moderate_safe_and_unsafe(self):
        payload = {"prompt-ids": ["safe1", "unsafe1", "nonexistent-id"]}
        response = requests.post(self.TEST_URL, json=payload, headers=HEADERS)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        self.assertEqual(len(data), 2)
        results = {item["prompt-id"]: item for item in data}
        
        # Check safe prompt (outcome=false)
        self.assertIn("safe1", results)
        self.assertFalse(results["safe1"]["outcome"])
        self.assertLessEqual(results["safe1"]["average_severity"], 2)

        # Check unsafe prompt (outcome=true)
        self.assertIn("unsafe1", results)
        self.assertTrue(results["unsafe1"]["outcome"])
        self.assertGreater(results["unsafe1"]["average_severity"], 2)

        # Check non-existent prompt is not in results
        self.assertNotIn("nonexistent-id", results)

# --------------------------------------------

class TestPromptDeleteFunction(BaseTestCase):
    """Tests for /prompt/delete"""
    TEST_URL = f"{BASE_URL}/prompt/delete"

    def setUp(self):
        super().setUp()
        self.prompt_container.create_item({"id": "p1", "username": "user_A", "texts": [], "tags": []})
        self.prompt_container.create_item({"id": "p2", "username": "user_A", "texts": [], "tags": []})
        self.prompt_container.create_item({"id": "p3", "username": "user_B", "texts": [], "tags": []})

    def test_delete_prompts_for_user(self):
        payload = {"player": "user_A"}
        response = requests.post(self.TEST_URL, json=payload, headers=HEADERS)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        self.assertTrue(data["result"])
        self.assertEqual(data["msg"], "2 prompts deleted")

        # Verify DB state
        results_A = list(self.prompt_container.query_items(
            query="SELECT * FROM c WHERE c.username = 'user_A'", partition_key="user_A"))
        self.assertEqual(len(results_A), 0)
        
        results_B = list(self.prompt_container.query_items(
            query="SELECT * FROM c WHERE c.username = 'user_B'", partition_key="user_B"))
        self.assertEqual(len(results_B), 1)

    def test_delete_for_user_with_no_prompts(self):
        payload = {"player": "user_C"} # User with no prompts
        response = requests.post(self.TEST_URL, json=payload, headers=HEADERS)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        self.assertTrue(data["result"])
        self.assertEqual(data["msg"], "0 prompts deleted")

# --------------------------------------------

class TestUtilsGetFunction(BaseTestCase):
    """Tests for /utils/get"""
    TEST_URL = f"{BASE_URL}/utils/get"

    def setUp(self):
        super().setUp()
        # Re-create example from spec
        self.prompt_container.create_item({"id": "auto-gen-1", "username": "py_luis", "texts": [], "tags": ["Programming"]})
        self.prompt_container.create_item({"id": "auto-gen-2", "username": "py_luis", "texts": [], "tags": ["Generation", "Question"]})
        self.prompt_container.create_item({"id": "auto-gen-3", "username": "js_packer", "texts": [], "tags": ["Generation", "Question"]})
        self.prompt_container.create_item({"id": "auto-gen-4", "username": "les_cobol", "texts": [], "tags": ["Boomer", "Question"]})
        self.prompt_container.create_item({"id": "auto-gen-5", "username": "les_cobol", "texts": [], "tags": ["Boomer", "Pub Jokes"]})

    def test_get_prompts_spec_example(self):
        payload = {"players": ["py_luis", "les_cobol"], "tag_list": ["Programming", "Boomer", "Millenial"]}
        response = requests.get(self.TEST_URL, json=payload, headers=HEADERS)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        self.assertEqual(len(data), 3)
        ids = {item["id"] for item in data}
        self.assertEqual(ids, {"auto-gen-1", "auto-gen-4", "auto-gen-5"})

    def test_get_prompts_no_matching_tags(self):
        payload = {"players": ["py_luis", "les_cobol"], "tag_list": ["NonExistentTag"]}
        response = requests.get(self.TEST_URL, json=payload, headers=HEADERS)
        data = response.json()
        self.assertEqual(len(data), 0)

    def test_get_prompts_no_matching_players(self):
        payload = {"players": ["no_user_1"], "tag_list": ["Programming", "Boomer"]}
        response = requests.get(self.TEST_URL, json=payload, headers=HEADERS)
        data = response.json()
        self.assertEqual(len(data), 0)

# --------------------------------------------

class TestUtilsWelcomeTrigger(BaseTestCase):
    """Tests for the /utils/welcome CosmosDB trigger"""

    def test_trigger_on_new_player(self):
        """Test that creating a new player creates a welcome prompt."""
        new_player_username = "welcome_user"
        
        # 1. Create a new player directly
        self._create_player(new_player_username, "pass", games=0, score=0)

        # 2. Wait for the trigger to fire (as per FAQ)
        print("\n(test_trigger_on_new_player) Waiting 5s for welcome trigger...")
        time.sleep(5) 

        # 3. Query the prompt container
        results = list(self.prompt_container.query_items(
            query="SELECT * FROM c WHERE c.username = @username",
            parameters=[{"name": "@username", "value": new_player_username}],
            partition_key=new_player_username
        ))

        # 4. Assert
        self.assertEqual(len(results), 1, "Welcome prompt was not created")
        prompt_doc = results[0]
        self.assertEqual(prompt_doc["username"], new_player_username)
        self.assertEqual(prompt_doc["tags"], []) # Must have empty tags
        self.assertEqual(len(prompt_doc["texts"]), 6) # Must be fully translated
        
        en_text = next(t["text"] for t in prompt_doc["texts"] if t["language"] == "en")
        self.assertEqual(en_text, f"Welcome to COMP3207, {new_player_username}")

    def test_trigger_does_not_fire_on_update(self):
        """Test that updating a player does NOT create a welcome prompt."""
        username = "update_user_no_welcome"
        
        # 1. Create a player (this will fire the trigger)
        player_doc = self._create_player(username, "pass", games=0, score=0)
        
        print("\n(test_trigger_does_not_fire_on_update) Waiting 5s for initial trigger...")
        time.sleep(5) 
        
        # Check that 1 prompt exists
        results = list(self.prompt_container.query_items(
            query="SELECT * FROM c WHERE c.username = @username",
            parameters=[{"name": "@username", "value": username}],
            partition_key=username))
        self.assertEqual(len(results), 1, "Initial welcome prompt failed to create")
        
        # 2. Now, update the player (simulating /player/update)
        player_doc["games_played"] = 1
        player_doc["total_score"] = 10
        self.player_container.replace_item(item=player_doc["id"], body=player_doc)
        
        # 3. Wait again
        print("(test_trigger_does_not_fire_on_update) Waiting 5s to check for 2nd trigger...")
        time.sleep(5)
        
        # 4. Check prompt container again
        results = list(self.prompt_container.query_items(
            query="SELECT * FROM c WHERE c.username = @username",
            parameters=[{"name": "@username", "value": username}],
            partition_key=username))
        
        # The count should STILL be 1
        self.assertEqual(len(results), 1, "Trigger incorrectly fired on player update")

# --------------------------------------------

if __name__ == '__main__':
    unittest.main()