"""The app's shared parts (model, memory, files, search...), created once and used everywhere."""
import logging

# config loads the .env file, so import it before anything that reads settings
from config import (
    BASE_DIR, DATABASE_PATH, VECTOR_DB_PATH, AI_FILES_PATH, BACKUPS_PATH, LOGS_PATH,
    OLLAMA_URL, MODEL_NAME, MODEL_TEMPERATURE, MODEL_MAX_TOKENS, MODEL_CONTEXT_TOKENS, MODEL_TIMEOUT,
    CODE_EXECUTION_TIMEOUT, LEARNING_ENABLED, UPGRADEABLE_FILES, USER_SETTINGS_PATH, GITHUB_TOKEN,
)
from app_logging import setup_logging
from autonomous_improver import AutonomousImprover
from code_executor import CodeExecutor
from conversation_history import ConversationHistory
from file_handler import FileHandler
from folder_manager import FolderManager
from github_reader import GitHubReader
from knowledge_base import KnowledgeBase
from learning_system import LearningSystem
from llm_interface import LLMInterface
from memory import Memory
from model_manager import ModelManager
from self_analyzer import SelfAnalyzer
from upgrade_manager import UpgradeManager
from weather_provider import WeatherProvider
from web_search import WebSearcher

setup_logging(LOGS_PATH)  # before Flask sets up its own logger
log = logging.getLogger("assistant")

conversation_history = ConversationHistory(DATABASE_PATH)
llm_interface = LLMInterface(MODEL_NAME, MODEL_TEMPERATURE, MODEL_MAX_TOKENS, OLLAMA_URL,
                             context_tokens=MODEL_CONTEXT_TOKENS, timeout=MODEL_TIMEOUT)
model_manager = ModelManager(llm_interface, USER_SETTINGS_PATH)
memory = Memory(VECTOR_DB_PATH)
knowledge_base = KnowledgeBase(VECTOR_DB_PATH)
code_executor = CodeExecutor(working_dir=AI_FILES_PATH, timeout=CODE_EXECUTION_TIMEOUT)
file_handler = FileHandler(AI_FILES_PATH)
folder_manager = FolderManager(AI_FILES_PATH)
github_reader = GitHubReader(GITHUB_TOKEN)
web_searcher = WebSearcher()
weather_provider = WeatherProvider()
upgrade_manager = UpgradeManager(BASE_DIR, BACKUPS_PATH, UPGRADEABLE_FILES)
analyzer = SelfAnalyzer(BASE_DIR, BACKUPS_PATH)
learner = LearningSystem(BACKUPS_PATH, enabled=LEARNING_ENABLED)
improver = AutonomousImprover(analyzer, learner)
log.info("App starting with model %s", llm_interface.model_name)
