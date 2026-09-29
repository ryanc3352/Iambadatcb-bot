from config import (
    DATABASE_PATH, OLLAMA_URL, MODEL_NAME, MODEL_TEMPERATURE, MODEL_MAX_TOKENS,
    MODEL_CONTEXT_TOKENS, MODEL_TIMEOUT, CONTEXT_MESSAGES, SYSTEM_PROMPT,
)
from llm_interface import LLMInterface, LLMError
from conversation_history import ConversationHistory

class PersonalAI:
    """Main AI assistant class that ties everything together"""

    def __init__(self):
        """Initialize all components"""
        print("Initializing Personal AI...\n")

        # Initialize the LLM interface (connects to Ollama)
        self.llm = LLMInterface(MODEL_NAME, MODEL_TEMPERATURE, MODEL_MAX_TOKENS, OLLAMA_URL,
                                context_tokens=MODEL_CONTEXT_TOKENS, timeout=MODEL_TIMEOUT)
        if not self.llm.test_connection():
            raise ConnectionError(f"Ollama is not reachable at {OLLAMA_URL}")

        # Initialize conversation history (database)
        self.history = ConversationHistory(DATABASE_PATH)

        print(f"✓ AI initialized with {MODEL_NAME} model")
        print(f"✓ Conversation history: {self.history.count_messages()} messages stored\n")

    def build_prompt(self, user_input):
        """
        Build the prompt to send to the model

        Combines:
        1. System prompt (instructions for the AI)
        2. Previous conversation messages (for context)
        3. Current user input

        Args:
            user_input: What the user just typed

        Returns:
            The full prompt as a string
        """
        # Get the last few messages for context
        recent_messages = self.history.get_last_n_messages(CONTEXT_MESSAGES)

        # Format them nicely
        conversation_context = ""
        if recent_messages:
            conversation_context = self.history.format_for_prompt(recent_messages)
            conversation_context = f"Previous conversation:\n{conversation_context}\n"

        # Build the complete prompt
        prompt = f"""{SYSTEM_PROMPT}

{conversation_context}User: {user_input}
Assistant:"""

        return prompt

    def chat(self, user_input):
        """
        Process a user message and generate a response

        Steps:
        1. Build a prompt with system instructions + context + user input
        2. Send to the LLM model
        3. Store both user message and response in history
        4. Return the response

        Args:
            user_input: What the user typed

        Returns:
            The AI's response
        """
        # Build the prompt first so the new message isn't repeated in the context
        prompt = self.build_prompt(user_input)

        # Get response from the model (raises LLMError if Ollama can't answer)
        response = self.llm.generate_response(prompt)

        # Store the exchange only once there is a real answer
        self.history.add_message("User", user_input)
        self.history.add_message("Assistant", response)

        return response

    def run(self):
        """Main loop - keep asking for input and responding"""
        print("=" * 60)
        print("Personal AI Assistant")
        print("Type 'exit' to quit, 'stats' to see conversation stats")
        print("=" * 60)
        print()

        while True:
            try:
                # Get user input
                user_input = input("You: ").strip()

                # Handle special commands
                if user_input.lower() == "exit":
                    print("\nGoodbye!")
                    break

                if user_input.lower() == "stats":
                    total = self.history.count_messages()
                    print(f"\nTotal messages stored: {total}")
                    print(f"Conversations: {total // 2}\n")
                    continue

                # Skip empty input
                if not user_input:
                    continue

                # Get and display response
                print("\nAI: ", end="", flush=True)
                response = self.chat(user_input)
                print(response)
                print()

            except LLMError as e:
                print(f"\n✗ {e}\n")
            except (KeyboardInterrupt, EOFError):
                print("\n\nInterrupted. Goodbye!")
                break
            except Exception as e:
                print(f"Error: {e}")
                print()

def main():
    """Entry point"""
    try:
        ai = PersonalAI()
        ai.run()
    except Exception as e:
        print(f"Failed to start: {e}")
        print("\nMake sure:")
        print("1. Ollama is installed: https://ollama.ai")
        print("2. Ollama is running: ollama serve")
        print("3. You have the model: ollama pull mistral")

if __name__ == "__main__":
    main()
