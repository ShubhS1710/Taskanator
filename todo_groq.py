import os
import json
import sqlite3
import tkinter as tk
from tkinter import ttk, scrolledtext
import threading
import queue
import ctypes
from groq import Groq
import datetime
from mem0 import MemoryClient
 
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
conn = sqlite3.connect("tasks.db", check_same_thread=False) 
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    completed INTEGER DEFAULT 0
)
""")
conn.commit()

db_lock = threading.Lock()


MEM0_API_KEY = "m0-tbkfm1gH6vXbyxcai95db0gjbttxrHMrui4HHnUr"
mem_client = MemoryClient(api_key=MEM0_API_KEY)
USER_ID = "taskanator_user"


def get_tasks():
    with db_lock:
        cursor.execute("SELECT id, title FROM tasks WHERE completed = 0")
        return cursor.fetchall()

def get_completed_tasks():
    with db_lock:
        cursor.execute("SELECT id, title FROM tasks WHERE completed = 1")
        return cursor.fetchall()

def add_task(title):
    with db_lock:
        cursor.execute("INSERT INTO tasks (title) VALUES (?)", (title,))
        conn.commit()
    try:
        mem_client.add(f"User added task '{title}' on {datetime.date.today()}", user_id=USER_ID)
    except Exception as e:
        print(f"Mem0 Error: {e}")

def complete_task(task_id):
    title = ""
    with db_lock:
        cursor.execute("SELECT title FROM tasks WHERE id = ?", (task_id,))
        row = cursor.fetchone()
        if row:
            title = row[0]
            cursor.execute("UPDATE tasks SET completed = 1 WHERE id = ?", (task_id,))
            conn.commit()
    
    if title:
        try:
            mem_client.add(f"User completed task '{title}' on {datetime.date.today()}", user_id=USER_ID)
        except Exception as e:
            print(f"Mem0 Error: {e}")

def readd_task(task_id):
    title = ""
    with db_lock:
        cursor.execute("SELECT title FROM tasks WHERE id = ?", (task_id,))
        row = cursor.fetchone()
        if row:
            title = row[0]
            cursor.execute("UPDATE tasks SET completed = 0 WHERE id = ?", (task_id,))
            conn.commit()
            
    if title:
        try:
            mem_client.add(f"User reactivated task '{title}' on {datetime.date.today()}", user_id=USER_ID)
        except Exception as e:
             print(f"Mem0 Error: {e}")

def delete_task(task_id):
    with db_lock:
        cursor.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        conn.commit()

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
        result += "\n\nCompleted Tasks:\n" if result else "Completed Tasks:\n"
        result += "\n".join(f"{task_id}: {title}" for task_id, title in completed_tasks)
    return result



def smart_reactivation_check(callback_queue):
    """
    Checks if any completed tasks should be reactivated based on Mem0 history and current date.
    """
    try:
        completed = get_completed_tasks()
        if not completed:
            return

        today = datetime.date.today()
        
        memories_response = mem_client.search("task frequency schedule habits", filters={"user_id": USER_ID})
        
        if isinstance(memories_response, dict):
             memories = memories_response.get("results", [])
        else:
             memories = memories_response
             
        memory_text = "\n".join([m['memory'] for m in memories]) if memories else "No specific memories found."
        
        completed_list_str = "\n".join([f"{tid}: {title}" for tid, title in completed])

        prompt = f"""
Current Date: {today}

User Memories (Task Habits):
{memory_text}

Currently COMPLETED Tasks:
{completed_list_str}

Based strictly on the user's past habits/memories and today's date, should any of the completed tasks be reactivated TODAY?
Example: If user buys milk weekly on Saturday and today is Saturday, reactivate "Buy Milk".
Example: If user gets car serviced in Jan and it is Jan, reactivate "Service Car".

Return JSON ONLY:
{{
  "reactivate": [
     {{ "id": 1, "reason": "It is Saturday and you usually buy milk on Saturdays." }}
  ]
}}
If none, return {{ "reactivate": [] }}
"""
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": "You are a smart task scheduler."},
                {"role": "user", "content": prompt}
            ],
            temperature=0
        )
        
        content = response.choices[0].message.content
        data = json.loads(content)
        to_reactivate = data.get("reactivate", [])
        
        for item in to_reactivate:
            tid = item["id"]
            reason = item["reason"]
            readd_task(tid)
            callback_queue.put(("log", f" Smart Manager: Reactivated task {tid} because: {reason}"))
            callback_queue.put(("refresh", None))
            
    except Exception as e:
        print(f"Smart Check Error: {e}")

def process_message_thread(message, callback_queue):
    all_actions = [] 
    max_iters = 5
    
    try:
        for i in range(max_iters):
            
            task_context = format_tasks_for_prompt()
            system_prompt = SYSTEM_PROMPT + f"\nCurrent task list:\n{task_context}\n"
    
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
                    callback_queue.put(("log", f"Added task: {a['title']}"))
                elif a["action"] == "complete_task":
                    complete_task(a["id"])
                    callback_queue.put(("log", f"Completed task {a['id']}"))
                elif a["action"] == "readd_task":
                    readd_task(a["id"])
                    callback_queue.put(("log", f"Reactivated task {a['id']}"))
                elif a["action"] == "delete_task":
                    delete_task(a["id"])
                    callback_queue.put(("log", f"Deleted task {a['id']}"))
            
            callback_queue.put(("refresh", None))
            
    except Exception as e:
        callback_queue.put(("log", f"Error: {str(e)}"))

    threading.Thread(target=smart_reactivation_check, args=(callback_queue,), daemon=True).start()

    callback_queue.put(("done", None))

root = tk.Tk()
root.title("Taskanator")
root.geometry("900x500")

def apply_dark_title_bar():
    root.update()
    try:
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        value = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(value), 4)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 19, ctypes.byref(value), 4)
    except Exception:
        pass
apply_dark_title_bar()

COLORS = {
    "bg_main": "#36393f",
    "bg_sec": "#2f3136",
    "bg_ter": "#202225",
    "text": "#dcddde",
    "accent": "#5865F2",
    "success": "#57F287",
    "entry_bg": "#40444b",
    "selection": "#5865F2",
    "scrollbar": "#202225",
    "thumb": "#202225",
    "arrow": "#dcddde"
}

root.configure(bg=COLORS["bg_main"])

style = ttk.Style()
style.theme_use('clam') 

style.configure("TFrame", background=COLORS["bg_main"])
style.configure("TLabel", background=COLORS["bg_sec"], foreground=COLORS["text"], font=("Segoe UI", 12))
style.configure("Header.TLabel", background=COLORS["bg_sec"], foreground=COLORS["text"], font=("Segoe UI", 11, "bold"))
style.configure("TButton", 
                background=COLORS["accent"], 
                foreground="white", 
                borderwidth=0, 
                focuscolor=COLORS["accent"],
                font=("Segoe UI", 10, "bold"))
style.map("TButton", background=[("active", "#4752c4")]) 

style.configure("TEntry", 
                fieldbackground=COLORS["entry_bg"], 
                foreground=COLORS["text"], 
                insertcolor=COLORS["text"],
                borderwidth=0)

style.layout("Dark.Vertical.TScrollbar",
             [('Vertical.Scrollbar.trough',
               {'children': [('Vertical.Scrollbar.thumb', 
                              {'expand': '1', 'sticky': 'nswe'})],
                'sticky': 'ns'})])

style.configure("Dark.Vertical.TScrollbar", 
                main_background=COLORS["scrollbar"],
                troughcolor=COLORS["scrollbar"],
                background=COLORS["entry_bg"],
                arrowcolor=COLORS["arrow"],
                bordercolor=COLORS["bg_sec"],
                lightcolor=COLORS["entry_bg"],
                darkcolor=COLORS["entry_bg"],
                relief="flat",
                borderwidth=0)

style.map("Dark.Vertical.TScrollbar",
          background=[('active', COLORS["accent"]), ('!disabled', COLORS["entry_bg"])],
          arrowcolor=[('active', 'white'), ('!disabled', COLORS["arrow"])])

def make_dark_scrollbar(master):
    return ttk.Scrollbar(master, orient="vertical", style="Dark.Vertical.TScrollbar")

msg_queue = queue.Queue()

def check_queue():
    while not msg_queue.empty():
        msg_type, content = msg_queue.get()
        if msg_type == "log":
            log_message("AI", content)
        elif msg_type == "refresh":
            refresh_tasks()
        elif msg_type == "done":
            send_button.config(state="normal", text="Send")
            user_input.config(state="normal")
            user_input.delete(0, tk.END)
            user_input.focus()
    root.after(100, check_queue)

main_frame = ttk.Frame(root)
main_frame.pack(fill=tk.BOTH, expand=True)

task_frame = tk.Frame(main_frame, bg=COLORS["bg_sec"], width=250)
task_frame.pack(side=tk.LEFT, fill=tk.Y)
task_frame.pack_propagate(False)

task_header = tk.Label(task_frame, text="PENDING TASKS", bg=COLORS["bg_sec"], fg="#8e9297", font=("Segoe UI", 9, "bold"))
task_header.pack(pady=(15, 10), padx=10, anchor="w")

task_list_container = tk.Frame(task_frame, bg=COLORS["bg_sec"])
task_list_container.pack(fill=tk.BOTH, expand=True, padx=5, pady=(0, 5))

task_scrollbar = make_dark_scrollbar(task_list_container)
task_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

task_listbox = tk.Listbox(task_list_container, 
                          bg=COLORS["bg_sec"], 
                          fg=COLORS["text"], 
                          bd=0, 
                          highlightthickness=0,
                          selectbackground=COLORS["selection"],
                          font=("Segoe UI", 10),
                          yscrollcommand=task_scrollbar.set)
task_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
task_scrollbar.config(command=task_listbox.yview)

chat_frame = tk.Frame(main_frame, bg=COLORS["bg_main"])
chat_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

chat_container = tk.Frame(chat_frame, bg=COLORS["bg_main"])
chat_container.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

chat_scrollbar = make_dark_scrollbar(chat_container)
chat_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

chat_log = tk.Text(chat_container, 
                   state="disabled", 
                   wrap=tk.WORD, 
                   bg=COLORS["bg_main"], 
                   fg=COLORS["text"],
                   bd=0,
                   font=("Segoe UI", 10),
                   insertbackground=COLORS["text"],
                   yscrollcommand=chat_scrollbar.set)
chat_log.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
chat_scrollbar.config(command=chat_log.yview)

input_frame = tk.Frame(chat_frame, bg=COLORS["bg_main"])
input_frame.pack(fill=tk.X, padx=20, pady=(0, 20))

entry_bg_frame = tk.Frame(input_frame, bg=COLORS["entry_bg"], bd=0)
entry_bg_frame.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=5)

user_input = tk.Entry(entry_bg_frame, 
                      bg=COLORS["entry_bg"], 
                      fg=COLORS["text"], 
                      bd=0, 
                      insertbackground=COLORS["text"],
                      disabledbackground=COLORS["entry_bg"],
                      disabledforeground=COLORS["text"],
                      font=("Segoe UI", 10))
user_input.pack(fill=tk.X, expand=True, padx=10)

send_button = ttk.Button(input_frame, text="Send", cursor="hand2")
send_button.pack(side=tk.RIGHT, padx=(10, 0))

def refresh_tasks():
    task_listbox.delete(0, tk.END)
    for task_id, title in get_tasks():
        task_listbox.insert(tk.END, f"{task_id}. {title}")

def log_message(sender, message):
    chat_log.configure(state="normal")
    
    tag = "user_tag" if sender == "You" else "ai_tag"
    chat_log.tag_config("user_tag", foreground="#ffffff", font=("Segoe UI", 10, "bold"))
    chat_log.tag_config("ai_tag", foreground=COLORS["accent"], font=("Segoe UI", 10, "bold"))
    
    chat_log.insert(tk.END, f"{sender}: ", tag)
    chat_log.insert(tk.END, f"{message}\n")
    
    chat_log.configure(state="disabled")
    chat_log.yview(tk.END)

def handle_send(event=None):
    message = user_input.get().strip()
    if not message:
        return

    user_input.delete(0, tk.END)
    log_message("You", message)
    
    send_button.config(state="disabled", text="Thinking...")
    
    user_input.config(state="normal")
    user_input.insert(0, "....")
    user_input.config(state="disabled")
    
    t = threading.Thread(target=process_message_thread, args=(message, msg_queue))
    t.start()
    
send_button.config(command=handle_send)
user_input.bind("<Return>", handle_send)

check_queue()

threading.Thread(target=smart_reactivation_check, args=(msg_queue,), daemon=True).start()

refresh_tasks()
root.mainloop()

