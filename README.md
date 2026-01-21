# Taskanator

**Taskanator** is a task-managing chatbot that uses **Groq** and **Mem0** to interpret user messages and manage a **local task database**.

## Features

* Add tasks
* Mark tasks as complete
* Delete tasks
* Reactivate tasks
* Build a user profile over time
* Automatically reactivate tasks based on your history or behavioral patterns

---

## Setup Instructions

### 1. Groq API Key

1. Visit the Groq API dashboard:
   [https://console.groq.com/keys](https://console.groq.com/keys)
2. Create an API key.
3. Set the API key as an environment variable by running the following command in your terminal or command prompt :- setx GROQ_API_KEY "your_api_key_here"

### 2. Mem0 API Key

1. Visit the Mem0 dashboard:
   [https://app.mem0.ai/dashboard](https://app.mem0.ai/dashboard)
2. Create an API key.
3. Paste the API key into the location in the code where `"insert_api_key"` is specified.

---

Once both API keys are configured, the chatbot will be able to interpret your messages, manage tasks, and build a personalized task-handling profile based on your behavior.
