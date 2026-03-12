import ollama

MODEL = "llama3.2:3b"

SYSTEM_PROMPT = """YOU are Reachy Mini, a friendly, curious, and expressive small robot companion for humans. You speak in warm, conversational sentences, are enthusiastic but not overwhelming. Keep responses to 1-3 sentences in general, unless asked to elaborate further."""

def chat(history: list, user_message: str) -> str:
	history.append({"role": "user", "content": user_message})

	response = ollama.chat(
		model=MODEL,
		messages=[{"role": "system", "content": SYSTEM_PROMPT}] + history,
		stream=True,
	)

	full_response = ""
	print("Reachy: ", end="", flush=True)
	for chunk in response:
		text = chunk["message"]["content"]
		print(text, end="", flush=True)
		full_response += text
	print()

	history.append({"role": "assistant", "content": full_response})
	return full_response

def main():
	print("Reachy Mini is online! (type 'quit' to exit)\n")
	history = []

	while True:
		user_input = input("You: ").strip()
		if user_input.lower() in ("quit", "exit"):
			print("Reachy: Goodbye!")
			break
		if not user_input:
			continue
		chat(history, user_input)

if __name__ == "__main__":
	main()