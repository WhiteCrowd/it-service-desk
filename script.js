// This file talks to the Flask API and updates the page.

var config = {};   // categories, priorities, statuses, technicians

// ---------- Helper functions ----------

// send a request to the API and return the answer
async function api(path, method, body) {
  var options = { method: method || "GET", headers: {} };

  if (body) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }

  var response = await fetch(path, options);
  var data = await response.json();

  if (!response.ok) {
    throw new Error(data.error || "Something went wrong");
  }
  return data;
}

// make text safe before putting it in the page
function escapeHtml(text) {
  if (text === null || text === undefined) {
    return "";
  }
  var div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

// show a green or red message at the top
function showMessage(text, isError) {
  var box = document.getElementById("message");
  box.textContent = text;
  if (isError) {
    box.className = "error";
  } else {
    box.className = "ok";
  }
}

// fill a dropdown with options
function fillSelect(selectId, items, firstText) {
  var html = "";
  if (firstText) {
    html = '<option value="">' + firstText + "</option>";
  }
  for (var i = 0; i < items.length; i++) {
    html += "<option>" + escapeHtml(items[i]) + "</option>";
  }
  document.getElementById(selectId).innerHTML = html;
}

// is the request past its due time?
function isOverdue(ticket) {
  if (ticket.status === "Resolved" || ticket.status === "Closed") {
    return false;
  }
  var due = new Date(ticket.due_at.replace(" ", "T"));
  return due < new Date();
}

// ---------- Summary ----------
async function loadSummary() {
  var s = await api("/reports/summary");
  var open = 0;
  var statuses = ["New", "Assigned", "In Progress", "On Hold"];
  for (var i = 0; i < statuses.length; i++) {
    open += s.by_status[statuses[i]] || 0;
  }
  var resolved = s.by_status["Resolved"] || 0;

  document.getElementById("summary").innerHTML =
    "<span>Total: <b>" + s.total + "</b></span>" +
    "<span>Open: <b>" + open + "</b></span>" +
    "<span>Resolved: <b>" + resolved + "</b></span>" +
    "<span>Overdue: <b>" + s.overdue + "</b></span>";
}

// ---------- Table of requests ----------
async function loadTickets() {
  var status = document.getElementById("filterStatus").value;
  var priority = document.getElementById("filterPriority").value;

  var url = "/requests?";
  if (status !== "") {
    url += "status=" + encodeURIComponent(status) + "&";
  }
  if (priority !== "") {
    url += "priority=" + encodeURIComponent(priority);
  }

  var tickets = await api(url);
  var html = "";

  for (var i = 0; i < tickets.length; i++) {
    var t = tickets[i];
    var rowClass = "";
    if (isOverdue(t)) {
      rowClass = "overdue";
    }

    html += '<tr class="' + rowClass + '">' +
      "<td>" + t.id + "</td>" +
      "<td>" + escapeHtml(t.title) + "</td>" +
      "<td>" + escapeHtml(t.category) + "</td>" +
      '<td class="' + t.priority + '">' + t.priority + "</td>" +
      "<td>" + t.status + "</td>" +
      "<td>" + escapeHtml(t.assignee || "-") + "</td>" +
      "<td>" + t.due_at.slice(0, 16) + "</td>" +
      '<td><button class="view" data-id="' + t.id + '">View</button></td>' +
      "</tr>";
  }

  if (tickets.length === 0) {
    html = '<tr><td colspan="8">No requests found.</td></tr>';
  }
  document.getElementById("ticketTable").innerHTML = html;

  // connect the View buttons
  var buttons = document.querySelectorAll("button.view");
  for (var j = 0; j < buttons.length; j++) {
    buttons[j].addEventListener("click", function () {
      showDetails(this.dataset.id);
    });
  }
}

async function loadAll() {
  try {
    await loadSummary();
    await loadTickets();
  } catch (error) {
    showMessage("Can't reach the server. Is app.py running?", true);
  }
}

// ---------- Details of one request ----------
async function showDetails(id) {
  try {
    var t = await api("/requests/" + id);

    // buttons for the allowed next statuses
    var statusButtons = "";
    for (var i = 0; i < t.allowed_statuses.length; i++) {
      var s = t.allowed_statuses[i];
      statusButtons += '<button class="status-btn" data-status="' + s + '">Move to ' + s + "</button>";
    }
    if (statusButtons === "") {
      statusButtons = "<p>No more steps for this request.</p>";
    }

    // dropdown with technicians
    var techOptions = "";
    for (var j = 0; j < config.technicians.length; j++) {
      var name = config.technicians[j];
      var selected = "";
      if (name === t.assignee) {
        selected = " selected";
      }
      techOptions += "<option" + selected + ">" + name + "</option>";
    }

    // history list
    var historyHtml = "";
    for (var k = 0; k < t.history.length; k++) {
      historyHtml += "<li>" + t.history[k].at.slice(0, 16) + " - " + escapeHtml(t.history[k].note) + "</li>";
    }

    var box = document.getElementById("details");
    box.style.display = "block";
    box.innerHTML =
      "<h2>Request #" + t.id + ": " + escapeHtml(t.title) + "</h2>" +
      "<p><b>Requester:</b> " + escapeHtml(t.requester) + "<br>" +
      "<b>Category:</b> " + escapeHtml(t.category) + "<br>" +
      "<b>Priority:</b> " + t.priority + "<br>" +
      "<b>Status:</b> " + t.status + "<br>" +
      "<b>Assigned to:</b> " + escapeHtml(t.assignee || "nobody") + "<br>" +
      "<b>Due:</b> " + t.due_at + "</p>" +
      "<p><b>Description:</b> " + escapeHtml(t.description) + "</p>" +
      "<h3>Change status</h3>" + statusButtons +
      "<h3>Assign to</h3>" +
      '<select id="assignSelect">' + techOptions + "</select>" +
      '<button id="assignBtn">Assign</button>' +
      "<h3>History</h3><ul>" + historyHtml + "</ul>" +
      '<button class="delete" id="deleteBtn">Delete request</button>' +
      '<button id="closeDetails">Close</button>';

    // connect the buttons we just created
    var statusBtns = document.querySelectorAll(".status-btn");
    for (var m = 0; m < statusBtns.length; m++) {
      statusBtns[m].addEventListener("click", function () {
        changeStatus(t.id, this.dataset.status);
      });
    }
    document.getElementById("assignBtn").addEventListener("click", function () {
      assignTicket(t.id, document.getElementById("assignSelect").value);
    });
    document.getElementById("deleteBtn").addEventListener("click", function () {
      deleteTicket(t.id);
    });
    document.getElementById("closeDetails").addEventListener("click", function () {
      box.style.display = "none";
    });

    box.scrollIntoView();
  } catch (error) {
    showMessage(error.message, true);
  }
}

// ---------- Actions ----------
async function changeStatus(id, newStatus) {
  try {
    await api("/requests/" + id + "/status", "PATCH", { status: newStatus });
    showMessage("Status changed to " + newStatus, false);
    showDetails(id);
    loadAll();
  } catch (error) {
    showMessage(error.message, true);
  }
}

async function assignTicket(id, name) {
  try {
    await api("/requests/" + id + "/assign", "PATCH", { assignee: name });
    showMessage("Assigned to " + name, false);
    showDetails(id);
    loadAll();
  } catch (error) {
    showMessage(error.message, true);
  }
}

async function deleteTicket(id) {
  if (!confirm("Delete request #" + id + "?")) {
    return;
  }
  try {
    await api("/requests/" + id, "DELETE");
    document.getElementById("details").style.display = "none";
    showMessage("Request deleted", false);
    loadAll();
  } catch (error) {
    showMessage(error.message, true);
  }
}

// ---------- New request form ----------
document.getElementById("newForm").addEventListener("submit", async function (event) {
  event.preventDefault();   // don't reload the page

  var data = {
    requester: document.getElementById("requester").value,
    title: document.getElementById("title").value,
    category: document.getElementById("category").value,
    priority: document.getElementById("priority").value,
    description: document.getElementById("description").value
  };

  try {
    var created = await api("/requests", "POST", data);
    showMessage("Request #" + created.id + " created, assigned to " + (created.assignee || "nobody"), false);
    document.getElementById("newForm").reset();
    document.getElementById("priority").value = "Medium";
    loadAll();
  } catch (error) {
    showMessage(error.message, true);
  }
});

// ---------- Start ----------
async function start() {
  try {
    config = await api("/config");
  } catch (error) {
    showMessage("Can't reach the server. Is app.py running?", true);
    return;
  }

  fillSelect("category", config.categories);
  fillSelect("priority", config.priorities);
  document.getElementById("priority").value = "Medium";
  fillSelect("filterStatus", config.statuses, "All");
  fillSelect("filterPriority", config.priorities, "All");

  document.getElementById("filterStatus").addEventListener("change", loadTickets);
  document.getElementById("filterPriority").addEventListener("change", loadTickets);

  loadAll();
}

start();
