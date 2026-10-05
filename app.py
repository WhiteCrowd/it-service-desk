import sqlite3
from datetime import datetime, timedelta
from flask import Flask, jsonify, request

app = Flask(__name__)

Database = "service.db"

#1 settings below

Categories = ["Hardware", "Software", "Network", "Accounts & Access", "Email", "Other"]

Priorities = ["Low", "Medium", "High", "Critical"]

#hours for solving a request

SLA_HOURS = {"Low": 72, "Medium": 48, "High": 24, "Critical": 4}

Statuses = ["New", "Assigned", "In progress", "On Hold", "Resolved", "Closed"]

#workflow, basically from each status it goes to the next one, but also can go to previous

Next_Statuses = {
    "New": ["Assigned", "Closed"],
    "Assigned": ["In progress", "On Hold", "Closed"],
    "In progress": ["On Hold", "Resolved"],
    "On Hold": ["In progress", "Closed"],
    "Resolved": ["Closed", "In progress"],
    "Closed": [],
    
}
#which techician handles which categorie

Technicians = {
    "John": ["Hardware", "Software"],
    "Maria": ["Network", "Email"],
    "Roman": ["Accounts & Access", "Software", "Other"]
}

Open_Statuses = "('New', 'Assigned', 'In progress', 'On Hold')"


#2 Database helpers

def get_connection():
    conn = sqlite3.connect(Database)
    conn.row_factory = sqlite3.Row # allows to read columns by name
    return conn


def init_db():
    conn = get_connection()
    conn.execute("""CREATE TABLE IF NOT EXISTS tickets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        description TEXT,
        requester TEXT NOT NULL,
        category TEXT NOT NULL,
        priority TEXT NOT NULL,
        status TEXT NOT NULL,
        assignee TEXT,
        created_at TEXT NOT NULL,
        due_at TEXT NOT NULL,
        resolved_at TEXT
    )
    """)
    conn.execute("""CREATE TABLE IF NOT EXISTS comments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ticket_id INTEGER NOT NULL,
        at TEXT NOT NULL,
        note TEXT NOT NULL
    )
    """)
    conn.commit()
    conn.close()
    
    
def get_ticket(conn, ticket_id): #fetches one request and turns it into a dictionary
    row = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
    if row is None:
        return None
    return dict(row) #turining row into a normal dictionary


def current_time():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def hours_from_now(hours):
    later = datetime.now() + timedelta(hours=hours)
    return later.strftime("%Y-%m-%d %H:%M:%S")


def add_history(conn, ticket_id, note):
    conn.execute("INSERT INTO comments (ticket_id, at, note) VALUES (?, ?, ?)",
                 (ticket_id, current_time(), note))
     



#3 Validation

def read_json():    #returns the JSON body as a dictionary, or none if it is wrong
    data = request.get_json(silent=True)
    if isinstance(data, dict):
        return data
    return None


def check_data(data, must_have_all):
    for field in ["title", "requester", "category", "priority"]:
        if field not in data:
            if must_have_all:
                return field + " is required"
        elif str(data[field]).strip() == "":
            return field + " can't be empty"
    
    
    
    if "category" in data and data["category"] not in Categories:
        return "category must be one of: "+", ".join(Categories)
    if "priority" in data and data["priority"] not in Priorities:
        return "priority must be one of: "+", ".join(Priorities)
    return None



#4 Automation

def find_technician(conn, category):
    best_tech = None
    lowest_count = None

    for name in Technicians:
        if category not in Technicians[name]:
            continue
        row = conn.execute(
            "SELECT COUNT(*) FROM tickets WHERE assignee = ? AND status IN " + Open_Statuses,
            (name,)).fetchone()
        count = row[0]
        if lowest_count is None or count < lowest_count:
            best_tech = name
            lowest_count = count

    return best_tech



def is_overdue(ticket):
    if ticket["status"] in ["Resolved", "Closed"]:
        return False
    return ticket["due_at"] < current_time()



def escalate_overdue(conn):      #raising priority by one level for open request past their due time
    rows = conn.execute("SELECT * FROM tickets WHERE status IN "+ Open_Statuses).fetchall()
    
    for row in rows:
        ticket = dict(row)
        if not is_overdue(ticket):
            continue
        
        position = Priorities.index(ticket["priority"])
        if position == len(Priorities) - 1:
            continue # if already Critical
        
        new_priority = Priorities[position + 1]
        conn.execute ("UPDATE tickets SET priority = ?, due_at = ? WHERE id = ?",
                      (new_priority, hours_from_now(SLA_HOURS[new_priority]), ticket["id"]))
        add_history(conn, ticket["id"],
                    "Auto-escalated " + ticket["priority"] + " -> " + new_priority)
        
    conn.commit()
    
         
        
    #5 API endpoints
 
@app.route("/")
def home():
    # the web page lives in static/index.html
    return app.send_static_file("index.html")


@app.route("/config", methods=["GET"])
def get_config():
    # the web page uses this to fill its dropdown lists
    return jsonify({"categories": Categories, "priorities": Priorities,
                    "statuses": Statuses, "technicians": list(Technicians)})
    
@app.route("/requests", methods=["POST"]) #validate, save, log, auto-assign
def add_request():
    data = read_json()
    if data is None:
        return jsonify({"error": "Send a JSON body"}), 400
        
    error = check_data(data, True)
    if error:
        return jsonify({"error": error}), 400
        
    conn = get_connection()
    due_at = hours_from_now(SLA_HOURS[data["priority"]])
    cursor = conn.execute(
        "INSERT INTO tickets (title, description, requester, category, priority, "
        "status, created_at, due_at) VALUES (?, ?, ?, ?, ?, 'New', ?, ?)",
        (data["title"].strip(), data.get("description", ""), data["requester"].strip(),
         data["category"], data["priority"], current_time(), due_at))
    ticket_id = cursor.lastrowid
    add_history(conn, ticket_id, "Request created")
    
    tech = find_technician(conn, data["category"])
    if tech is not None:
        conn.execute("UPDATE tickets SET assignee = ?, status = 'Assigned' WHERE id = ?",
                     (tech, ticket_id))
        add_history(conn, ticket_id, "Auto-assigned to " + tech)
    conn.commit()
    ticket = get_ticket(conn, ticket_id)
    conn.close()
    return jsonify(ticket), 201
 
 
@app.route("/requests", methods=["GET"]) #list, with filters 
def list_requests():
    conn = get_connection()
    escalate_overdue(conn)
 
    # optional filters: /requests?status=New&priority=High
    query = "SELECT * FROM tickets WHERE 1=1"
    params = []
    for field in ["status", "priority", "category", "assignee"]:
        value = request.args.get(field)
        if value:
            query = query + " AND " + field + " = ?"
            params.append(value)
    query = query + " ORDER BY id"
 
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return jsonify([dict(row) for row in rows])
 
 
@app.route("/requests/<int:ticket_id>", methods=["GET"]) #one request plus its history and overdue flag
def get_request(ticket_id):
    conn = get_connection()
    ticket = get_ticket(conn, ticket_id)
    if ticket is None:
        conn.close()
        return jsonify({"error": "Request not found"}), 404
 
    rows = conn.execute("SELECT at, note FROM comments WHERE ticket_id = ? ORDER BY id",
                        (ticket_id,)).fetchall()
    conn.close()
    ticket["overdue"] = is_overdue(ticket)
    ticket["allowed_statuses"] = Next_Statuses[ticket["status"]]
    ticket["history"] = [dict(row) for row in rows]
    return jsonify(ticket)
 
 
@app.route("/requests/<int:ticket_id>", methods=["PUT"]) #edit title, description, category, priority
def update_request(ticket_id):
    data = read_json()
    if data is None:
        return jsonify({"error": "Send a JSON body"}), 400
    error = check_data(data, False)
    if error:
        return jsonify({"error": error}), 400
 
    conn = get_connection()
    ticket = get_ticket(conn, ticket_id)
    if ticket is None:
        conn.close()
        return jsonify({"error": "Request not found"}), 404
 
    # uses the new value if sent, otherwise keep the old one
    title = data.get("title", ticket["title"])
    description = data.get("description", ticket["description"])
    category = data.get("category", ticket["category"])
    priority = data.get("priority", ticket["priority"])
 
    due_at = ticket["due_at"]
    if priority != ticket["priority"]:
        due_at = hours_from_now(SLA_HOURS[priority])   # new priority = new deadline
 
    conn.execute("UPDATE tickets SET title = ?, description = ?, category = ?, "
                 "priority = ?, due_at = ? WHERE id = ?",
                 (title, description, category, priority, due_at, ticket_id))
    add_history(conn, ticket_id, "Request edited")
    conn.commit()
    ticket = get_ticket(conn, ticket_id)
    conn.close()
    return jsonify(ticket)
 
 
@app.route("/requests/<int:ticket_id>/status", methods=["PATCH"]) #change status, but only along allowed transitions
def change_status(ticket_id):
    data = read_json()
    if data is None or "status" not in data:
        return jsonify({"error": "status is required"}), 400
    new_status = data["status"]
    if new_status not in Statuses:
        return jsonify({"error": "status must be one of: " + ", ".join(Statuses)}), 400
 
    conn = get_connection()
    ticket = get_ticket(conn, ticket_id)
    if ticket is None:
        conn.close()
        return jsonify({"error": "Request not found"}), 404
 
    # workflow rule
    if new_status not in Next_Statuses[ticket["status"]]:
        conn.close()
        return jsonify({"error": "Can't move from " + ticket["status"] + " to " + new_status,
                        "allowed": Next_Statuses[ticket["status"]]}), 400
 
    resolved_at = ticket["resolved_at"]
    if new_status == "Resolved":
        resolved_at = current_time()
 
    conn.execute("UPDATE tickets SET status = ?, resolved_at = ? WHERE id = ?",
                 (new_status, resolved_at, ticket_id))
    add_history(conn, ticket_id, "Status: " + ticket["status"] + " -> " + new_status)
    conn.commit()
    ticket = get_ticket(conn, ticket_id)
    conn.close()
    return jsonify(ticket)
 
 
@app.route("/requests/<int:ticket_id>/assign", methods=["PATCH"]) #reassign to another technician
def assign_request(ticket_id):
    data = read_json()
    if data is None or data.get("assignee") not in Technicians:
        return jsonify({"error": "assignee must be one of: " + ", ".join(Technicians)}), 400
 
    conn = get_connection()
    ticket = get_ticket(conn, ticket_id)
    if ticket is None:
        conn.close()
        return jsonify({"error": "Request not found"}), 404
 
    status = ticket["status"]
    if status == "New":
        status = "Assigned"
 
    conn.execute("UPDATE tickets SET assignee = ?, status = ? WHERE id = ?",
                 (data["assignee"], status, ticket_id))
    add_history(conn, ticket_id, "Reassigned to " + data["assignee"])
    conn.commit()
    ticket = get_ticket(conn, ticket_id)
    conn.close()
    return jsonify(ticket)
 
 
@app.route("/requests/<int:ticket_id>", methods=["DELETE"]) #delete the request and its history
def delete_request(ticket_id):
    conn = get_connection()
    if get_ticket(conn, ticket_id) is None:
        conn.close()
        return jsonify({"error": "Request not found"}), 404
 
    conn.execute("DELETE FROM comments WHERE ticket_id = ?", (ticket_id,))
    conn.execute("DELETE FROM tickets WHERE id = ?", (ticket_id,))
    conn.commit()
    conn.close()
    return jsonify({"message": "Request " + str(ticket_id) + " deleted"})
 
 
@app.route("/reports/summary", methods=["GET"]) #counts by status, priority, category, and overdue
def summary():
    conn = get_connection()
    escalate_overdue(conn)
    rows = conn.execute("SELECT * FROM tickets").fetchall()
    conn.close()
 
    report = {"total": len(rows), "overdue": 0,
              "by_status": {}, "by_priority": {}, "by_category": {}}
    for row in rows:
        ticket = dict(row)
        report["by_status"][ticket["status"]] = report["by_status"].get(ticket["status"], 0) + 1
        report["by_priority"][ticket["priority"]] = report["by_priority"].get(ticket["priority"], 0) + 1
        report["by_category"][ticket["category"]] = report["by_category"].get(ticket["category"], 0) + 1
        if is_overdue(ticket):
            report["overdue"] = report["overdue"] + 1
    return jsonify(report)
 
 
if __name__ == "__main__":
    init_db()
    app.run(debug=True)
        
