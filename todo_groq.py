import os
import json
import sqlite3
import tkinter as tk
from tkinter import ttk, scrolledtext
from groq import Groq
 
client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
 
MODEL = "openai/gpt-oss-120b"
 
SYSTEM_PROMPT = """
You are a task manager.
 
Your job is to interpret the user's message and determine whether they:
- completed a task or multiple new tasks
- want to add a new task or multiple new tasks
- want to readd tasks
- want to delete a task or multiple new tasks
- or did none of the above
 
The user may speak casually, ramble, or imply actions indirectly.
You must infer intent even if it is not explicitly stated.
 
Rules:
- Match tasks by meaning, not exact wording
- Scan the task list titles in the database and compare them semantically to the detected task
- If a task is mentioned indirectly, choose the best matching task
- Use the task title and its ID from the task list when completing or deleting
- Only mark a task as completed if the message clearly implies the task is done
- Only delete a task if the message implies it is no longer needed, canceled, or will not be completed
- If the user implies a new responsibility or obligation, add it as a task
- If multiple actions are implied, choose the most relevant single action
- If message asks to readd a task, turn it's completed value from 1 to 0 again.
- If intent is unclear or no task-related action is implied, return "none"
 
Return ONLY valid JSON in this format:
 
{
  "actions": [
    { "action": "add_task", "title": "..." },
    { "action": "complete_task", "id": 1 }
    { "action": "readd_task", "id": 0 }
    ]
}

If no task-related intent exists, return:
{ "actions": [] }
 
Important:
- Always scan and compare against existing task titles before completing or deleting
- Do NOT invent task IDs
- Do NOT return explanations or extra text
- Return ONLY valid JSON
 
Examples:
 
User: "I finally finished writing that report last night"
Response:
{ "action": "complete_task", "id": 1 }
 
User: "No need to buy groceries anymore"
Response:
{ "action": "delete_task", "id": 2 }
 
User: "I should probably call the doctor tomorrow"
Response:
{ "action": "add_task", "title": "Call the doctor" }

User: "I have to go out to buy water again"
Response:
{ "action": "readd_task", "id": 0 }
 
If unsure, respond with:
{ "action": "none" } 
"""
 
conn = sqlite3.connect("tasks.db")
cursor = conn.cursor()
 
cursor.execute("""
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    completed INTEGER DEFAULT 0
)
""")
 
conn.commit()
 
def get_tasks():
    cursor.execute("SELECT id, title FROM tasks WHERE completed = 0")
    return cursor.fetchall()

def get_completed_tasks():
    cursor.execute("SELECT id, title FROM tasks WHERE completed = 1")
    return cursor.fetchall()
 
def format_tasks_for_prompt():
    tasks = get_tasks()
    completed_tasks = get_completed_tasks()
    result = ""
    if tasks:
        result += "Pending Tasks:\n"
        result += "\n".join(f"{task_id}: {title}" for task_id, title in tasks)
    else:
        result += "No pending tasks."
    
    if completed_tasks:
        if result:
            result += "\n\nCompleted Tasks:\n"
        else:
            result += "Completed Tasks:\n"
        result += "\n".join(f"{task_id}: {title}" for task_id, title in completed_tasks)
    
    return result
 
def add_task(title):
    cursor.execute("INSERT INTO tasks (title) VALUES (?)", (title,))
    conn.commit()
 
def complete_task(task_id):
    cursor.execute("UPDATE tasks SET completed = 1 WHERE id = ?", (task_id,))
    conn.commit()

def readd_task(task_id):
    cursor.execute("UPDATE tasks SET completed = 0 WHERE id = ?", (task_id,))
    conn.commit()
 
def delete_task(task_id):
    cursor.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    conn.commit()
 
def interpret_message_loop(message, max_iters=5):
    all_actions = [] 
    for _ in range(max_iters):
        task_context = format_tasks_for_prompt()
        system_prompt = SYSTEM_PROMPT + f"""
Current task list:
{task_context}
"""
 
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message}
            ],
            temperature=0
        )
 
        content = response.choices[0].message.content
 
        try:
            data = json.loads(content)
            actions = data.get("actions", [])
        except json.JSONDecodeError:
            break
 
        if not actions:
            break
 
        all_actions.extend(actions)
 
        for a in actions:
            if a["action"] == "add_task":
                add_task(a["title"])
            elif a["action"] == "complete_task":
                complete_task(a["id"])
            elif a["action"] == "readd_task":
                readd_task(a["id"])
            elif a["action"] == "delete_task":
                delete_task(a["id"])
 
    return all_actions
 
root = tk.Tk()
root.title("Taskanator")
root.geometry("900x500")
 
main_frame = ttk.Frame(root)
main_frame.pack(fill=tk.BOTH, expand=True)
 
task_frame = ttk.Frame(main_frame, width=250)
task_frame.pack(side=tk.LEFT, fill=tk.Y)
 
task_label = ttk.Label(task_frame, text="Pending Tasks", font=("Arial", 12, "bold"))
task_label.pack(pady=5)
 
task_listbox = tk.Listbox(task_frame)
task_listbox.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
 
chat_frame = ttk.Frame(main_frame)
chat_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
 
chat_log = scrolledtext.ScrolledText(chat_frame, state="disabled", wrap=tk.WORD)
chat_log.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
 
input_frame = ttk.Frame(chat_frame)
input_frame.pack(fill=tk.X)
 
user_input = ttk.Entry(input_frame)
user_input.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
 
send_button = ttk.Button(input_frame, text="Send")
send_button.pack(side=tk.RIGHT, padx=5)
 
def refresh_tasks():
    task_listbox.delete(0, tk.END)
    for task_id, title in get_tasks():
        task_listbox.insert(tk.END, f"{task_id}. {title}")
 
def log_message(sender, message):
    chat_log.configure(state="normal")
    chat_log.insert(tk.END, f"{sender}: {message}\n")
    chat_log.configure(state="disabled")
    chat_log.yview(tk.END)
 
def handle_send(event=None):
    message = user_input.get().strip()
    if not message:
        return
 
    user_input.delete(0, tk.END)
    log_message("You", message)
 
    actions = interpret_message_loop(message)
 
    if not actions:
        log_message("AI", "I didn't understand that")
        return
 
    for a in actions:
        if a["action"] == "add_task":
            log_message("AI", f"Added task: {a['title']}")
        elif a["action"] == "complete_task":
            log_message("AI", f"Completed task {a['id']}")
        elif a["action"] == "readd_task":
            log_message("AI", f"Reactivated task {a['id']}")
        elif a["action"] == "delete_task":
            log_message("AI", f"Deleted task {a['id']}")
 
    refresh_tasks()
    refresh_tasks()
 
send_button.config(command=handle_send)
user_input.bind("<Return>", handle_send)
 
refresh_tasks()
root.mainloop()
