"""Tests never send traces anywhere, whatever .env says (the fast tests use scripted models and fakes)."""
import os

os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"
