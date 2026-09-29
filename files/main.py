"""Chat with the assistant in the terminal: python main.py

It uses the same memory, documents, maths and web search as the web page, just without
the buttons (no Save cards, code running or upgrades).
"""
from answers import generate_answer, record_exchange
from llm_interface import LLMError
from services import conversation_history, llm_interface


def main():
    """Ask, answer and remember until the user types 'exit'."""
    print("=" * 60)
    print("Personal AI Assistant")
    print("Type 'exit' to quit, 'new' to start a new conversation, 'stats' for statistics")
    print("=" * 60)
    if not llm_interface.test_connection():
        print("Ollama isn't running. Start it (or install it from https://ollama.com), then try again.")
        return

    while True:
        try:
            user_input = input("\nYou: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye!")
            return
        command = user_input.lower()
        if command == "exit":
            print("Goodbye!")
            return
        if command == "stats":
            total = conversation_history.count_messages()
            print(f"Total messages stored: {total}\nConversations: {total // 2}")
            continue
        if command == "new":
            conversation_history.start_new_conversation()
            print("Started a new conversation.")
            continue
        if not user_input:
            continue
        try:
            answer = generate_answer(user_input)
        except LLMError as e:
            print(f"✗ {e}")
            continue
        record_exchange(user_input, answer)
        print(f"\nAI: {answer}")


if __name__ == "__main__":
    main()
